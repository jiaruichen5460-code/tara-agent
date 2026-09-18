from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl
import pytest

from tara_agent.data.preprocess import PreprocessingError, preprocess
from tara_agent.data.reader import ProcessedDataError, ProcessedDataReader
from tara_agent.domain.contracts import Marker


def _source_state(source_dir: Path) -> dict[str, tuple[int, int, str]]:
    state = {}
    for path in source_dir.glob("*.tsv"):
        stat = path.stat()
        state[path.name] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return state


def test_preprocess_is_read_only_repeatable_and_accessible(
    preprocessable_dataset_dir: Path, tmp_path: Path
) -> None:
    processed_dir = tmp_path / "processed"
    before = _source_state(preprocessable_dataset_dir)

    first = preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    first_hashes = {
        key: artifact.sha256 for key, artifact in first.manifest.artifacts.items()
    }
    second = preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    forced = preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        force=True,
        enforce_expected_shape=False,
    )

    assert first.status == "processed"
    assert second.status == "skipped"
    assert forced.status == "verified"
    assert before == _source_state(preprocessable_dataset_dir)
    assert first_hashes == {
        key: artifact.sha256 for key, artifact in forced.manifest.artifacts.items()
    }
    assert forced.manifest.metrics == first.manifest.metrics
    assert forced.manifest.benchmark_report is None
    assert not (processed_dir / forced.manifest.generation / "benchmark.json").exists()
    assert not list(processed_dir.glob(".staging-*"))

    store = ProcessedDataReader(processed_dir)
    context = store.load_sample_context(["TARA_TEST_001"])
    marker = store.load_marker_data(Marker.V4, sample_ids=["TARA_TEST_002"])

    assert context.height == 1
    assert context.schema["event_date"] == pl.Datetime("us")
    assert marker.select("TARA_TEST_002").item() == 2
    assert marker.schema["TARA_TEST_002"] == pl.UInt32


def test_preprocess_rejects_inconsistent_total_without_partial_output(
    preprocessable_dataset_dir: Path, tmp_path: Path
) -> None:
    marker_path = preprocessable_dataset_dir / "TARA-Oceans_18S-V4_dada2_table.tsv"
    invalid = marker_path.read_text(encoding="utf-8").replace("\t3\t2\t", "\t4\t2\t")
    marker_path.write_text(invalid, encoding="utf-8")
    processed_dir = tmp_path / "processed"

    with pytest.raises(PreprocessingError, match="total_mismatches"):
        preprocess(
            preprocessable_dataset_dir,
            processed_dir,
            enforce_expected_shape=False,
        )

    assert not (processed_dir / "manifest.json").exists()
    assert not list(processed_dir.glob(".staging-*"))


def test_store_rejects_unknown_sample(
    preprocessable_dataset_dir: Path, tmp_path: Path
) -> None:
    processed_dir = tmp_path / "processed"
    preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    store = ProcessedDataReader(processed_dir)

    with pytest.raises(ProcessedDataError, match="Unknown sample IDs"):
        store.scan_abundance(Marker.V9, ["TARA_UNKNOWN"])
