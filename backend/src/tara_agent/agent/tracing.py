"""统一记录 Agent 执行期间的 Trace 节点。"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from tara_agent.persistence.repositories import SpanRecord


class TraceRepository(Protocol):
    """Trace Recorder 依赖的最小持久化接口。"""

    async def create_span(self, record: SpanRecord) -> None: ...

    async def update_span(self, record: SpanRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class ObservationUpdate:
    """节点开始或结束时可以补充的结构化信息。"""

    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_data: dict[str, Any] | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_parameters: dict[str, Any] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    context_length: int | None = None
    tool_name: str | None = None
    filters: dict[str, Any] | None = None
    marker: str | None = None
    sample_count: int | None = None
    sample_ids: list[str] | None = None
    data_sources: list[dict[str, Any]] | None = None
    artifact_refs: list[dict[str, Any]] | None = None
    attributes: dict[str, Any] | None = None


class TraceRecorder:
    """以同一套生命周期写入本地 Trace，供后续观测适配器复用。"""

    def __init__(self, repository: TraceRepository, trace_id: UUID) -> None:
        self.repository = repository
        self.trace_id = trace_id
        self._next_sequence = 0
        self._records: dict[UUID, SpanRecord] = {}

    async def start_observation(
        self,
        name: str,
        span_kind: str,
        *,
        parent_span_id: UUID | None = None,
        started_at: datetime | None = None,
        details: ObservationUpdate | None = None,
    ) -> UUID:
        """创建运行中的节点并立即持久化。"""

        observation_id = uuid4()
        record = SpanRecord(
            id=observation_id,
            trace_id=self.trace_id,
            parent_span_id=parent_span_id,
            sequence_no=self._next_sequence,
            name=name,
            span_kind=span_kind,
            started_at=started_at or datetime.now(UTC),
        )
        self._next_sequence += 1
        if details is not None:
            record = _merge_update(record, details)
        await self.repository.create_span(record)
        self._records[observation_id] = record
        return observation_id

    async def update_observation(
        self,
        observation_id: UUID,
        details: ObservationUpdate,
    ) -> None:
        """在不改变节点状态的情况下补充执行信息。"""

        record = _merge_update(self._record(observation_id), details)
        await self.repository.update_span(record)
        self._records[observation_id] = record

    async def finish_observation(
        self,
        observation_id: UUID,
        *,
        ended_at: datetime | None = None,
        details: ObservationUpdate | None = None,
    ) -> None:
        """结束节点，并保存耗时和最终结果。"""

        record = self._record(observation_id)
        if record.status != "running":
            if details is not None:
                await self.update_observation(observation_id, details)
            return
        if details is not None:
            record = _merge_update(record, details)
        end = ended_at or datetime.now(UTC)
        record = replace(
            record,
            status="completed",
            ended_at=end,
            duration_ms=_duration_ms(record.started_at, end),
        )
        await self.repository.update_span(record)
        self._records[observation_id] = record

    async def fail_observation(
        self,
        observation_id: UUID,
        *,
        error_code: str,
        error_message: str,
        ended_at: datetime | None = None,
    ) -> None:
        """把仍在运行的节点标记为失败。"""

        record = self._record(observation_id)
        if record.status != "running":
            return
        end = ended_at or datetime.now(UTC)
        record = replace(
            record,
            status="failed",
            ended_at=end,
            duration_ms=_duration_ms(record.started_at, end),
            error_code=error_code,
            error_message=error_message,
        )
        await self.repository.update_span(record)
        self._records[observation_id] = record

    async def fail_open_observations(
        self,
        *,
        error_code: str,
        error_message: str,
        ended_at: datetime | None = None,
    ) -> None:
        """由内向外关闭本次执行中尚未结束的节点。"""

        end = ended_at or datetime.now(UTC)
        open_records = sorted(
            (record for record in self._records.values() if record.status == "running"),
            key=lambda record: record.sequence_no,
            reverse=True,
        )
        for record in open_records:
            await self.fail_observation(
                record.id,
                error_code=error_code,
                error_message=error_message,
                ended_at=end,
            )

    def _record(self, observation_id: UUID) -> SpanRecord:
        try:
            return self._records[observation_id]
        except KeyError as error:
            raise KeyError(f"未知的 Trace 节点：{observation_id}") from error


def _merge_update(record: SpanRecord, update: ObservationUpdate) -> SpanRecord:
    values = {
        field.name: value
        for field in fields(update)
        if (value := getattr(update, field.name)) is not None
    }
    return replace(record, **values)


def _duration_ms(started_at: datetime, ended_at: datetime) -> int:
    return max(0, round((ended_at - started_at).total_seconds() * 1_000))
