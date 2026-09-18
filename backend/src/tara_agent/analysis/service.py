"""Tara MVP 查询能力的清晰、确定性实现。"""

from __future__ import annotations

from typing import Any

import polars as pl

from tara_agent.analysis.models import (
    FindSamplesQuery,
    FindSamplesResult,
    FindTaxaQuery,
    FindTaxaResult,
    Page,
    SampleContext,
    SampleInfoResult,
    SampleOccurrence,
    SampleSummary,
    TaxonRecord,
)
from tara_agent.analysis.taxonomy import taxonomy_predicate
from tara_agent.data.reader import ProcessedDataReader
from tara_agent.domain.contracts import DataProvenance, ResultMetadata, ResultWarning

SAMPLE_SUMMARY_COLUMNS = (
    "sample_id_pangaea",
    "event_date",
    "event_latitude",
    "event_longitude",
    "ocean_region",
    "station",
    "depth",
    "size_fraction",
    "polar",
    "temperature",
)

ABUNDANCE_COLUMNS_PER_BATCH = 64


class AnalysisNotFoundError(LookupError):
    """请求的 Tara 数据实体不存在时抛出。"""


class TaraQueryService:
    """查询已校验的数据，不依赖 API、MCP 或 Agent 传输层。"""

    def __init__(self, reader: ProcessedDataReader) -> None:
        self.reader = reader

    def find_samples(self, query: FindSamplesQuery) -> FindSamplesResult:
        context = self.reader.load_sample_context()
        filtered = self._filter_samples(context, query).sort("sample_id_pangaea")
        total = filtered.height
        page = filtered.slice(query.offset, query.limit)
        items = [
            SampleSummary.model_validate(row)
            for row in page.select(SAMPLE_SUMMARY_COLUMNS).to_dicts()
        ]

        warnings = self._sample_filter_warnings(context, query)
        return FindSamplesResult(
            items=items,
            page=Page(offset=query.offset, limit=query.limit, total=total),
            metadata=ResultMetadata(
                provenance=DataProvenance(
                    source_datasets=["context_general", "context_stat"],
                    sample_count=total,
                    excluded_sample_count=context.height - total,
                    filters=self._meaningful_filters(query),
                ),
                warnings=warnings,
            ),
        )

    def get_sample_info(self, sample_id: str) -> SampleInfoResult:
        normalized = sample_id.strip()
        if not normalized:
            raise ValueError("sample_id must not be blank")

        frame = (
            self.reader.scan_context()
            .filter(pl.col("sample_id_pangaea") == normalized)
            .collect()
        )
        if frame.is_empty():
            raise AnalysisNotFoundError(f"Unknown sample ID: {normalized}")

        sample = SampleContext.model_validate(frame.row(0, named=True))
        return SampleInfoResult(
            sample=sample,
            metadata=ResultMetadata(
                provenance=DataProvenance(
                    source_datasets=["context_general", "context_stat"],
                    sample_count=1,
                    filters={"sample_id": normalized},
                )
            ),
        )

    def find_taxa(self, query: FindTaxaQuery) -> FindTaxaResult:
        predicate = taxonomy_predicate(query.taxon, query.match_mode)
        matching = self.reader.scan_asv_metadata(query.marker).filter(predicate)
        matching_frame = matching.collect(engine="streaming")
        matching_frame = matching_frame.sort(
            ["total", "amplicon"], descending=[True, False]
        )

        asv_total = matching_frame.height
        asv_page = matching_frame.slice(query.asv_offset, query.asv_limit)
        asvs = [TaxonRecord.model_validate(row) for row in asv_page.to_dicts()]

        occurrences = self._taxon_occurrences(query, matching_frame)
        sample_total = occurrences.height
        occurrence_page = occurrences.slice(query.sample_offset, query.sample_limit)
        sample_occurrences = [
            SampleOccurrence.model_validate(row) for row in occurrence_page.to_dicts()
        ]
        marker_sample_count = len(self.reader.marker_sample_ids(query.marker))

        return FindTaxaResult(
            marker=query.marker,
            taxon=query.taxon,
            match_mode=query.match_mode,
            asvs=asvs,
            asv_page=Page(
                offset=query.asv_offset,
                limit=query.asv_limit,
                total=asv_total,
            ),
            sample_occurrences=sample_occurrences,
            sample_page=Page(
                offset=query.sample_offset,
                limit=query.sample_limit,
                total=sample_total,
            ),
            metadata=ResultMetadata(
                provenance=DataProvenance(
                    source_datasets=[f"18s_{query.marker.value}"],
                    marker=query.marker,
                    sample_count=sample_total,
                    excluded_sample_count=marker_sample_count - sample_total,
                    filters={
                        "taxon": query.taxon,
                        "match_mode": query.match_mode.value,
                    },
                ),
                warnings=[
                    ResultWarning(
                        code="read_count_is_not_cell_abundance",
                        message=(
                            "测序读数是测序观测信号，不能直接解释为细胞丰度。"
                        ),
                    )
                ],
            ),
        )

    @staticmethod
    def _filter_samples(context: pl.DataFrame, query: FindSamplesQuery) -> pl.DataFrame:
        filtered = TaraQueryService._filter_samples_by_context(context, query)
        if query.temperature_min is not None:
            filtered = filtered.filter(pl.col("temperature") >= query.temperature_min)
        if query.temperature_max is not None:
            filtered = filtered.filter(pl.col("temperature") <= query.temperature_max)
        return filtered

    @staticmethod
    def _filter_samples_by_context(
        context: pl.DataFrame, query: FindSamplesQuery
    ) -> pl.DataFrame:
        """应用不依赖温度值的筛选条件。"""

        filtered = context
        if query.ocean_region_contains is not None:
            region = query.ocean_region_contains.lower()
            filtered = filtered.filter(
                pl.col("ocean_region").str.to_lowercase().str.contains(region, literal=True)
            )
        if query.polar is not None:
            label = "Polar" if query.polar else "Non polar"
            filtered = filtered.filter(pl.col("polar") == label)
        if query.depths:
            depth_values = [depth.value for depth in query.depths]
            filtered = filtered.filter(pl.col("depth").is_in(depth_values))
        if query.size_fractions:
            filtered = filtered.filter(pl.col("size_fraction").is_in(query.size_fractions))
        return filtered

    @staticmethod
    def _sample_filter_warnings(
        context: pl.DataFrame, query: FindSamplesQuery
    ) -> list[ResultWarning]:
        if query.temperature_min is None and query.temperature_max is None:
            return []
        candidates = TaraQueryService._filter_samples_by_context(context, query)
        missing = candidates.get_column("temperature").null_count()
        if missing == 0:
            return []
        return [
            ResultWarning(
                code="missing_filter_values_excluded",
                message=(
                    "应用其他样本筛选条件后，温度值缺失的样本未参与温度筛选。"
                ),
                details={
                    "field": "temperature",
                    "sample_count": missing,
                    "candidate_sample_count": candidates.height,
                },
            )
        ]

    @staticmethod
    def _meaningful_filters(query: FindSamplesQuery) -> dict[str, Any]:
        values = query.model_dump(
            mode="json",
            exclude={"offset", "limit"},
            exclude_none=True,
        )
        return {key: value for key, value in values.items() if value != []}

    def _taxon_occurrences(
        self, query: FindTaxaQuery, matching_metadata: pl.DataFrame
    ) -> pl.DataFrame:
        if matching_metadata.is_empty():
            return pl.DataFrame(
                schema={"sample_id": pl.String, "read_count": pl.UInt64}
            )

        matching_ids = matching_metadata.select("amplicon").lazy()
        samples = self.reader.marker_sample_ids(query.marker)
        occurrence_rows: list[dict[str, int | str]] = []

        for start in range(0, len(samples), ABUNDANCE_COLUMNS_PER_BATCH):
            batch = samples[start : start + ABUNDANCE_COLUMNS_PER_BATCH]
            totals = (
                self.reader.scan_abundance(query.marker, batch)
                .join(matching_ids, on="amplicon", how="inner")
                .select([pl.col(sample).cast(pl.UInt64).sum() for sample in batch])
                .collect(engine="streaming")
                .row(0, named=True)
            )
            occurrence_rows.extend(
                {"sample_id": sample, "read_count": total}
                for sample, total in totals.items()
                if total is not None and total > 0
            )

        return pl.DataFrame(
            occurrence_rows,
            schema={"sample_id": pl.String, "read_count": pl.UInt64},
        ).sort(["read_count", "sample_id"], descending=[True, False])
