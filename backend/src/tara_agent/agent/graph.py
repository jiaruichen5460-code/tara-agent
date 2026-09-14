"""Minimal, fixed-path LangGraph workflow for Tara questions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from tara_agent.agent.charts import build_charts
from tara_agent.agent.gateway import MCPToolGateway
from tara_agent.agent.models import (
    AgentResponse,
    AgentStep,
    AgentStreamEvent,
    ChartSpec,
    ToolPlan,
    ToolTrace,
)
from tara_agent.agent.provider import AgentModel
from tara_agent.domain.contracts import ResultWarning


class AgentState(TypedDict, total=False):
    question: str
    plan: ToolPlan
    result: dict[str, Any]
    reasoning: str
    answer: str
    charts: list[ChartSpec]
    steps: list[AgentStep]


class TaraAgent:
    """Run one planned MCP call through a traceable fixed workflow."""

    def __init__(self, model: AgentModel, gateway: MCPToolGateway) -> None:
        self.model = model
        self.gateway = gateway
        self.graph = self._build_graph()

    async def run(self, question: str) -> AgentResponse:
        state = await self.graph.ainvoke({"question": question, "steps": []})
        return self._response(state)

    async def stream(self, question: str) -> AsyncIterator[AgentStreamEvent]:
        state: AgentState = {"question": question, "steps": []}
        sent_stages: set[str] = set()
        async for part in self.graph.astream(
            state,
            stream_mode=["updates", "custom"],
            version="v2",
        ):
            if part["type"] == "custom":
                event = AgentStreamEvent.model_validate(part["data"])
                if event.step is not None:
                    sent_stages.add(event.step.stage)
                yield event
                continue

            if part["type"] != "updates":
                continue
            for values in part["data"].values():
                state.update(values)
                steps = values.get("steps", [])
                if not steps or steps[-1].stage in sent_stages:
                    continue
                sent_stages.add(steps[-1].stage)
                yield AgentStreamEvent(event="step", step=steps[-1])
        yield AgentStreamEvent(event="complete", response=self._response(state))

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("understand", self._understand)
        graph.add_node("execute", self._execute)
        graph.add_node("answer", self._answer)
        graph.add_edge(START, "understand")
        graph.add_edge("understand", "execute")
        graph.add_edge("execute", "answer")
        graph.add_edge("answer", END)
        return graph.compile()

    async def _understand(self, state: AgentState) -> AgentState:
        tools = await self.gateway.list_tools()
        plan = await self.model.plan(state["question"], tools)
        step = AgentStep(
            stage="understand",
            title="理解问题并选择工具",
            detail=f"选择 {plan.tool_name.value}：{plan.rationale}",
        )
        return {"plan": plan, "steps": [*state.get("steps", []), step]}

    async def _execute(self, state: AgentState) -> AgentState:
        plan = state["plan"]
        result = await self.gateway.call(plan.tool_name, plan.arguments)
        step = AgentStep(
            stage="execute",
            title="执行确定性分析",
            detail=f"已通过 MCP 调用白名单工具 {plan.tool_name.value}。",
        )
        return {"result": result, "steps": [*state.get("steps", []), step]}

    async def _answer(self, state: AgentState, writer: StreamWriter) -> AgentState:
        step = AgentStep(
            stage="answer",
            title="组织可追踪答案",
            detail="根据工具结果生成回答、警告、来源和图表数据。",
        )
        writer(AgentStreamEvent(event="step", step=step).model_dump(mode="json"))

        reasoning_parts = []
        answer_parts = []
        async for delta in self.model.stream_answer(
            state["question"],
            state["plan"],
            state["result"],
        ):
            if delta.kind == "reasoning":
                reasoning_parts.append(delta.content)
                event = AgentStreamEvent(event="reasoning_delta", delta=delta.content)
            else:
                answer_parts.append(delta.content)
                event = AgentStreamEvent(event="answer_delta", delta=delta.content)
            writer(event.model_dump(mode="json"))

        reasoning = "".join(reasoning_parts).strip()
        answer = "".join(answer_parts).strip()
        charts = build_charts(state["plan"].tool_name, state["result"])
        return {
            "reasoning": reasoning,
            "answer": answer,
            "charts": charts,
            "steps": [*state.get("steps", []), step],
        }

    def _response(self, state: AgentState) -> AgentResponse:
        result = state["result"]
        plan = state["plan"]
        metadata = result.get("metadata", {})
        provenance = metadata.get("provenance", {})
        warnings = [
            ResultWarning.model_validate(item) for item in metadata.get("warnings", [])
        ]
        return AgentResponse(
            question=state["question"],
            reasoning=state.get("reasoning", ""),
            answer=state["answer"],
            model=self.model.name,
            tool=ToolTrace(
                name=plan.tool_name,
                arguments=plan.arguments,
                summary=plan.rationale,
            ),
            steps=state["steps"],
            result=result,
            charts=state.get("charts", []),
            warnings=warnings,
            sources=[str(item) for item in provenance.get("source_datasets", [])],
        )
