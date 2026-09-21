from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from tara_agent.agent.models import AgentResponse, AgentStreamEvent, ToolTrace
from tara_agent.agent.runtime import PersistentAgentRun
from tara_agent.agent.workflow import WorkflowTaskEvent
from tara_agent.observability.execution import TraceObservationEvent
from tara_agent.persistence.repositories import SpanRecord, StartedRun


class RuntimeRepository:
    def __init__(self) -> None:
        self.spans: dict[object, SpanRecord] = {}
        self.completed = False
        self.failed = False

    async def create_span(self, record: SpanRecord) -> None:
        self.spans[record.id] = record

    async def update_span(self, record: SpanRecord) -> None:
        self.spans[record.id] = record

    async def complete_run(self, run: StartedRun, **values: Any) -> None:
        self.completed = True

    async def fail_run(self, run: StartedRun, **values: Any) -> None:
        self.failed = True


class DynamicWorkflowAgent:
    workflow_name = "dynamic_workflow"
    workflow_title = "动态工作流"

    async def stream_execution(self, question: str):
        yield WorkflowTaskEvent(
            task_id="task-1",
            node_name="branch_a",
            node_title="分支 A",
            phase="started",
            input_data={"question": question},
        )
        yield TraceObservationEvent(
            observation_id="operation-1",
            parent_id="task-1",
            name="分支 A 模型调用",
            span_kind="llm",
            phase="started",
            occurred_at=datetime.now(UTC),
            details={"input_data": {"question": question}},
        )
        yield WorkflowTaskEvent(
            task_id="task-2",
            node_name="branch_b",
            node_title="分支 B",
            phase="started",
            input_data={"question": question},
        )
        yield TraceObservationEvent(
            observation_id="operation-2",
            parent_id="task-2",
            name="分支 B 工具调用",
            span_kind="tool",
            phase="started",
            occurred_at=datetime.now(UTC),
            details={"tool_name": "find_samples"},
        )
        yield TraceObservationEvent(
            observation_id="operation-2",
            parent_id="task-2",
            name="分支 B 工具调用",
            span_kind="tool",
            phase="completed",
            occurred_at=datetime.now(UTC),
            details={"output_data": {"value": 2}},
        )
        yield WorkflowTaskEvent(
            task_id="task-2",
            node_name="branch_b",
            node_title="分支 B",
            phase="completed",
            output_data={"value": 2},
        )
        yield TraceObservationEvent(
            observation_id="operation-1",
            parent_id="task-1",
            name="分支 A 模型调用",
            span_kind="llm",
            phase="completed",
            occurred_at=datetime.now(UTC),
            details={"output_data": {"value": 1}},
        )
        yield WorkflowTaskEvent(
            task_id="task-1",
            node_name="branch_a",
            node_title="分支 A",
            phase="completed",
            output_data={"value": 1},
        )
        yield AgentStreamEvent(
            event="complete",
            response=AgentResponse(
                question=question,
                reasoning="",
                answer="完成",
                model="test-model",
                tool=ToolTrace(
                    name="find_samples",
                    arguments={"query": {"limit": 1}},
                    summary="测试",
                ),
                steps=[],
                result={"metadata": {"provenance": {}}},
                charts=[],
                warnings=[],
                sources=[],
            ),
        )


@pytest.mark.anyio
async def test_persistent_run_records_dynamic_langgraph_tasks() -> None:
    repository = RuntimeRepository()
    started_at = datetime.now(UTC)
    run = StartedRun(
        session_id=uuid4(),
        trace_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        started_at=started_at,
    )
    execution = PersistentAgentRun(
        agent=cast(Any, DynamicWorkflowAgent()),
        repository=cast(Any, repository),
        run=run,
        question="测试动态节点",
    )

    events = [event async for event in execution.stream()]
    spans = sorted(repository.spans.values(), key=lambda item: item.sequence_no)

    assert [event.event for event in events] == ["run_started", "complete"]
    assert [span.span_kind for span in spans] == [
        "workflow",
        "node",
        "llm",
        "node",
        "tool",
    ]
    assert all(span.status == "completed" for span in spans)
    assert spans[1].parent_span_id == spans[0].id
    assert spans[2].parent_span_id == spans[1].id
    assert spans[3].parent_span_id == spans[0].id
    assert spans[4].parent_span_id == spans[3].id
    assert [span.name for span in spans[1:]] == [
        "分支 A",
        "分支 A 模型调用",
        "分支 B",
        "分支 B 工具调用",
    ]
    assert all(
        span.input_data == {"question": "测试动态节点"}
        for span in (spans[1], spans[3])
    )
    assert [span.output_data for span in (spans[1], spans[3])] == [
        {"value": 1},
        {"value": 2},
    ]
    assert spans[1].attributes == {
        "langgraph_task_id": "task-1",
        "langgraph_node": "branch_a",
        "langgraph_namespace": [],
    }
    assert spans[3].attributes["langgraph_task_id"] == "task-2"
    assert spans[4].tool_name == "find_samples"
    assert repository.completed is True
    assert repository.failed is False
