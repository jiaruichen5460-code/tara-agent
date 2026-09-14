"""Versioned contracts for processed Tara data."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SourceFileRecord(BaseModel):
    """Identity and observed shape of one immutable source file."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    size_bytes: int = Field(ge=0)
    modified_ns: int = Field(ge=0)
    sha256: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class ArtifactRecord(BaseModel):
    """Integrity, shape, and logical schema of a generated artifact."""

    model_config = ConfigDict(extra="forbid")

    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    fixed_schema: dict[str, str]
    repeated_column_type: str | None = None
    repeated_columns: list[str] = Field(default_factory=list)


class CoverageRecord(BaseModel):
    """Sample relationships across context, V4, and V9."""

    model_config = ConfigDict(extra="forbid")

    context_samples: int = Field(ge=0)
    v4_samples: int = Field(ge=0)
    v9_samples: int = Field(ge=0)
    shared_marker_samples: int = Field(ge=0)
    v4_only_samples: int = Field(ge=0)
    v9_only_samples: int = Field(ge=0)
    context_without_marker_samples: int = Field(ge=0)
    v4_only_sample_ids: list[str]
    v9_only_sample_ids: list[str]
    context_without_marker_sample_ids: list[str]
    marker_samples_missing_context: list[str]


class ProcessingMetrics(BaseModel):
    """Resource observations from one completed preprocessing run."""

    model_config = ConfigDict(extra="forbid")

    elapsed_seconds: float = Field(ge=0)
    peak_memory_bytes: int = Field(ge=0)
    source_bytes: int = Field(ge=0)
    output_bytes: int = Field(ge=0)


class DataManifest(BaseModel):
    """Pointer from a stable manifest to one complete data generation."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: int = 1
    pipeline_version: str
    generation: str
    created_at_utc: str
    sources: dict[str, SourceFileRecord]
    artifacts: dict[str, ArtifactRecord]
    coverage: CoverageRecord
    metrics: ProcessingMetrics
    validation_report: str
    benchmark_report: str

    @classmethod
    def load(cls, path: Path) -> DataManifest:
        """Load and validate a manifest from disk."""

        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, path: Path) -> None:
        """Write stable, human-readable JSON. Atomic replacement is handled by the caller."""

        payload = self.model_dump(mode="json")
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
