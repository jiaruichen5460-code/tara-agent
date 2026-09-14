from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tara_agent.data.catalog import DATASET_SPECS
from tara_agent.data.preprocess import preprocess
from tara_agent.data.store import ProcessedDataStore
from tara_agent.domain.contracts import Marker


def _fingerprints(source_dir: Path) -> dict[str, tuple[int, int, str]]:
    fingerprints = {}
    for spec in DATASET_SPECS:
        path = source_dir / spec.filename
        stat = path.stat()
        fingerprints[spec.key] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return fingerprints


@pytest.mark.integration
def test_full_dataset_preprocessing_acceptance(tmp_path: Path) -> None:
    source_dir = Path(__file__).resolve().parents[2] / "Tara_4_Core_Datasets"
    if not source_dir.is_dir():
        pytest.skip("Local Tara datasets are not available")
    processed_dir = tmp_path / "processed"
    before = _fingerprints(source_dir)

    first = preprocess(source_dir, processed_dir)
    skipped = preprocess(source_dir, processed_dir)
    forced = preprocess(source_dir, processed_dir, force=True)

    assert first.status == "processed"
    assert skipped.status == "skipped"
    assert forced.status == "verified"
    assert first.manifest.coverage.context_samples == 1_434
    assert first.manifest.coverage.v4_samples == 1_011
    assert first.manifest.coverage.v9_samples == 1_069
    assert first.manifest.coverage.shared_marker_samples == 812
    assert first.manifest.coverage.v4_only_samples == 199
    assert first.manifest.coverage.v9_only_samples == 257
    assert first.manifest.coverage.context_without_marker_samples == 166
    assert first.manifest.coverage.marker_samples_missing_context == []
    assert first.manifest.metrics.elapsed_seconds > 0
    assert first.manifest.metrics.peak_memory_bytes > 0
    assert before == _fingerprints(source_dir)
    assert {
        key: artifact.sha256 for key, artifact in first.manifest.artifacts.items()
    } == {key: artifact.sha256 for key, artifact in forced.manifest.artifacts.items()}
    assert not list(processed_dir.glob(".staging-*"))

    store = ProcessedDataStore(processed_dir)
    assert store.load_sample_context().height == 1_434
    assert len(store.marker_sample_ids(Marker.V4)) == 1_011
    assert len(store.marker_sample_ids(Marker.V9)) == 1_069
