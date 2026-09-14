from collections.abc import Iterator
from pathlib import Path

import pytest

from tara_agent.data.catalog import DATASET_SPECS, DatasetKind
from tara_agent.data.preprocess import GENERAL_SCHEMA, MARKER_METADATA_SCHEMA, STAT_SCHEMA


@pytest.fixture
def valid_dataset_dir(tmp_path: Path) -> Iterator[Path]:
    dataset_dir = tmp_path / "source"
    dataset_dir.mkdir()

    for spec in DATASET_SPECS:
        columns = list(spec.required_columns)
        if spec.kind is DatasetKind.AMPLICON:
            columns.extend(["TARA_TEST_001", "TARA_TEST_002"])
        values = ["1"] * len(columns)
        (dataset_dir / spec.filename).write_text(
            "\t".join(columns) + "\n" + "\t".join(values) + "\n",
            encoding="utf-8",
        )

    yield dataset_dir


@pytest.fixture
def preprocessable_dataset_dir(tmp_path: Path) -> Path:
    """Create a tiny but semantically valid four-file Tara source set."""

    dataset_dir = tmp_path / "source"
    dataset_dir.mkdir()
    sample_ids = ["TARA_TEST_001", "TARA_TEST_002"]

    general_rows = []
    for index, sample_id in enumerate(sample_ids, start=1):
        general_rows.append(
            {
                "sample_id_pangaea": sample_id,
                "sample_id_biosamples": f"BIOSAMPLE_{index}",
                "sample_id_ena": f"ENA_{index}",
                "sample_material": "water",
                "event_date": f"2010-01-0{index}T12:00:00",
                "event_latitude": str(10.0 * index),
                "event_longitude": str(-20.0 * index),
                "depth_nominal": "0-100" if index == 1 else "5",
                "marine_biome": "Trades Biome",
                "ocean_region": "Test Ocean",
                "biogeo_province": "Test Province",
                "station": f"ST{index}",
                "depth": "SRF",
                "size_fraction": "0.8-5",
                "lower_size_fraction": "0.8",
                "upper_size_fraction": "5",
                "depthplot": "SRF",
                "sizeplot": "pico",
                "station_plot": f"ST{index}",
                "biomeplot": "Trades",
                "polar": "Non polar",
                "abs_lat": str(10.0 * index),
                "uniq": "yes",
                "complete": "yes",
                "coral_station": "no",
            }
        )
    _write_rows(dataset_dir / "context_general.tsv", list(GENERAL_SCHEMA), general_rows)

    stat_rows = []
    for index, sample_id in enumerate(sample_ids, start=1):
        stat_rows.append(
            {
                "sample_id_pangaea": sample_id,
                "par": str(10 + index),
                "depth_bathy": str(-100 * index),
                "lyapunov_exp": "0.1",
                "temperature": str(20 + index),
                "chla": "0.2",
                "backscattering": "0.01",
                "depth_chl_max": "50",
                "mixed_layer_depth_sigma": "25",
                "depth_max_brunt_väisälä": "40",
                "nitrite": "0.1",
                "phosphate": "0.2",
                "nitrate_nitrite": "0.3",
                "silicate": "0.4",
                "nstar": "-1.0",
            }
        )
    _write_rows(dataset_dir / "context_stat.tsv", list(STAT_SCHEMA), stat_rows)

    marker_columns = [*MARKER_METADATA_SCHEMA, *sample_ids]
    marker_rows = [
        {
            "amplicon": "0123456789abcdef0123456789abcdef",
            "taxonomy": "Root;Eukaryota;Dinoflagellata",
            "confidence": "100;99;98.5",
            "total": "3",
            "spread": "2",
            "sequence": "ACGTN",
            "TARA_TEST_001": "1",
            "TARA_TEST_002": "2",
        }
    ]
    for spec in DATASET_SPECS:
        if spec.kind is DatasetKind.AMPLICON:
            _write_rows(dataset_dir / spec.filename, marker_columns, marker_rows)
    return dataset_dir


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    lines = ["\t".join(columns)]
    lines.extend("\t".join(row[column] for column in columns) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
