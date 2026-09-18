"""供后续分析结果使用的简洁、可复用数据契约。"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Marker(StrEnum):
    """18S 标记数据集必须明确区分并保持独立。"""

    V4 = "v4"
    V9 = "v9"


class ResultWarning(BaseModel):
    """不影响结果有效性的机器可读警告。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DataProvenance(BaseModel):
    """解释结果所需的数据输入与筛选信息。"""

    model_config = ConfigDict(extra="forbid")

    source_datasets: list[str]
    marker: Marker | None = None
    sample_count: int = Field(ge=0)
    excluded_sample_count: int = Field(default=0, ge=0)
    filters: dict[str, Any] = Field(default_factory=dict)


class ResultMetadata(BaseModel):
    """API 与 MCP 分析响应共用的元数据。"""

    model_config = ConfigDict(extra="forbid")

    provenance: DataProvenance
    warnings: list[ResultWarning] = Field(default_factory=list)
