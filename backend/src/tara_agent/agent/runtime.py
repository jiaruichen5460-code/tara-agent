"""把 Agent 流式执行转换为可持久化的会话和链路记录。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tara_agent import __version__
from tara_agent.agent.graph import TaraAgent
from tara_agent.agent.models import AgentResponse, AgentStreamEvent
from tara_agent.data.catalog import source_filename
from tara_agent.persistence.repositories import AgentRunRepository, SpanRecord, StartedRun

STAGE_DETAILS = {
    "understand": (0, "理解问题并选择工具", "llm"),
    "execute": (1, "执行确定性分析", "tool"),
    "answer": (2, "组织可追踪答案", "llm"),
}


@dataclass(slots=True)
class _StageTiming:
    stage: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "running"
    error_code: str | None = None
    error_message: str | None = None

    def finish(
        self,
        ended_at: datetime,
        *,
        status: str = "completed",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.ended_at = ended_at
        self.status = status
        self.error_code = error_code
        self.error_message = error_message

    @property
    def duration_ms(self) -> int:
        if self.ended_at is None:
            return 0
        return max(0, round((self.ended_at - self.started_at).total_seconds() * 1_000))


class PersistentAgentRunner:
    """启动持久化请求，并为同步与流式接口复用同一执行路径。"""

    def __init__(self, agent: TaraAgent, repository: AgentRunRepository) -> None:
        self.agent = agent
        self.repository = repository

    async def start(
        self, question: str, user_id: str, session_id: UUID | None = None
    ) -> PersistentAgentRun:
        model_provider = str(getattr(self.agent.model, "provider", "unknown"))
        model_parameters = dict(getattr(self.agent.model, "trace_parameters", {}))
        run = await self.repository.start_run(
            user_id=user_id,
            question=question,
            session_id=session_id,
            workflow_name="tara_agent_chat",
            workflow_version=__version__,
            model_provider=model_provider,
            model_name=self.agent.model.name,
            model_parameters=model_parameters,
        )
        return PersistentAgentRun(
            agent=self.agent,
            repository=self.repository,
            run=run,
            question=question,
            model_provider=model_provider,
            model_parameters=model_parameters,
        )

    async def run(
        self, question: str, user_id: str, session_id: UUID | None = None
    ) -> AgentResponse:
        execution = await self.start(question, user_id, session_id)
        response: AgentResponse | None = None
        async for event in execution.stream():
            if event.event == "complete":
                response = event.response
        if response is None:
            raise RuntimeError("Agent 执行结束但未返回完整响应")
        return response


class PersistentAgentRun:
    """一次已经分配 session_id 和 trace_id 的 Agent 执行。"""

    def __init__(
        self,
        *,
        agent: TaraAgent,
        repository: AgentRunRepository,
        run: StartedRun,
        question: str,
        model_provider: str,
        model_parameters: dict[str, Any],
    ) -> None:
        self.agent = agent
        self.repository = repository
        self.run_record = run
        self.question = question
        self.model_provider = model_provider
        self.model_parameters = model_parameters

    async def stream(self) -> AsyncIterator[AgentStreamEvent]:
        timings: dict[str, _StageTiming] = {
            "understand": _StageTiming("understand", self.run_record.started_at)
        }
        current_stage: str | None = "understand"
        terminal_received = False

        yield AgentStreamEvent(
            event="run_started",
            session_id=self.run_record.session_id,
            trace_id=self.run_record.trace_id,
        )

        try:
            async for event in self.agent.stream(self.question):
                now = datetime.now(UTC)
                if event.event == "step" and event.step is not None:
                    stage = event.step.stage
                    current_stage = _advance_timing(timings, current_stage, stage, now)

                if event.event != "complete" or event.response is None:
                    yield event
                    continue

                terminal_received = True
                _finish_current(timings, current_stage, now)
                response = event.response.model_copy(
                    update={
                        "session_id": self.run_record.session_id,
                        "trace_id": self.run_record.trace_id,
                        "message_id": self.run_record.assistant_message_id,
                    }
                )
                await self._complete(response, timings, now)
                yield event.model_copy(update={"response": response})
                return

            if not terminal_received:
                raise RuntimeError("Agent 流在完整响应前结束")
        except BaseException as error:
            ended_at = datetime.now(UTC)
            error_code = type(error).__name__
            error_message = str(error) or "Agent 执行被中断"
            _finish_current(
                timings,
                current_stage,
                ended_at,
                status="failed",
                error_code=error_code,
                error_message=error_message,
            )
            await self.repository.fail_run(
                self.run_record,
                ended_at=ended_at,
                duration_ms=_duration_ms(self.run_record.started_at, ended_at),
                error_code=error_code,
                error_message=error_message,
                spans=self._span_records(timings, None),
            )
            raise

    async def _complete(
        self,
        response: AgentResponse,
        timings: dict[str, _StageTiming],
        ended_at: datetime,
    ) -> None:
        provenance = _provenance(response.result)
        marker = provenance.get("marker") or _marker_from_arguments(response.tool.arguments)
        markers = [str(marker)] if marker else []
        sample_count = _nonnegative_int(provenance.get("sample_count"))
        data_sources = [{"filename": item} for item in response.sources]
        response_data = response.model_dump(mode="json", exclude={"result"})

        await self.repository.complete_run(
            self.run_record,
            ended_at=ended_at,
            duration_ms=_duration_ms(self.run_record.started_at, ended_at),
            answer=response.answer,
            reasoning=response.reasoning,
            response_data=response_data,
            spans=self._span_records(timings, response),
            markers=markers,
            sample_count=sample_count,
            data_sources=data_sources,
        )

    def _span_records(
        self,
        timings: dict[str, _StageTiming],
        response: AgentResponse | None,
    ) -> list[SpanRecord]:
        records = []
        for stage in ("understand", "execute", "answer"):
            timing = timings.get(stage)
            if timing is None or timing.ended_at is None:
                continue
            records.append(self._span_record(timing, response))
        return records

    def _span_record(
        self,
        timing: _StageTiming,
        response: AgentResponse | None,
    ) -> SpanRecord:
        sequence_no, name, span_kind = STAGE_DETAILS[timing.stage]
        common = {
            "sequence_no": sequence_no,
            "name": name,
            "span_kind": span_kind,
            "status": timing.status,
            "started_at": timing.started_at,
            "ended_at": timing.ended_at,
            "duration_ms": timing.duration_ms,
            "error_code": timing.error_code,
            "error_message": timing.error_message,
        }
        if response is None:
            model_fields: dict[str, Any] = {}
            if span_kind == "llm":
                model_fields = {
                    "model_provider": self.model_provider,
                    "model_name": self.agent.model.name,
                    "model_parameters": self.model_parameters.get(
                        "planner" if timing.stage == "understand" else "answer",
                        {},
                    ),
                }
            return SpanRecord(
                **common,
                input_data={"question": self.question},
                **model_fields,
            )

        if timing.stage == "understand":
            usage = response.tool.usage
            return SpanRecord(
                **common,
                input_data={"question": self.question},
                output_data={
                    "tool_name": response.tool.name.value,
                    "arguments": response.tool.arguments,
                    "rationale": response.tool.summary,
                },
                model_provider=self.model_provider,
                model_name=response.model,
                model_parameters=self.model_parameters.get("planner", {}),
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                context_length=usage.input_tokens if usage else None,
                attributes=_usage_attributes(usage),
            )

        if timing.stage == "execute":
            provenance = _provenance(response.result)
            marker = provenance.get("marker") or _marker_from_arguments(
                response.tool.arguments
            )
            sample_ids = _sample_ids(response.result)
            sample_count = _nonnegative_int(provenance.get("sample_count"))
            attributes = {}
            if sample_count is not None and sample_count > len(sample_ids):
                attributes["sample_ids_scope"] = "returned_result"
            return SpanRecord(
                **common,
                input_data=response.tool.arguments,
                output_data=response.result,
                tool_name=response.tool.name.value,
                filters=dict(provenance.get("filters") or {}),
                marker=str(marker) if marker else None,
                sample_count=sample_count,
                sample_ids=sample_ids,
                data_sources=[
                    {"filename": source_filename(str(item))}
                    for item in provenance.get("source_datasets", [])
                ],
                attributes=attributes,
            )

        usage = response.answer_usage
        return SpanRecord(
            **common,
            input_data={
                "question": self.question,
                "tool_name": response.tool.name.value,
            },
            output_data={
                "reasoning": response.reasoning,
                "answer": response.answer,
                "charts": [item.model_dump(mode="json") for item in response.charts],
                "warnings": [item.model_dump(mode="json") for item in response.warnings],
                "sources": response.sources,
            },
            model_provider=self.model_provider,
            model_name=response.model,
            model_parameters=self.model_parameters.get("answer", {}),
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            context_length=usage.input_tokens if usage else None,
            attributes=_usage_attributes(usage),
        )


def _advance_timing(
    timings: dict[str, _StageTiming],
    current_stage: str | None,
    event_stage: str,
    now: datetime,
) -> str | None:
    if event_stage == "understand":
        _finish_current(timings, current_stage, now)
        timings["execute"] = _StageTiming("execute", now)
        return "execute"
    if event_stage == "execute":
        _finish_current(timings, current_stage, now)
        return None
    if event_stage == "answer":
        timings["answer"] = _StageTiming("answer", now)
        return "answer"
    return current_stage


def _finish_current(
    timings: dict[str, _StageTiming],
    current_stage: str | None,
    ended_at: datetime,
    *,
    status: str = "completed",
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    if current_stage is None:
        return
    timing = timings.get(current_stage)
    if timing is None or timing.ended_at is not None:
        return
    timing.finish(
        ended_at,
        status=status,
        error_code=error_code,
        error_message=error_message,
    )


def _duration_ms(started_at: datetime, ended_at: datetime) -> int:
    return max(0, round((ended_at - started_at).total_seconds() * 1_000))


def _provenance(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    provenance = metadata.get("provenance")
    return provenance if isinstance(provenance, dict) else {}


def _marker_from_arguments(arguments: dict[str, Any]) -> str | None:
    query = arguments.get("query")
    if isinstance(query, dict) and query.get("marker") is not None:
        return str(query["marker"])
    marker = arguments.get("marker")
    return str(marker) if marker is not None else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _sample_ids(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    sample = result.get("sample")
    if isinstance(sample, dict):
        _append_sample_id(values, sample)

    for key in ("items", "sample_occurrences", "observations", "points"):
        items = result.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                _append_sample_id(values, item)
    return list(dict.fromkeys(values))


def _append_sample_id(values: list[str], item: dict[str, Any]) -> None:
    value = item.get("sample_id") or item.get("sample_id_pangaea")
    if isinstance(value, str) and value:
        values.append(value)


def _usage_attributes(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    attributes = {}
    if usage.cached_tokens is not None:
        attributes["cached_tokens"] = usage.cached_tokens
    if usage.reasoning_tokens is not None:
        attributes["reasoning_tokens"] = usage.reasoning_tokens
    return attributes
