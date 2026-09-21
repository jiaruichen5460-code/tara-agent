"""用于 Tara 问题的最小化固定流程 LangGraph 工作流。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from tara_agent.agent.charts import build_charts
from tara_agent.agent.gateway import MCPToolGateway
from tara_agent.agent.models import (
    AgentResponse,
    AgentStep,
    AgentStreamEvent,
    ChartSpec,
    ModelUsage,
    ToolPlan,
    ToolTrace,
)
from tara_agent.agent.provider import AgentModel
from tara_agent.agent.workflow import (
    WorkflowNodeDefinition,
    WorkflowTaskEvent,
    bind_workflow_trace,
)
from tara_agent.data.catalog import source_filename
from tara_agent.domain.contracts import ResultWarning
from tara_agent.observability.contracts import ObservationKind, ObservationUpdate
from tara_agent.observability.execution import TraceObservationEvent, observe


class AgentState(TypedDict, total=False):
    question: str
    plan: ToolPlan
    result: dict[str, Any]
    reasoning: str
    answer: str
    charts: list[ChartSpec]
    steps: list[AgentStep]
    answer_usage: ModelUsage


UNDERSTAND_NODE = WorkflowNodeDefinition("understand", "理解问题并选择工具")
EXECUTE_NODE = WorkflowNodeDefinition("execute", "执行科学分析")
ANSWER_NODE = WorkflowNodeDefinition("answer", "组织可追溯答案")


class TaraAgent:
    """通过可追踪的固定工作流执行一次预定的 MCP 调用。"""

    workflow_name = "tara_agent_chat"
    workflow_title = "Tara Agent 工作流"

    def __init__(self, model: AgentModel, gateway: MCPToolGateway) -> None:
        self.model = model
        self.gateway = gateway
        self.node_definitions = {
            item.name: item
            for item in (UNDERSTAND_NODE, EXECUTE_NODE, ANSWER_NODE)
        }
        self.graph = self._build_graph()

    async def run(self, question: str) -> AgentResponse:
        state = await self.graph.ainvoke({"question": question, "steps": []})
        return self._response(state)

    async def stream(self, question: str) -> AsyncIterator[AgentStreamEvent]:
        async for event in self.stream_execution(question):
            if isinstance(event, AgentStreamEvent):
                yield event

    async def stream_execution(
        self,
        question: str,
    ) -> AsyncIterator[
        AgentStreamEvent | WorkflowTaskEvent | TraceObservationEvent
    ]:
        """同时发送聊天事件和仅供持久化运行器使用的节点事件。"""

        state: AgentState = {"question": question, "steps": []}
        sent_stages: set[str] = set()
        async for part in self.graph.astream(
            state,
            stream_mode=["updates", "custom", "tasks"],
            version="v2",
        ):
            if part["type"] == "tasks":
                yield self._task_event(part["data"], part["ns"])
                continue
            if part["type"] == "custom":
                if part["data"].get("event") == "trace_observation":
                    yield TraceObservationEvent.model_validate(part["data"])
                    continue
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

    def _task_event(
        self,
        data: dict[str, Any],
        namespace: tuple[str, ...],
    ) -> WorkflowTaskEvent:
        node_name = str(data["name"])
        definition = self.node_definitions.get(
            node_name,
            WorkflowNodeDefinition(node_name, node_name),
        )
        if "input" in data:
            phase = "started"
        elif data.get("error") is not None:
            phase = "failed"
        else:
            phase = "completed"
        error = data.get("error")
        return WorkflowTaskEvent(
            task_id=str(data["id"]),
            node_name=node_name,
            node_title=definition.title,
            phase=phase,
            namespace=tuple(namespace),
            input_data=data.get("input"),
            output_data=data.get("result"),
            error=str(error) if error is not None else None,
        )

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node(UNDERSTAND_NODE.name, self._understand)
        graph.add_node(EXECUTE_NODE.name, self._execute)
        graph.add_node(ANSWER_NODE.name, self._answer)
        graph.add_edge(START, UNDERSTAND_NODE.name)
        graph.add_edge(UNDERSTAND_NODE.name, EXECUTE_NODE.name)
        graph.add_edge(EXECUTE_NODE.name, ANSWER_NODE.name)
        graph.add_edge(ANSWER_NODE.name, END)
        return graph.compile()

    async def _understand(self, state: AgentState, runtime: Runtime) -> AgentState:
        with bind_workflow_trace(runtime):
            tools = await self.gateway.list_tools()
            with observe(
                "选择分析工具",
                ObservationKind.LLM,
                ObservationUpdate(
                    input_data={
                        "question": state["question"],
                        "available_tools": [tool.model_dump(mode="json") for tool in tools],
                    },
                    **self._model_details("planner"),
                ),
            ) as observation:
                plan = await self.model.plan(state["question"], tools)
                observation.finish(
                    ObservationUpdate(
                        output_data=plan.model_dump(mode="json", exclude={"usage"}),
                        **_usage_details(plan.usage),
                    )
                )
        step = AgentStep(
            stage="understand",
            title="理解问题并选择工具",
            detail=f"选择 {plan.tool_name.value}：{plan.rationale}",
        )
        return {"plan": plan, "steps": [*state.get("steps", []), step]}

    async def _execute(self, state: AgentState, runtime: Runtime) -> AgentState:
        with bind_workflow_trace(runtime):
            plan = state["plan"]
            with observe(
                f"调用 MCP 工具 {plan.tool_name.value}",
                ObservationKind.TOOL,
                ObservationUpdate(
                    input_data=plan.arguments,
                    tool_name=plan.tool_name.value,
                ),
            ) as observation:
                result = await self.gateway.call(plan.tool_name, plan.arguments)
                observation.finish(_tool_result_details(plan, result))
        step = AgentStep(
            stage="execute",
            title="执行科学分析",
            detail=f"已通过 MCP 调用白名单工具 {plan.tool_name.value}。",
        )
        return {"result": result, "steps": [*state.get("steps", []), step]}

    async def _answer(self, state: AgentState, runtime: Runtime) -> AgentState:
        writer = runtime.stream_writer
        step = AgentStep(
            stage="answer",
            title="组织可追踪答案",
            detail="根据工具结果生成回答、警告、来源和图表数据。",
        )
        writer(AgentStreamEvent(event="step", step=step).model_dump(mode="json"))

        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        answer_usage = None
        with bind_workflow_trace(runtime), observe(
            "生成分析回答",
            ObservationKind.LLM,
            ObservationUpdate(
                input_data={
                    "question": state["question"],
                    "plan": state["plan"].model_dump(mode="json", exclude={"usage"}),
                    "tool_result": state["result"],
                },
                **self._model_details("answer"),
            ),
        ) as observation:
            async for delta in self.model.stream_answer(
                state["question"],
                state["plan"],
                state["result"],
            ):
                if delta.kind == "usage":
                    answer_usage = delta.usage
                    continue
                if delta.kind == "reasoning":
                    reasoning_parts.append(delta.content)
                    event = AgentStreamEvent(
                        event="reasoning_delta", delta=delta.content
                    )
                else:
                    answer_parts.append(delta.content)
                    event = AgentStreamEvent(event="answer_delta", delta=delta.content)
                writer(event.model_dump(mode="json"))

            reasoning = "".join(reasoning_parts).strip()
            answer = "".join(answer_parts).strip()
            observation.finish(
                ObservationUpdate(
                    output_data={"reasoning": reasoning, "answer": answer},
                    **_usage_details(answer_usage),
                )
            )

        charts = build_charts(state["plan"].tool_name, state["result"])
        return {
            "reasoning": reasoning,
            "answer": answer,
            "charts": charts,
            "answer_usage": answer_usage,
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
                usage=plan.usage,
            ),
            steps=state["steps"],
            result=result,
            charts=state.get("charts", []),
            warnings=warnings,
            sources=[
                source_filename(str(item))
                for item in provenance.get("source_datasets", [])
            ],
            answer_usage=state.get("answer_usage"),
        )

    def _model_details(self, phase: str) -> dict[str, Any]:
        parameters = dict(getattr(self.model, "trace_parameters", {}))
        phase_parameters = parameters.get(phase, {})
        return {
            "model_provider": str(getattr(self.model, "provider", "unknown")),
            "model_name": self.model.name,
            "model_parameters": (
                phase_parameters if isinstance(phase_parameters, dict) else {}
            ),
        }


def _usage_details(usage: ModelUsage | None) -> dict[str, int | None]:
    if usage is None:
        return {}
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _tool_result_details(plan: ToolPlan, result: dict[str, Any]) -> ObservationUpdate:
    metadata = result.get("metadata")
    provenance = metadata.get("provenance") if isinstance(metadata, dict) else None
    provenance = provenance if isinstance(provenance, dict) else {}
    marker = provenance.get("marker")
    source_datasets = provenance.get("source_datasets", [])
    filters = provenance.get("filters")
    return ObservationUpdate(
        output_data=result,
        tool_name=plan.tool_name.value,
        filters=filters if isinstance(filters, dict) else None,
        marker=str(marker) if marker is not None else None,
        sample_count=(
            provenance["sample_count"]
            if isinstance(provenance.get("sample_count"), int)
            else None
        ),
        data_sources=[
            {"filename": source_filename(str(dataset))}
            for dataset in source_datasets
        ],
    )
