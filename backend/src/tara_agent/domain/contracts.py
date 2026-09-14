"""Small, reusable contracts carried by future analysis results."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Marker(StrEnum):
    """18S marker datasets must remain explicit and independent."""

    V4 = "v4"
    V9 = "v9"


class ResultWarning(BaseModel):
    """A machine-readable warning that does not invalidate a result."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DataProvenance(BaseModel):
    """Data inputs and filtering facts needed to interpret a result."""

    model_config = ConfigDict(extra="forbid")

    source_datasets: list[str]
    marker: Marker | None = None
    sample_count: int = Field(ge=0)
    excluded_sample_count: int = Field(default=0, ge=0)
    filters: dict[str, Any] = Field(default_factory=dict)


class ResultMetadata(BaseModel):
    """Metadata shared by API and MCP analysis responses."""

    model_config = ConfigDict(extra="forbid")

    provenance: DataProvenance
    warnings: list[ResultWarning] = Field(default_factory=list)
