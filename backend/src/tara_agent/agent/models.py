"""Validated contracts for planning, traces, charts, and chat responses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tara_agent.domain.contracts import ResultWarning


class ToolName(StrEnum):
    FIND_SAMPLES = "find_samples"
    GET_SAMPLE_INFO = "get_sample_info"
    FIND_TAXA = "find_taxa"
    TAXON_ABUNDANCE = "taxon_abundance"
    DIVERSITY_ANALYSIS = "diversity_analysis"
    ENVIRONMENT_ASSOCIATION = "environment_association"


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ToolName
    description: str
    input_schema: dict[str, Any]


class ToolPlan(BaseModel):
    """One bounded MCP tool call selected by the model."""

    model_config = ConfigDict(extra="forbid")

    tool_name: ToolName
    arguments: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=300)


@dataclass(frozen=True, slots=True)
class ModelStreamDelta:
    """One provider-independent reasoning or answer text delta."""

    kind: Literal["reasoning", "answer"]
    content: str


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["understand", "execute", "answer"]
    title: str
    detail: str


class ChartKind(StrEnum):
    SAMPLE_MAP = "sample_map"
    BAR = "bar"
    SCATTER = "scatter"


class ChartSpec(BaseModel):
    """Small transport-neutral chart contract rendered by the frontend."""

    model_config = ConfigDict(extra="forbid")

    kind: ChartKind
    title: str
    x: list[str | float]
    y: list[float]
    labels: list[str] = Field(default_factory=list)
    x_label: str
    y_label: str


class ToolTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ToolName
    arguments: dict[str, Any]
    summary: str


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    reasoning: str
    answer: str
    model: str
    tool: ToolTrace
    steps: list[AgentStep]
    result: dict[str, Any]
    charts: list[ChartSpec]
    warnings: list[ResultWarning]
    sources: list[str]


class AgentStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["step", "reasoning_delta", "answer_delta", "complete", "error"]
    step: AgentStep | None = None
    delta: str | None = None
    response: AgentResponse | None = None
    error: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized
