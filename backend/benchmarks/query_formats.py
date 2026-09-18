"""在不影响预处理流程的前提下比较具有代表性的 Tara 查询。"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

import duckdb
import polars as pl

from tara_agent.config import Settings
from tara_agent.data.catalog import AMPLICON_METADATA_COLUMNS
from tara_agent.data.preprocess import MARKER_FILES, MARKER_METADATA_SCHEMA
from tara_agent.data.reader import ProcessedDataReader
from tara_agent.domain.contracts import Marker

BENCHMARK_RUNS = 3
SAMPLE_COUNT = 8
TAXONOMY_PATTERN = "Dinoflagellata"


class BenchmarkError(RuntimeError):
    """基准测试输入或查询引擎结果不一致时抛出。"""


def benchmark_query_formats(source_dir: Path, processed_dir: Path) -> dict[str, Any]:
    """分别计时原始 TSV 和处理后 Parquet 上的一次等价查询。"""

    store = ProcessedDataReader(processed_dir)
    selected = store.marker_sample_ids(Marker.V4)[:SAMPLE_COUNT]
    source_path = source_dir / MARKER_FILES["v4"]
    source_schema = _source_schema(source_path)
    metadata_path = store.generation_dir / store.manifest.artifacts["v4_metadata"].relative_path
    abundance_path = store.generation_dir / store.manifest.artifacts["v4_abundance"].relative_path

    def raw_query() -> tuple[int, ...]:
        result = (
            pl.scan_csv(
                source_path,
                separator="\t",
                quote_char=None,
                schema=source_schema,
                null_values="",
                empty_string_is_null=True,
                encoding="utf8",
            )
            .select("taxonomy", *selected)
            .filter(pl.col("taxonomy").str.contains(TAXONOMY_PATTERN, literal=True))
            .select(pl.col(selected).sum())
            .collect(engine="streaming")
        )
        return tuple(result.row(0))

    def polars_query() -> tuple[int, ...]:
        matching = pl.scan_parquet(metadata_path).filter(
            pl.col("taxonomy").str.contains(TAXONOMY_PATTERN, literal=True)
        )
        result = (
            pl.scan_parquet(abundance_path)
            .select("amplicon", *selected)
            .join(matching.select("amplicon"), on="amplicon", how="inner")
            .select(pl.col(selected).sum())
            .collect(engine="streaming")
        )
        return tuple(result.row(0))

    connection = duckdb.connect(":memory:")
    connection.from_parquet(str(metadata_path)).create_view("asv_metadata")
    connection.from_parquet(str(abundance_path)).create_view("abundance")
    sums = ", ".join(f'SUM(a."{_quote_identifier(sample)}")' for sample in selected)
    sql = (
        f"SELECT {sums} FROM abundance AS a "
        "JOIN asv_metadata AS m USING (amplicon) WHERE contains(m.taxonomy, ?)"
    )

    def duckdb_query() -> tuple[int, ...]:
        row = connection.execute(sql, [TAXONOMY_PATTERN]).fetchone()
        if row is None:
            raise BenchmarkError("DuckDB returned no benchmark result")
        return tuple(row)

    try:
        raw_times, raw_result = _time_query(raw_query)
        polars_times, polars_result = _time_query(polars_query)
        duckdb_times, duckdb_result = _time_query(duckdb_query)
    finally:
        connection.close()

    if raw_result != polars_result or raw_result != duckdb_result:
        raise BenchmarkError("Benchmark engines returned different abundance results")

    return {
        "status": "passed",
        "query": {
            "marker": "v4",
            "taxonomy_contains": TAXONOMY_PATTERN,
            "selected_sample_count": len(selected),
            "result_verified_equal": True,
        },
        "timings_ms": {
            "raw_tsv_polars": raw_times,
            "processed_parquet_polars": polars_times,
            "processed_parquet_duckdb": duckdb_times,
        },
        "median_ms": {
            "raw_tsv_polars": statistics.median(raw_times),
            "processed_parquet_polars": statistics.median(polars_times),
            "processed_parquet_duckdb": statistics.median(duckdb_times),
        },
    }


def _source_schema(path: Path) -> dict[str, pl.DataType]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        header = source.readline().rstrip("\r\n").split("\t")
    metadata_columns = list(AMPLICON_METADATA_COLUMNS)
    if header[: len(metadata_columns)] != metadata_columns:
        raise BenchmarkError(f"Unexpected metadata columns in {path.name}")
    samples = header[len(metadata_columns) :]
    return {**MARKER_METADATA_SCHEMA, **dict.fromkeys(samples, pl.UInt32)}


def _quote_identifier(value: str) -> str:
    return value.replace('"', '""')


def _time_query(query: Callable[[], tuple[int, ...]]) -> tuple[list[float], tuple[int, ...]]:
    timings: list[float] = []
    result: tuple[int, ...] = ()
    for _ in range(BENCHMARK_RUNS):
        started = perf_counter()
        result = query()
        timings.append(round((perf_counter() - started) * 1_000, 3))
    return timings, result


def main() -> None:
    settings = Settings()
    report = benchmark_query_formats(settings.dataset_dir, settings.processed_data_dir)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
