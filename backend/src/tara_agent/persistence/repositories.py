"""会话、消息和 Agent 链路的持久化操作。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from tara_agent.persistence.database import Database
from tara_agent.persistence.models import AgentTrace, ChatMessage, ChatSession, TraceSpan


class SessionNotFoundError(LookupError):
    """请求续接的会话不存在。"""


class TraceNotFoundError(LookupError):
    """请求查询的链路不存在。"""


class PersistenceStateError(RuntimeError):
    """持久化记录处于不允许当前操作的状态。"""


@dataclass(frozen=True, slots=True)
class StartedRun:
    """一次已写入数据库、等待 Agent 执行的请求。"""

    session_id: UUID
    trace_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    started_at: datetime


@dataclass(frozen=True, slots=True)
class SpanRecord:
    """一次工作流节点执行结束后需要保存的数据。"""

    sequence_no: int
    name: str
    span_kind: str
    status: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_parameters: dict[str, Any] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    context_length: int | None = None
    tool_name: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    marker: str | None = None
    sample_count: int | None = None
    sample_ids: list[str] = field(default_factory=list)
    data_sources: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


class AgentRunRepository:
    """以短事务保存一次请求，并提供会话与链路的只读查询。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def start_run(
        self,
        *,
        user_id: str,
        question: str,
        session_id: UUID | None,
        workflow_name: str,
        workflow_version: str,
        model_provider: str,
        model_name: str,
        model_parameters: dict[str, Any],
    ) -> StartedRun:
        now = datetime.now(UTC)
        trace_id = uuid4()
        user_message_id = uuid4()
        assistant_message_id = uuid4()

        async with self.database.session() as session:
            if session_id is None:
                conversation = ChatSession(
                    id=uuid4(),
                    user_id=user_id,
                    title=_session_title(question),
                    status="active",
                )
                session.add(conversation)
                await session.flush()
            else:
                conversation = await session.scalar(
                    select(ChatSession)
                    .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
                    .with_for_update()
                )
                if conversation is None or conversation.status == "archived":
                    raise SessionNotFoundError(str(session_id))

            sequence = await session.scalar(
                select(func.max(ChatMessage.sequence_no)).where(
                    ChatMessage.session_id == conversation.id
                )
            )
            user_sequence = 0 if sequence is None else sequence + 1

            trace = AgentTrace(
                id=trace_id,
                session_id=conversation.id,
                workflow_name=workflow_name,
                workflow_version=workflow_version,
                status="running",
                started_at=now,
                model_provider=model_provider,
                model_name=model_name,
                model_parameters=model_parameters,
                input_data={"question": question},
            )
            session.add(trace)
            await session.flush()

            session.add_all(
                [
                    ChatMessage(
                        id=user_message_id,
                        session_id=conversation.id,
                        trace_id=trace_id,
                        sequence_no=user_sequence,
                        role="user",
                        status="completed",
                        content=question,
                    ),
                    ChatMessage(
                        id=assistant_message_id,
                        session_id=conversation.id,
                        trace_id=trace_id,
                        parent_message_id=user_message_id,
                        sequence_no=user_sequence + 1,
                        role="assistant",
                        status="streaming",
                        content="",
                    ),
                ]
            )
            conversation.updated_at = now

        return StartedRun(
            session_id=conversation.id,
            trace_id=trace_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            started_at=now,
        )

    async def complete_run(
        self,
        run: StartedRun,
        *,
        ended_at: datetime,
        duration_ms: int,
        answer: str,
        reasoning: str,
        response_data: dict[str, Any],
        spans: list[SpanRecord],
        markers: list[str],
        sample_count: int | None,
        data_sources: list[dict[str, Any]],
    ) -> None:
        async with self.database.session() as session:
            trace = await session.scalar(
                select(AgentTrace)
                .where(AgentTrace.id == run.trace_id)
                .with_for_update()
            )
            assistant_message = await session.get(ChatMessage, run.assistant_message_id)
            conversation = await session.get(ChatSession, run.session_id)
            if trace is None or assistant_message is None or conversation is None:
                raise PersistenceStateError("请求对应的持久化记录不完整")
            if trace.status != "running":
                raise PersistenceStateError(f"链路已经结束：{trace.status}")

            trace.status = "completed"
            trace.ended_at = ended_at
            trace.duration_ms = duration_ms
            trace.output_data = response_data
            trace.markers = markers
            trace.sample_count = sample_count
            trace.data_sources = data_sources

            assistant_message.status = "completed"
            assistant_message.content = answer
            assistant_message.content_parts = [
                {"type": "reasoning", "content": reasoning},
            ]
            assistant_message.extra = {
                "model": trace.model_name,
                "sources": [item.get("filename") for item in data_sources],
            }
            conversation.updated_at = ended_at
            session.add_all([_span_model(run.trace_id, item) for item in spans])

    async def fail_run(
        self,
        run: StartedRun,
        *,
        ended_at: datetime,
        duration_ms: int,
        error_code: str,
        error_message: str,
        spans: list[SpanRecord],
    ) -> None:
        async with self.database.session() as session:
            trace = await session.scalar(
                select(AgentTrace)
                .where(AgentTrace.id == run.trace_id)
                .with_for_update()
            )
            assistant_message = await session.get(ChatMessage, run.assistant_message_id)
            conversation = await session.get(ChatSession, run.session_id)
            if trace is None or assistant_message is None or conversation is None:
                raise PersistenceStateError("请求对应的持久化记录不完整")
            if trace.status != "running":
                return

            trace.status = "failed"
            trace.ended_at = ended_at
            trace.duration_ms = duration_ms
            trace.error_code = error_code
            trace.error_message = error_message
            assistant_message.status = "failed"
            assistant_message.extra = {
                "error_code": error_code,
                "error_message": error_message,
            }
            conversation.updated_at = ended_at
            session.add_all([_span_model(run.trace_id, item) for item in spans])

    async def list_sessions(
        self, *, user_id: str, limit: int, offset: int
    ) -> tuple[list[ChatSession], int]:
        async with self.database.session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(ChatSession.user_id == user_id)
            )
            records = await session.scalars(
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(
                    ChatSession.pinned_at.desc().nulls_last(),
                    ChatSession.updated_at.desc(),
                    ChatSession.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            return list(records), int(total or 0)

    async def get_session(
        self, session_id: UUID, *, user_id: str
    ) -> tuple[ChatSession, list[ChatMessage], dict[UUID, dict[str, Any]]]:
        async with self.database.session() as session:
            conversation = await session.scalar(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == user_id,
                )
            )
            if conversation is None:
                raise SessionNotFoundError(str(session_id))
            messages = await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.sequence_no.asc(), ChatMessage.id.asc())
            )
            trace_rows = await session.execute(
                select(AgentTrace.id, AgentTrace.output_data).where(
                    AgentTrace.session_id == session_id,
                    AgentTrace.output_data.is_not(None),
                )
            )
            responses = {
                trace_id: dict(output_data)
                for trace_id, output_data in trace_rows
                if isinstance(output_data, dict)
            }
            if responses:
                tool_rows = await session.execute(
                    select(TraceSpan.trace_id, TraceSpan.output_data)
                    .where(
                        TraceSpan.trace_id.in_(responses),
                        TraceSpan.span_kind == "tool",
                        TraceSpan.output_data.is_not(None),
                    )
                    .order_by(TraceSpan.sequence_no.asc())
                )
                for trace_id, result in tool_rows:
                    if isinstance(result, dict):
                        responses[trace_id].setdefault("result", result)
            return conversation, list(messages), responses

    async def delete_session(self, session_id: UUID, *, user_id: str) -> bool:
        """硬删除当前用户的一条会话及其所有级联数据。"""

        async with self.database.session() as session:
            deleted_id = await session.scalar(
                delete(ChatSession)
                .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
                .returning(ChatSession.id)
            )
        return deleted_id is not None

    async def update_session(
        self,
        session_id: UUID,
        *,
        user_id: str,
        title: str | None,
        pinned: bool | None,
    ) -> ChatSession:
        """修改当前用户会话的名称或置顶状态。"""

        async with self.database.session() as session:
            conversation = await session.scalar(
                select(ChatSession)
                .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
                .with_for_update()
            )
            if conversation is None:
                raise SessionNotFoundError(str(session_id))
            if title is not None:
                conversation.title = title
            if pinned is not None:
                conversation.pinned_at = datetime.now(UTC) if pinned else None
            await session.flush()
            await session.refresh(conversation)
        return conversation

    async def delete_sessions(self, session_ids: list[UUID], *, user_id: str) -> list[UUID]:
        """批量硬删除当前用户拥有的会话及其所有级联数据。"""

        if not session_ids:
            return []
        async with self.database.session() as session:
            deleted_ids = list(
                await session.scalars(
                    delete(ChatSession)
                    .where(
                        ChatSession.id.in_(session_ids),
                        ChatSession.user_id == user_id,
                    )
                    .returning(ChatSession.id)
                )
            )
        deleted = set(deleted_ids)
        return [session_id for session_id in session_ids if session_id in deleted]

    async def list_traces(
        self,
        *,
        user_id: str,
        session_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentTrace], int]:
        filters = [ChatSession.user_id == user_id]
        if session_id is not None:
            filters.append(AgentTrace.session_id == session_id)
        async with self.database.session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(AgentTrace)
                .join(ChatSession, ChatSession.id == AgentTrace.session_id)
                .where(*filters)
            )
            records = await session.scalars(
                select(AgentTrace)
                .join(ChatSession, ChatSession.id == AgentTrace.session_id)
                .where(*filters)
                .order_by(AgentTrace.started_at.desc(), AgentTrace.id.desc())
                .offset(offset)
                .limit(limit)
            )
            return list(records), int(total or 0)

    async def get_trace(
        self, trace_id: UUID, *, user_id: str
    ) -> tuple[AgentTrace, list[TraceSpan]]:
        async with self.database.session() as session:
            trace = await session.scalar(
                select(AgentTrace)
                .join(ChatSession, ChatSession.id == AgentTrace.session_id)
                .where(AgentTrace.id == trace_id, ChatSession.user_id == user_id)
            )
            if trace is None:
                raise TraceNotFoundError(str(trace_id))
            spans = await session.scalars(
                select(TraceSpan)
                .where(TraceSpan.trace_id == trace_id)
                .order_by(TraceSpan.sequence_no.asc(), TraceSpan.id.asc())
            )
            return trace, list(spans)


def _session_title(question: str) -> str:
    normalized = " ".join(question.split())
    return normalized if len(normalized) <= 80 else f"{normalized[:79]}…"


def _span_model(trace_id: UUID, record: SpanRecord) -> TraceSpan:
    return TraceSpan(
        trace_id=trace_id,
        sequence_no=record.sequence_no,
        name=record.name,
        span_kind=record.span_kind,
        status=record.status,
        started_at=record.started_at,
        ended_at=record.ended_at,
        duration_ms=record.duration_ms,
        input_data=record.input_data,
        output_data=record.output_data,
        error_code=record.error_code,
        error_message=record.error_message,
        model_provider=record.model_provider,
        model_name=record.model_name,
        model_parameters=record.model_parameters,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        context_length=record.context_length,
        tool_name=record.tool_name,
        filters=record.filters,
        marker=record.marker,
        sample_count=record.sample_count,
        sample_ids=record.sample_ids,
        data_sources=record.data_sources,
        artifact_refs=record.artifact_refs,
        attributes=record.attributes,
    )
