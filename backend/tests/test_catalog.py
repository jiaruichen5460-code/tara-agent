from pathlib import Path

import pytest

from tara_agent.data.catalog import DATASET_SPECS, DatasetCatalog, source_filename


@pytest.mark.parametrize(
    ("source_key", "filename"),
    [
        ("context_general", "context_general.tsv"),
        ("context_stat", "context_stat.tsv"),
        ("18s_v4", "TARA-Oceans_18S-V4_dada2_table.tsv"),
        ("18s_v9", "TARA-Oceans_18S-V9_dada2_table.tsv"),
    ],
)
def test_source_keys_map_to_original_filenames(source_key: str, filename: str) -> None:
    assert source_filename(source_key) == filename


def test_catalog_accepts_the_expected_dataset_contract(valid_dataset_dir: Path) -> None:
    inspection = DatasetCatalog(valid_dataset_dir).inspect()

    assert inspection.ready is True
    assert len(inspection.datasets) == 4
    assert [item.sample_column_count for item in inspection.datasets] == [0, 0, 2, 2]


def test_catalog_reports_a_missing_dataset(valid_dataset_dir: Path) -> None:
    missing_file = valid_dataset_dir / DATASET_SPECS[-1].filename
    missing_file.unlink()

    inspection = DatasetCatalog(valid_dataset_dir).inspect()
    missing = inspection.datasets[-1]

    assert inspection.ready is False
    assert missing.exists is False
    assert missing.ready is False


def test_catalog_reports_schema_errors(valid_dataset_dir: Path) -> None:
    general_file = valid_dataset_dir / DATASET_SPECS[0].filename
    general_file.write_text("sample_id_pangaea\tunexpected\nTARA_TEST_001\t1\n", encoding="utf-8")

    inspection = DatasetCatalog(valid_dataset_dir).inspect()
    general = inspection.datasets[0]

    assert general.ready is False
    assert "event_date" in general.missing_columns


@pytest.mark.integration
def test_local_source_dataset_headers_are_valid_and_unchanged() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source_dir = project_root / "Tara_4_Core_Datasets"
    if not source_dir.is_dir():
        pytest.skip("Local Tara datasets are not available")

    before = {
        spec.filename: (source_dir / spec.filename).stat().st_mtime_ns for spec in DATASET_SPECS
    }
    inspection = DatasetCatalog(source_dir).inspect()
    after = {
        spec.filename: (source_dir / spec.filename).stat().st_mtime_ns for spec in DATASET_SPECS
    }

    assert inspection.ready is True
    assert before == after
