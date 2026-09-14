"""HTTP response schemas for service and dataset readiness."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DatasetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    filename: str
    ready: bool
    exists: bool
    size_bytes: int = Field(ge=0)
    column_count: int = Field(ge=0)
    sample_column_count: int = Field(ge=0)
    missing_columns: list[str]
    duplicate_columns: list[str]
    invalid_sample_columns: list[str]
    error: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    data_ready: bool
    datasets: list[DatasetStatus]
