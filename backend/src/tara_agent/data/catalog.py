"""对四份 MVP 原始数据集进行轻量级只读校验。"""

import csv
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DatasetKind(StrEnum):
    CONTEXT = "context"
    AMPLICON = "amplicon"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    key: str
    filename: str
    kind: DatasetKind
    required_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetInspection:
    key: str
    filename: str
    exists: bool
    size_bytes: int = 0
    column_count: int = 0
    sample_column_count: int = 0
    missing_columns: tuple[str, ...] = ()
    duplicate_columns: tuple[str, ...] = ()
    invalid_sample_columns: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.exists
            and self.size_bytes > 0
            and self.column_count > 0
            and not self.missing_columns
            and not self.duplicate_columns
            and not self.invalid_sample_columns
            and self.error is None
        )


@dataclass(frozen=True, slots=True)
class CatalogInspection:
    datasets: tuple[DatasetInspection, ...]

    @property
    def ready(self) -> bool:
        return len(self.datasets) == len(DATASET_SPECS) and all(
            dataset.ready for dataset in self.datasets
        )


GENERAL_COLUMNS = (
    "sample_id_pangaea",
    "event_date",
    "event_latitude",
    "event_longitude",
    "depth_nominal",
    "ocean_region",
    "station",
    "depth",
    "size_fraction",
    "lower_size_fraction",
    "upper_size_fraction",
    "polar",
)

STAT_COLUMNS = (
    "sample_id_pangaea",
    "par",
    "temperature",
    "chla",
    "nitrite",
    "phosphate",
    "nitrate_nitrite",
    "silicate",
)

AMPLICON_METADATA_COLUMNS = (
    "amplicon",
    "taxonomy",
    "confidence",
    "total",
    "spread",
    "sequence",
)

DATASET_SPECS = (
    DatasetSpec("context_general", "context_general.tsv", DatasetKind.CONTEXT, GENERAL_COLUMNS),
    DatasetSpec("context_stat", "context_stat.tsv", DatasetKind.CONTEXT, STAT_COLUMNS),
    DatasetSpec(
        "18s_v4",
        "TARA-Oceans_18S-V4_dada2_table.tsv",
        DatasetKind.AMPLICON,
        AMPLICON_METADATA_COLUMNS,
    ),
    DatasetSpec(
        "18s_v9",
        "TARA-Oceans_18S-V9_dada2_table.tsv",
        DatasetKind.AMPLICON,
        AMPLICON_METADATA_COLUMNS,
    ),
)

SOURCE_FILENAMES = {spec.key: spec.filename for spec in DATASET_SPECS}


def source_filename(source_key: str) -> str:
    return SOURCE_FILENAMES.get(source_key, source_key)


class DatasetCatalog:
    """检查源数据表头，无需将大型丰度矩阵载入内存。"""

    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir.resolve(strict=False)

    def inspect(self) -> CatalogInspection:
        return CatalogInspection(tuple(self._inspect_one(spec) for spec in DATASET_SPECS))

    def _inspect_one(self, spec: DatasetSpec) -> DatasetInspection:
        path = self.source_dir / spec.filename
        if not path.is_file():
            return DatasetInspection(key=spec.key, filename=spec.filename, exists=False)

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                header = next(csv.reader(source, delimiter="\t"), [])
        except (OSError, UnicodeError, csv.Error) as exc:
            return DatasetInspection(
                key=spec.key,
                filename=spec.filename,
                exists=True,
                size_bytes=path.stat().st_size,
                error=f"{type(exc).__name__}: {exc}",
            )

        duplicates = tuple(sorted({column for column in header if header.count(column) > 1}))
        missing = tuple(column for column in spec.required_columns if column not in header)
        sample_columns: list[str] = []
        invalid_sample_columns: tuple[str, ...] = ()

        if spec.kind is DatasetKind.AMPLICON:
            metadata_count = len(AMPLICON_METADATA_COLUMNS)
            sample_columns = header[metadata_count:]
            invalid_sample_columns = tuple(
                column for column in sample_columns if not column.startswith("TARA_")
            )
            if not sample_columns:
                invalid_sample_columns = ("<no sample columns>",)

        return DatasetInspection(
            key=spec.key,
            filename=spec.filename,
            exists=True,
            size_bytes=path.stat().st_size,
            column_count=len(header),
            sample_column_count=len(sample_columns),
            missing_columns=missing,
            duplicate_columns=duplicates,
            invalid_sample_columns=invalid_sample_columns,
        )
