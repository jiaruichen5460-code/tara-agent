"""确定性地访问已校验、处理后的 Tara 数据。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from tara_agent.data.manifest import ArtifactRecord, DataManifest
from tara_agent.domain.contracts import Marker


class ProcessedDataError(RuntimeError):
    """处理后数据缺失、无效或查询方式不正确时抛出。"""


class ProcessedDataReader:
    """提供具有明确类型的 Parquet 扫描能力，不访问原始 TSV。"""

    def __init__(self, processed_dir: Path) -> None:
        self.processed_dir = processed_dir.resolve(strict=False)
        manifest_path = self.processed_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ProcessedDataError(f"Processed data manifest not found: {manifest_path}")
        try:
            self.manifest = DataManifest.load(manifest_path)
        except (OSError, ValueError) as exc:
            raise ProcessedDataError(f"Invalid processed data manifest: {exc}") from exc

        self.generation_dir = self._safe_child(self.processed_dir, self.manifest.generation)
        if not self.generation_dir.is_dir():
            raise ProcessedDataError(
                f"Processed data generation not found: {self.manifest.generation}"
            )
        for artifact in self.manifest.artifacts.values():
            path = self._artifact_path(artifact)
            if not path.is_file() or path.stat().st_size != artifact.size_bytes:
                raise ProcessedDataError(
                    f"Processed artifact is missing or incomplete: {path.name}"
                )

    def scan_context(self) -> pl.LazyFrame:
        """返回全部样本背景信息，明确保留 Parquet 中的数据类型和空值。"""

        return pl.scan_parquet(self._artifact_path(self.manifest.artifacts["context"]))

    def load_sample_context(self, sample_ids: list[str] | None = None) -> pl.DataFrame:
        """加载全部背景数据行，或调用方指定的样本 ID 对应行。"""

        query = self.scan_context()
        if sample_ids is not None:
            self._validate_requested_samples(sample_ids, set(self.context_sample_ids()))
            query = query.filter(pl.col("sample_id_pangaea").is_in(sample_ids))
        return query.collect()

    def context_sample_ids(self) -> list[str]:
        """按处理后数据的稳定顺序返回背景样本 ID。"""

        return (
            self.scan_context()
            .select("sample_id_pangaea")
            .collect()
            .get_column("sample_id_pangaea")
            .to_list()
        )

    def scan_asv_metadata(self, marker: Marker) -> pl.LazyFrame:
        """返回指定标记的 ASV 分类信息和元数据。"""

        artifact = self.manifest.artifacts[f"{marker.value}_metadata"]
        return pl.scan_parquet(self._artifact_path(artifact))

    def marker_sample_ids(self, marker: Marker) -> list[str]:
        """返回指定标记可用的样本列。"""

        return list(self.manifest.artifacts[f"{marker.value}_abundance"].repeated_columns)

    def scan_abundance(
        self, marker: Marker, sample_ids: list[str] | None = None
    ) -> pl.LazyFrame:
        """返回指定标记的宽格式读数矩阵，可选择仅保留指定样本。"""

        artifact = self.manifest.artifacts[f"{marker.value}_abundance"]
        available = set(artifact.repeated_columns)
        selected = artifact.repeated_columns if sample_ids is None else sample_ids
        self._validate_requested_samples(selected, available)
        return pl.scan_parquet(self._artifact_path(artifact)).select("amplicon", *selected)

    def load_marker_data(
        self,
        marker: Marker,
        *,
        sample_ids: list[str] | None = None,
        taxonomy_contains: str | None = None,
    ) -> pl.DataFrame:
        """加载已关联的 ASV 元数据及选取的读数列，供确定性分析使用。"""

        metadata = self.scan_asv_metadata(marker)
        if taxonomy_contains is not None:
            metadata = metadata.filter(
                pl.col("taxonomy").str.contains(taxonomy_contains, literal=True)
            )
        return metadata.join(
            self.scan_abundance(marker, sample_ids),
            on="amplicon",
            how="inner",
            validate="1:1",
        ).collect(engine="streaming")

    def _artifact_path(self, artifact: ArtifactRecord) -> Path:
        return self._safe_child(self.generation_dir, artifact.relative_path)

    @staticmethod
    def _safe_child(parent: Path, child: str) -> Path:
        path = (parent / child).resolve(strict=False)
        try:
            path.relative_to(parent)
        except ValueError as exc:
            raise ProcessedDataError(
                f"Manifest path escapes processed data directory: {child}"
            ) from exc
        return path

    @staticmethod
    def _validate_requested_samples(requested: list[str], available: set[str]) -> None:
        if len(requested) != len(set(requested)):
            raise ProcessedDataError("Requested sample IDs contain duplicates")
        unknown = sorted(set(requested) - available)
        if unknown:
            raise ProcessedDataError(f"Unknown sample IDs: {unknown[:5]}")
