"""处理后 Tara 数据的版本化契约。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SourceFileRecord(BaseModel):
    """一个不可修改源文件的标识及实际数据规模。"""

    model_config = ConfigDict(extra="forbid")

    filename: str
    size_bytes: int = Field(ge=0)
    modified_ns: int = Field(ge=0)
    sha256: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class ArtifactRecord(BaseModel):
    """生成产物的完整性、规模和逻辑结构。"""

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
    """背景数据、V4 和 V9 之间的样本关系。"""

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
    """一次已完成预处理运行的资源使用记录。"""

    model_config = ConfigDict(extra="forbid")

    elapsed_seconds: float = Field(ge=0)
    peak_memory_bytes: int = Field(ge=0)
    source_bytes: int = Field(ge=0)
    output_bytes: int = Field(ge=0)


class DataManifest(BaseModel):
    """从稳定清单指向一次完整数据生成结果的引用。"""

    model_config = ConfigDict(extra="forbid")

    manifest_version: int = 2
    pipeline_version: str
    generation: str
    created_at_utc: str
    sources: dict[str, SourceFileRecord]
    artifacts: dict[str, ArtifactRecord]
    coverage: CoverageRecord
    metrics: ProcessingMetrics
    validation_report: str
    benchmark_report: str | None = Field(
        default=None,
        exclude=True,
        description="Legacy manifest v1 field accepted for backward compatibility.",
    )

    @classmethod
    def load(cls, path: Path) -> DataManifest:
        """从磁盘加载并校验数据清单。"""

        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, path: Path) -> None:
        """写入稳定、便于阅读的 JSON；原子替换由调用方处理。"""

        payload = self.model_dump(mode="json", exclude_none=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
