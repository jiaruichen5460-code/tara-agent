"""Deterministic access to validated, processed Tara data."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from tara_agent.data.manifest import ArtifactRecord, DataManifest
from tara_agent.domain.contracts import Marker


class ProcessedDataError(RuntimeError):
    """Raised when processed data is absent, invalid, or queried incorrectly."""


class ProcessedDataStore:
    """Expose typed Parquet scans without access to source TSV files."""

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
        """Return all sample context with explicit Parquet-backed types and nulls."""

        return pl.scan_parquet(self._artifact_path(self.manifest.artifacts["context"]))

    def load_sample_context(self, sample_ids: list[str] | None = None) -> pl.DataFrame:
        """Load all context rows or a caller-specified set of sample IDs."""

        query = self.scan_context()
        if sample_ids is not None:
            self._validate_requested_samples(sample_ids, set(self.context_sample_ids()))
            query = query.filter(pl.col("sample_id_pangaea").is_in(sample_ids))
        return query.collect()

    def context_sample_ids(self) -> list[str]:
        """Return context sample IDs in their stable processed order."""

        return (
            self.scan_context()
            .select("sample_id_pangaea")
            .collect()
            .get_column("sample_id_pangaea")
            .to_list()
        )

    def scan_asv_metadata(self, marker: Marker) -> pl.LazyFrame:
        """Return ASV taxonomy and metadata for one explicit marker."""

        artifact = self.manifest.artifacts[f"{marker.value}_metadata"]
        return pl.scan_parquet(self._artifact_path(artifact))

    def marker_sample_ids(self, marker: Marker) -> list[str]:
        """Return the sample columns available for a marker."""

        return list(self.manifest.artifacts[f"{marker.value}_abundance"].repeated_columns)

    def scan_abundance(
        self, marker: Marker, sample_ids: list[str] | None = None
    ) -> pl.LazyFrame:
        """Return one marker's wide count matrix, optionally projected to selected samples."""

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
        """Load joined ASV metadata and projected counts for deterministic analysis."""

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
