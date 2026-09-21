"""LangGraph 节点定义、生命周期事件和 Trace 上下文绑定。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.runtime import Runtime

from tara_agent.observability.execution import bind_execution_trace


@dataclass(frozen=True, slots=True)
class WorkflowNodeDefinition:
    """由工作流声明的节点标识和用户可读名称。"""

    name: str
    title: str


@dataclass(frozen=True, slots=True)
class WorkflowTaskEvent:
    """LangGraph 节点生命周期的内部事件，不属于聊天流协议。"""

    task_id: str
    node_name: str
    node_title: str
    phase: Literal["started", "completed", "failed"]
    namespace: tuple[str, ...] = ()
    input_data: Any = None
    output_data: Any = None
    error: str | None = None


@contextmanager
def bind_workflow_trace(runtime: Runtime):
    """使用 LangGraph 官方 task_id 绑定节点内部 Trace 上下文。"""

    execution_info = runtime.execution_info
    parent_id = str(execution_info.task_id) if execution_info is not None else None
    with bind_execution_trace(
        parent_id=parent_id,
        writer=runtime.stream_writer,
    ):
        yield
