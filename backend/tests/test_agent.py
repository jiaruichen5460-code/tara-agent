from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tara_agent.agent import AgentModel
from tara_agent.agent.gateway import MCPToolGateway
from tara_agent.agent.graph import TaraAgent
from tara_agent.agent.models import (
    ModelStreamDelta,
    ModelUsage,
    ToolDefinition,
    ToolName,
    ToolPlan,
)
from tara_agent.data.preprocess import preprocess
from tara_agent.data.reader import ProcessedDataReader
from tara_agent.mcp import create_server


class RepresentativeModel(AgentModel):
    name = "test-model"

    plans = {
        "找一个 Tara 样本": ToolPlan(
            tool_name="find_samples",
            arguments={"query": {"limit": 1}},
            rationale="需要筛选样本。",
        ),
        "查看 TARA_TEST_001": ToolPlan(
            tool_name="get_sample_info",
            arguments={"sample_id": "TARA_TEST_001"},
            rationale="需要查看单个样本。",
        ),
        "V4 中有哪些 Dinoflagellata ASV": ToolPlan(
            tool_name="find_taxa",
            arguments={"query": {"marker": "v4", "taxon": "Dinoflagellata"}},
            rationale="需要查询分类群。",
        ),
        "V4 Dinoflagellata 的相对丰度": ToolPlan(
            tool_name="taxon_abundance",
            arguments={"query": {"marker": "v4", "taxon": "Dinoflagellata"}},
            rationale="需要计算相对丰度。",
        ),
        "按极地分组比较 V9 多样性": ToolPlan(
            tool_name="diversity_analysis",
            arguments={"query": {"marker": "v9", "group_by": "polar"}},
            rationale="需要计算分组多样性。",
        ),
        "V4 Dinoflagellata 丰度和温度是否相关": ToolPlan(
            tool_name="environment_association",
            arguments={
                "query": {
                    "marker": "v4",
                    "taxon": "Dinoflagellata",
                    "environment_variable": "temperature",
                }
            },
            rationale="需要计算环境关联。",
        ),
    }

    async def plan(
        self,
        question: str,
        tools: list[ToolDefinition],
    ) -> ToolPlan:
        assert {tool.name for tool in tools} == set(ToolName)
        return self.plans[question].model_copy(
            update={
                "usage": ModelUsage(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                )
            }
        )

    async def stream_answer(
        self,
        question: str,
        plan: ToolPlan,
        result: dict[str, Any],
    ):
        assert result
        answer = f"已使用 {plan.tool_name.value} 回答：{question}"
        midpoint = len(answer) // 2
        yield ModelStreamDelta(kind="reasoning", content="先检查工具结果。")
        yield ModelStreamDelta(kind="answer", content=answer[:midpoint])
        yield ModelStreamDelta(kind="answer", content=answer[midpoint:])
        yield ModelStreamDelta(
            kind="usage",
            usage=ModelUsage(
                input_tokens=200,
                output_tokens=40,
                total_tokens=240,
                reasoning_tokens=10,
            ),
        )


@pytest.fixture
def representative_model() -> RepresentativeModel:
    return RepresentativeModel()


@pytest.fixture
def tara_agent(
    preprocessable_dataset_dir: Path,
    tmp_path: Path,
    representative_model: RepresentativeModel,
) -> TaraAgent:
    processed_dir = tmp_path / "processed"
    preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    server = create_server(ProcessedDataReader(processed_dir))
    return TaraAgent(representative_model, MCPToolGateway(server))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("question", "expected_tool", "expected_chart"),
    [
        ("找一个 Tara 样本", ToolName.FIND_SAMPLES, "sample_map"),
        ("查看 TARA_TEST_001", ToolName.GET_SAMPLE_INFO, None),
        ("V4 中有哪些 Dinoflagellata ASV", ToolName.FIND_TAXA, "bar"),
        ("V4 Dinoflagellata 的相对丰度", ToolName.TAXON_ABUNDANCE, "bar"),
        ("按极地分组比较 V9 多样性", ToolName.DIVERSITY_ANALYSIS, "bar"),
        ("V4 Dinoflagellata 丰度和温度是否相关", ToolName.ENVIRONMENT_ASSOCIATION, "scatter"),
    ],
)
async def test_representative_questions_follow_expected_tool_trace(
    tara_agent: TaraAgent,
    question: str,
    expected_tool: ToolName,
    expected_chart: str | None,
) -> None:
    response = await tara_agent.run(question)

    assert response.tool.name is expected_tool
    assert [step.stage for step in response.steps] == ["understand", "execute", "answer"]
    assert response.result
    assert response.model == "test-model"
    assert [chart.kind for chart in response.charts] == (
        [expected_chart] if expected_chart else []
    )


def test_plan_rejects_non_whitelisted_tool() -> None:
    with pytest.raises(ValidationError):
        ToolPlan.model_validate(
            {
                "tool_name": "run_sql",
                "arguments": {"sql": "select *"},
                "rationale": "not allowed",
            }
        )


@pytest.mark.anyio
async def test_stream_exposes_steps_answer_deltas_then_complete(tara_agent: TaraAgent) -> None:
    events = [event async for event in tara_agent.stream("找一个 Tara 样本")]

    assert [event.event for event in events] == [
        "step",
        "step",
        "step",
        "reasoning_delta",
        "answer_delta",
        "answer_delta",
        "complete",
    ]
    assert events[-1].response is not None
    assert events[-1].response.tool.name is ToolName.FIND_SAMPLES
    streamed_reasoning = "".join(
        event.delta or "" for event in events if event.event == "reasoning_delta"
    )
    streamed_answer = "".join(
        event.delta or "" for event in events if event.event == "answer_delta"
    )
    assert streamed_reasoning == events[-1].response.reasoning
    assert streamed_answer == events[-1].response.answer
