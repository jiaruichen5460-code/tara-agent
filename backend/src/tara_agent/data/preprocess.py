"""四份 Tara MVP 数据集的确定性校验与预处理。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import polars as pl
import psutil

from tara_agent.data.catalog import AMPLICON_METADATA_COLUMNS, DATASET_SPECS, DatasetCatalog
from tara_agent.data.manifest import (
    ArtifactRecord,
    CoverageRecord,
    DataManifest,
    ProcessingMetrics,
    SourceFileRecord,
)

PIPELINE_VERSION = "2.1.0"
MANIFEST_FILENAME = "manifest.json"

GENERAL_SCHEMA: dict[str, pl.DataType] = {
    "sample_id_pangaea": pl.String,
    "sample_id_biosamples": pl.String,
    "sample_id_ena": pl.String,
    "sample_material": pl.String,
    "event_date": pl.String,
    "event_latitude": pl.Float64,
    "event_longitude": pl.Float64,
    "depth_nominal": pl.String,
    "marine_biome": pl.String,
    "ocean_region": pl.String,
    "biogeo_province": pl.String,
    "station": pl.String,
    "depth": pl.String,
    "size_fraction": pl.String,
    "lower_size_fraction": pl.Float64,
    "upper_size_fraction": pl.Float64,
    "depthplot": pl.String,
    "sizeplot": pl.String,
    "station_plot": pl.String,
    "biomeplot": pl.String,
    "polar": pl.String,
    "abs_lat": pl.Float64,
    "uniq": pl.String,
    "complete": pl.String,
    "coral_station": pl.String,
}

STAT_SCHEMA: dict[str, pl.DataType] = {
    "sample_id_pangaea": pl.String,
    "par": pl.Float64,
    "depth_bathy": pl.Int32,
    "lyapunov_exp": pl.Float64,
    "temperature": pl.Float64,
    "chla": pl.Float64,
    "backscattering": pl.Float64,
    "depth_chl_max": pl.Int32,
    "mixed_layer_depth_sigma": pl.Int32,
    "depth_max_brunt_väisälä": pl.Int32,
    "nitrite": pl.Float64,
    "phosphate": pl.Float64,
    "nitrate_nitrite": pl.Float64,
    "silicate": pl.Float64,
    "nstar": pl.Float64,
}

MARKER_METADATA_SCHEMA: dict[str, pl.DataType] = {
    "amplicon": pl.String,
    "taxonomy": pl.String,
    "confidence": pl.String,
    "total": pl.UInt64,
    "spread": pl.UInt32,
    "sequence": pl.String,
}

MARKER_FILES = {
    "v4": "TARA-Oceans_18S-V4_dada2_table.tsv",
    "v9": "TARA-Oceans_18S-V9_dada2_table.tsv",
}

EXPECTED_CONTEXT_SAMPLES = 1_434
EXPECTED_MARKER_SAMPLES = {"v4": 1_011, "v9": 1_069}
EXPECTED_MARKER_ROWS = {"v4": 152_155, "v9": 181_388}


class PreprocessingError(RuntimeError):
    """源数据违反确定性预处理约束时抛出。"""


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    """一次预处理请求的结果。"""

    status: str
    manifest_path: Path
    manifest: DataManifest


def preprocess(
    source_dir: Path,
    processed_dir: Path,
    *,
    force: bool = False,
    enforce_expected_shape: bool = True,
) -> PreprocessResult:
    """校验原始 TSV，并发布一份完整的处理后数据。"""

    started = perf_counter()
    source_dir = source_dir.resolve(strict=True)
    processed_dir = processed_dir.resolve(strict=False)
    _ensure_separate_directories(source_dir, processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    _remove_stale_staging_directories(processed_dir)

    manifest_path = processed_dir / MANIFEST_FILENAME
    existing = _load_manifest_if_valid(manifest_path)
    if not force and existing and _can_skip(existing, source_dir, processed_dir):
        return PreprocessResult("skipped", manifest_path, existing)

    inspection = DatasetCatalog(source_dir).inspect()
    if not inspection.ready:
        failures = [item.key for item in inspection.datasets if not item.ready]
        raise PreprocessingError(f"Source header validation failed: {', '.join(failures)}")

    sources = _snapshot_sources(source_dir)
    generation = _generation_name(sources)
    staging_dir = processed_dir / f".staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()

    try:
        context, context_report = _prepare_context(source_dir)
        if enforce_expected_shape and context.height != EXPECTED_CONTEXT_SAMPLES:
            raise PreprocessingError(
                f"Expected {EXPECTED_CONTEXT_SAMPLES} context samples, found {context.height}"
            )
        context_path = staging_dir / "context.parquet"
        context.write_parquet(
            context_path,
            compression="zstd",
            statistics=True,
            row_group_size=10_000,
        )

        context_ids = set(context.get_column("sample_id_pangaea").to_list())
        marker_reports: dict[str, dict[str, Any]] = {}
        marker_samples: dict[str, list[str]] = {}
        for marker, filename in MARKER_FILES.items():
            samples = _prepare_marker(source_dir / filename, staging_dir, marker)
            marker_samples[marker] = samples
            report = _validate_marker(staging_dir, marker, samples)
            marker_reports[marker] = report

            if enforce_expected_shape:
                _enforce_marker_shape(marker, report, len(samples))

        coverage = _validate_coverage(context_ids, marker_samples)
        validation = {
            "status": "passed",
            "pipeline_version": PIPELINE_VERSION,
            "context": context_report,
            "markers": marker_reports,
            "coverage": coverage.model_dump(mode="json"),
        }
        validation_path = staging_dir / "validation.json"
        _write_json(validation_path, validation)

        after = _snapshot_sources(source_dir)
        if sources != after:
            raise PreprocessingError("A source TSV changed while preprocessing was running")

        artifacts = _build_artifact_records(staging_dir, context, marker_samples)
        elapsed = perf_counter() - started
        output_bytes = sum(path.stat().st_size for path in staging_dir.iterdir() if path.is_file())
        memory_info = psutil.Process().memory_info()
        peak_memory = getattr(memory_info, "peak_wset", memory_info.rss)

        manifest = DataManifest(
            pipeline_version=PIPELINE_VERSION,
            generation=generation,
            created_at_utc=datetime.now(UTC).isoformat(),
            sources=sources,
            artifacts=artifacts,
            coverage=coverage,
            metrics=ProcessingMetrics(
                elapsed_seconds=round(elapsed, 6),
                peak_memory_bytes=peak_memory,
                source_bytes=sum(item.size_bytes for item in sources.values()),
                output_bytes=output_bytes,
            ),
            validation_report="validation.json",
        )

        final_dir = processed_dir / generation
        status = _publish_generation(staging_dir, final_dir, artifacts)
        if status == "verified" and existing and existing.generation == generation:
            return PreprocessResult(status, manifest_path, existing)
        _write_manifest_atomically(manifest_path, manifest)
        _remove_obsolete_generations(processed_dir, final_dir)
        return PreprocessResult(status, manifest_path, manifest)
    except Exception:
        _remove_directory(staging_dir, processed_dir)
        raise


def _ensure_separate_directories(source_dir: Path, processed_dir: Path) -> None:
    try:
        processed_dir.relative_to(source_dir)
    except ValueError:
        return
    raise PreprocessingError("Processed data directory must not be inside the source directory")


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return source.readline().rstrip("\r\n").split("\t")


def _scan_tsv(path: Path, schema: dict[str, pl.DataType]) -> pl.LazyFrame:
    header = _read_header(path)
    if header != list(schema):
        raise PreprocessingError(f"Unexpected column order or names in {path.name}")
    return pl.scan_csv(
        path,
        separator="\t",
        quote_char=None,
        schema=schema,
        null_values="",
        empty_string_is_null=True,
        encoding="utf8",
    )


def _prepare_context(source_dir: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    general = _scan_tsv(source_dir / "context_general.tsv", GENERAL_SCHEMA).collect()
    stat = _scan_tsv(source_dir / "context_stat.tsv", STAT_SCHEMA).collect()

    _require_unique_non_null_id(general, "context_general")
    _require_unique_non_null_id(stat, "context_stat")
    if set(general["sample_id_pangaea"]) != set(stat["sample_id_pangaea"]):
        raise PreprocessingError("context_general and context_stat sample IDs differ")

    parsed_dates = general.get_column("event_date").str.to_datetime(strict=False)
    if parsed_dates.null_count() != general.get_column("event_date").null_count():
        raise PreprocessingError("context_general contains an unparseable event_date")
    general = general.with_columns(parsed_dates.alias("event_date"))

    context = general.join(stat, on="sample_id_pangaea", how="inner", validate="1:1")
    coordinate_errors = context.filter(
        ~pl.col("event_latitude").is_between(-90, 90, closed="both")
        | ~pl.col("event_longitude").is_between(-180, 180, closed="both")
        | ((pl.col("abs_lat") - pl.col("event_latitude").abs()).abs() > 1e-9)
    ).height
    if coordinate_errors:
        raise PreprocessingError(f"Found {coordinate_errors} invalid coordinate rows")

    numeric_profiles = _numeric_profiles(context)
    non_finite = {
        name: profile["non_finite_count"]
        for name, profile in numeric_profiles.items()
        if profile["non_finite_count"]
    }
    if non_finite:
        raise PreprocessingError(f"Context contains non-finite numeric values: {non_finite}")

    report = {
        "row_count": context.height,
        "column_count": context.width,
        "sample_id_unique": True,
        "general_and_stat_ids_equal": True,
        "duplicate_rows": {
            "context_general": general.height - general.unique().height,
            "context_stat": stat.height - stat.unique().height,
        },
        "missing_values": _missing_values(context),
        "numeric_profiles": numeric_profiles,
        "categorical_values": {
            "depth": sorted(context["depth"].drop_nulls().unique().to_list()),
            "polar": sorted(context["polar"].drop_nulls().unique().to_list()),
        },
        "depth_nominal_type": "String (source includes numeric ranges)",
        "event_date_parse_errors": 0,
        "coordinate_errors": 0,
    }
    return context, report


def _require_unique_non_null_id(frame: pl.DataFrame, label: str) -> None:
    ids = frame.get_column("sample_id_pangaea")
    if ids.null_count():
        raise PreprocessingError(f"{label} contains missing sample IDs")
    if ids.n_unique() != frame.height:
        raise PreprocessingError(f"{label} contains duplicate sample IDs")
    invalid = ids.filter(~ids.str.starts_with("TARA_"))
    if invalid.len():
        raise PreprocessingError(f"{label} contains invalid sample IDs")


def _missing_values(frame: pl.DataFrame) -> dict[str, int]:
    counts = frame.null_count().row(0)
    return {
        column: count
        for column, count in zip(frame.columns, counts, strict=True)
        if count > 0
    }


def _numeric_profiles(frame: pl.DataFrame) -> dict[str, dict[str, int | float | None]]:
    profiles: dict[str, dict[str, int | float | None]] = {}
    for column, dtype in frame.schema.items():
        if not dtype.is_numeric():
            continue
        values = frame.get_column(column).drop_nulls()
        q1 = values.quantile(0.25, interpolation="linear")
        q3 = values.quantile(0.75, interpolation="linear")
        outliers = 0
        if q1 is not None and q3 is not None:
            distance = q3 - q1
            lower = q1 - 1.5 * distance
            upper = q3 + 1.5 * distance
            outliers = values.filter((values < lower) | (values > upper)).len()
        profiles[column] = {
            "min": values.min(),
            "max": values.max(),
            "null_count": frame.get_column(column).null_count(),
            "non_finite_count": int((~values.is_finite()).sum()),
            "iqr_outlier_count": outliers,
        }
    return profiles


def _prepare_marker(source_path: Path, staging_dir: Path, marker: str) -> list[str]:
    header = _read_header(source_path)
    metadata_columns = list(AMPLICON_METADATA_COLUMNS)
    if header[: len(metadata_columns)] != metadata_columns:
        raise PreprocessingError(f"Unexpected metadata columns in {source_path.name}")

    samples = header[len(metadata_columns) :]
    if not samples or len(samples) != len(set(samples)):
        raise PreprocessingError(f"Missing or duplicate sample columns in {source_path.name}")
    invalid = [sample for sample in samples if not sample.startswith("TARA_")]
    if invalid:
        raise PreprocessingError(f"Invalid sample IDs in {source_path.name}: {invalid[:3]}")

    schema = {**MARKER_METADATA_SCHEMA, **dict.fromkeys(samples, pl.UInt32)}
    source = _scan_tsv(source_path, schema)
    source.select(metadata_columns).sink_parquet(
        staging_dir / f"{marker}_asv_metadata.parquet",
        compression="zstd",
        statistics=True,
        row_group_size=10_000,
        engine="streaming",
    )
    source.select(["amplicon", *samples]).sink_parquet(
        staging_dir / f"{marker}_abundance.parquet",
        compression="zstd",
        statistics=True,
        row_group_size=10_000,
        engine="streaming",
    )
    return samples


def _validate_marker(
    staging_dir: Path, marker: str, samples: list[str]
) -> dict[str, Any]:
    metadata = pl.read_parquet(staging_dir / f"{marker}_asv_metadata.parquet")
    if metadata.height != metadata.get_column("amplicon").n_unique():
        raise PreprocessingError(f"{marker.upper()} contains duplicate amplicon IDs")

    taxonomy_parts = metadata.get_column("taxonomy").str.split(";").list.len()
    confidence_parts = metadata.get_column("confidence").str.split(";").list.len()
    level_mismatches = int((taxonomy_parts != confidence_parts).sum())
    empty_taxonomy_levels = metadata.select(
        pl.col("taxonomy")
        .str.split(";")
        .list.eval(pl.element().str.strip_chars().eq(""))
        .list.any()
        .sum()
    ).item()
    confidence_values = (
        metadata.get_column("confidence").str.split(";").explode(empty_as_null=True)
    )
    parsed_confidence = confidence_values.cast(pl.Float64, strict=False)
    invalid_confidence = parsed_confidence.null_count() + int(
        ((parsed_confidence < 0) | (parsed_confidence > 100)).sum()
    )
    invalid_amplicons = metadata.filter(
        ~pl.col("amplicon").str.contains(r"^[0-9a-f]{32}$")
    ).height
    invalid_sequences = metadata.filter(
        ~pl.col("sequence").str.contains(r"^[ACGTN]+$")
    ).height

    checks = _compute_abundance_checks(
        staging_dir / f"{marker}_abundance.parquet", metadata, samples
    )

    errors = {
        "metadata_missing_values": sum(_missing_values(metadata).values()),
        "taxonomy_confidence_level_mismatches": level_mismatches,
        "empty_taxonomy_levels": empty_taxonomy_levels,
        "invalid_confidence_values": invalid_confidence,
        "invalid_amplicon_ids": invalid_amplicons,
        "invalid_sequences": invalid_sequences,
        "total_mismatches": checks["total_mismatches"],
        "spread_mismatches": checks["spread_mismatches"],
        "rows_with_missing_counts": checks["rows_with_missing_counts"],
    }
    failed = {name: count for name, count in errors.items() if count}
    if failed:
        raise PreprocessingError(f"{marker.upper()} validation failed: {failed}")

    positive_cells = int(metadata.get_column("spread").sum())
    total_cells = metadata.height * len(samples)
    return {
        "row_count": checks["row_count"],
        "column_count": len(samples) + len(AMPLICON_METADATA_COLUMNS),
        "sample_column_count": len(samples),
        "amplicon_ids_unique": True,
        "metadata_missing_values": {},
        "taxonomy_level_counts": _value_counts(taxonomy_parts),
        "taxonomy_confidence_level_mismatches": 0,
        "confidence_range": [parsed_confidence.min(), parsed_confidence.max()],
        "total_range": [metadata["total"].min(), metadata["total"].max()],
        "spread_range": [metadata["spread"].min(), metadata["spread"].max()],
        "max_read_count": checks["max_read_count"],
        "positive_abundance_cells": positive_cells,
        "total_abundance_cells": total_cells,
        "nonzero_fraction": round(positive_cells / total_cells, 8),
        "count_type": "UInt32",
        "total_type": "UInt64",
        "missing_count_representation": "null (none found)",
        "total_and_spread_match_abundance": True,
    }


def _compute_abundance_checks(
    abundance_path: Path,
    metadata: pl.DataFrame,
    samples: list[str],
    *,
    columns_per_batch: int = 64,
) -> dict[str, int]:
    """分批选取列并重新计算各行总数，以限制内存峰值。"""

    expected_amplicons = metadata.get_column("amplicon")
    totals: pl.Series | None = None
    spreads: pl.Series | None = None
    missing: pl.Series | None = None
    maximums: pl.Series | None = None

    for start in range(0, len(samples), columns_per_batch):
        batch = samples[start : start + columns_per_batch]
        values = (
            pl.scan_parquet(abundance_path)
            .select(
                "amplicon",
                pl.sum_horizontal([pl.col(name).cast(pl.UInt64) for name in batch]).alias(
                    "total"
                ),
                pl.sum_horizontal(
                    [pl.col(name).gt(0).cast(pl.UInt32) for name in batch]
                ).alias("spread"),
                pl.any_horizontal([pl.col(name).is_null() for name in batch]).alias(
                    "missing"
                ),
                pl.max_horizontal(batch).alias("maximum"),
            )
            .collect(engine="streaming")
        )
        if not values.get_column("amplicon").equals(expected_amplicons):
            raise PreprocessingError("Abundance and metadata amplicon order differs")

        if totals is None:
            totals = values.get_column("total")
            spreads = values.get_column("spread")
            missing = values.get_column("missing")
            maximums = values.get_column("maximum")
            continue

        totals = totals + values.get_column("total")
        spreads = spreads + values.get_column("spread")
        missing = missing | values.get_column("missing")
        maximums = pl.DataFrame(
            {"previous": maximums, "current": values.get_column("maximum")}
        ).max_horizontal()

    if totals is None or spreads is None or missing is None or maximums is None:
        raise PreprocessingError("Abundance matrix has no sample columns")

    return {
        "row_count": metadata.height,
        "total_mismatches": int((totals != metadata.get_column("total")).sum()),
        "spread_mismatches": int((spreads != metadata.get_column("spread")).sum()),
        "rows_with_missing_counts": int(missing.sum()),
        "max_read_count": int(maximums.max()),
    }


def _value_counts(values: pl.Series) -> dict[str, int]:
    rows = values.value_counts().sort(values.name).iter_rows()
    return {str(value): count for value, count in rows}


def _enforce_marker_shape(marker: str, report: dict[str, Any], sample_count: int) -> None:
    expected_samples = EXPECTED_MARKER_SAMPLES[marker]
    expected_rows = EXPECTED_MARKER_ROWS[marker]
    if sample_count != expected_samples:
        raise PreprocessingError(
            f"Expected {expected_samples} {marker.upper()} samples, found {sample_count}"
        )
    if report["row_count"] != expected_rows:
        raise PreprocessingError(
            f"Expected {expected_rows} {marker.upper()} rows, found {report['row_count']}"
        )


def _validate_coverage(
    context_ids: set[str], marker_samples: dict[str, list[str]]
) -> CoverageRecord:
    v4 = set(marker_samples["v4"])
    v9 = set(marker_samples["v9"])
    v4_only = sorted(v4 - v9)
    v9_only = sorted(v9 - v4)
    context_without_marker = sorted(context_ids - (v4 | v9))
    missing = sorted((v4 | v9) - context_ids)
    if missing:
        raise PreprocessingError(f"Marker samples missing context: {missing[:5]}")
    return CoverageRecord(
        context_samples=len(context_ids),
        v4_samples=len(v4),
        v9_samples=len(v9),
        shared_marker_samples=len(v4 & v9),
        v4_only_samples=len(v4_only),
        v9_only_samples=len(v9_only),
        context_without_marker_samples=len(context_without_marker),
        v4_only_sample_ids=v4_only,
        v9_only_sample_ids=v9_only,
        context_without_marker_sample_ids=context_without_marker,
        marker_samples_missing_context=missing,
    )


def _snapshot_sources(source_dir: Path) -> dict[str, SourceFileRecord]:
    return {
        spec.key: _source_record(source_dir / spec.filename)
        for spec in DATASET_SPECS
    }


def _source_record(path: Path) -> SourceFileRecord:
    digest = hashlib.sha256()
    newline_count = 0
    last_byte = b""
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    stat = path.stat()
    line_count = newline_count + int(bool(last_byte) and last_byte != b"\n")
    row_count = max(0, line_count - 1)
    return SourceFileRecord(
        filename=path.name,
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sha256=digest.hexdigest(),
        row_count=row_count,
        column_count=len(_read_header(path)),
    )


def _generation_name(sources: dict[str, SourceFileRecord]) -> str:
    payload = {
        "pipeline_version": PIPELINE_VERSION,
        "sources": {key: value.sha256 for key, value in sources.items()},
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return f"generation-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _build_artifact_records(
    staging_dir: Path,
    context: pl.DataFrame,
    marker_samples: dict[str, list[str]],
) -> dict[str, ArtifactRecord]:
    artifacts = {
        "context": _artifact_record(
            staging_dir / "context.parquet",
            context.height,
            context.width,
            {name: str(dtype) for name, dtype in context.schema.items()},
        )
    }
    for marker, samples in marker_samples.items():
        metadata_path = staging_dir / f"{marker}_asv_metadata.parquet"
        abundance_path = staging_dir / f"{marker}_abundance.parquet"
        metadata_schema = pl.read_parquet_schema(metadata_path)
        metadata_rows = pl.scan_parquet(metadata_path).select(pl.len()).collect().item()
        artifacts[f"{marker}_metadata"] = _artifact_record(
            metadata_path,
            metadata_rows,
            len(metadata_schema),
            {name: str(dtype) for name, dtype in metadata_schema.items()},
        )
        artifacts[f"{marker}_abundance"] = _artifact_record(
            abundance_path,
            metadata_rows,
            len(samples) + 1,
            {"amplicon": "String"},
            repeated_column_type="UInt32",
            repeated_columns=samples,
        )
    return artifacts


def _artifact_record(
    path: Path,
    row_count: int,
    column_count: int,
    fixed_schema: dict[str, str],
    *,
    repeated_column_type: str | None = None,
    repeated_columns: list[str] | None = None,
) -> ArtifactRecord:
    return ArtifactRecord(
        relative_path=path.name,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
        row_count=row_count,
        column_count=column_count,
        fixed_schema=fixed_schema,
        repeated_column_type=repeated_column_type,
        repeated_columns=repeated_columns or [],
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _can_skip(manifest: DataManifest, source_dir: Path, processed_dir: Path) -> bool:
    if manifest.pipeline_version != PIPELINE_VERSION:
        return False
    generation_dir = processed_dir / manifest.generation
    if not generation_dir.is_dir():
        return False
    for record in manifest.sources.values():
        path = source_dir / record.filename
        if not path.is_file():
            return False
        stat = path.stat()
        if stat.st_size != record.size_bytes or stat.st_mtime_ns != record.modified_ns:
            return False
    return all(
        (generation_dir / artifact.relative_path).is_file()
        and (generation_dir / artifact.relative_path).stat().st_size == artifact.size_bytes
        for artifact in manifest.artifacts.values()
    )


def _load_manifest_if_valid(path: Path) -> DataManifest | None:
    if not path.is_file():
        return None
    try:
        return DataManifest.load(path)
    except (OSError, ValueError):
        return None


def _publish_generation(
    staging_dir: Path,
    final_dir: Path,
    artifacts: dict[str, ArtifactRecord],
) -> str:
    if not final_dir.exists():
        staging_dir.rename(final_dir)
        return "processed"

    for artifact in artifacts.values():
        existing_path = final_dir / artifact.relative_path
        staged_path = staging_dir / artifact.relative_path
        if not existing_path.is_file() or _sha256(existing_path) != _sha256(staged_path):
            raise PreprocessingError(
                f"Existing generation differs from reproducible output: {artifact.relative_path}"
            )
    _remove_directory(staging_dir, staging_dir.parent)
    return "verified"


def _write_manifest_atomically(path: Path, manifest: DataManifest) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        manifest.write(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _remove_stale_staging_directories(processed_dir: Path) -> None:
    for path in processed_dir.glob(".staging-*"):
        if path.is_dir():
            _remove_directory(path, processed_dir)


def _remove_obsolete_generations(processed_dir: Path, current: Path) -> None:
    for path in processed_dir.glob("generation-*"):
        if path.is_dir() and path != current:
            _remove_directory(path, processed_dir)


def _remove_directory(path: Path, expected_parent: Path) -> None:
    resolved = path.resolve(strict=False)
    parent = expected_parent.resolve(strict=False)
    if resolved.parent != parent or not resolved.name:
        raise PreprocessingError(f"Refusing to remove unsafe path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
