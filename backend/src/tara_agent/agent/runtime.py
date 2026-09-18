"""把 Agent 流式执行转换为可持久化的会话和链路记录。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tara_agent import __version__
from tara_agent.agent.context import build_answer_model_input
from tara_agent.agent.graph import TaraAgent
from tara_agent.agent.models import AgentResponse, AgentStreamEvent
from tara_agent.agent.tracing import ObservationUpdate, TraceRecorder
from tara_agent.data.catalog import source_filename
from tara_agent.persistence.repositories import AgentRunRepository, StartedRun

STAGE_DETAILS: dict[str, tuple[str, str]] = {
    "understand": ("理解问题并选择工具", "llm"),
    "execute": ("执行确定性分析", "tool"),
    "answer": ("组织可追踪答案", "llm"),
}


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
        recorder = TraceRecorder(self.repository, self.run_record.trace_id)
        root_id = await recorder.start_observation(
            "Tara Agent 工作流",
            "workflow",
            started_at=self.run_record.started_at,
            details=ObservationUpdate(
                input_data={"question": self.question},
                attributes={"workflow_name": "tara_agent_chat"},
            ),
        )
        stage_ids: dict[str, UUID] = {}
        stage_ids["understand"] = await recorder.start_observation(
            *STAGE_DETAILS["understand"],
            parent_span_id=root_id,
            started_at=self.run_record.started_at,
            details=ObservationUpdate(
                input_data={"question": self.question},
                model_provider=self.model_provider,
                model_name=self.agent.model.name,
                model_parameters=self.model_parameters.get("planner", {}),
            ),
        )
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
                    summary = ObservationUpdate(
                        output_data={"summary": event.step.detail}
                    )
                    if stage == "understand":
                        await recorder.finish_observation(
                            stage_ids["understand"],
                            ended_at=now,
                            details=summary,
                        )
                        stage_ids["execute"] = await recorder.start_observation(
                            *STAGE_DETAILS["execute"],
                            parent_span_id=root_id,
                            started_at=now,
                        )
                        current_stage = "execute"
                    elif stage == "execute":
                        await recorder.finish_observation(
                            stage_ids["execute"],
                            ended_at=now,
                            details=summary,
                        )
                        current_stage = None
                    elif stage == "answer":
                        stage_ids["answer"] = await recorder.start_observation(
                            *STAGE_DETAILS["answer"],
                            parent_span_id=root_id,
                            started_at=now,
                            details=ObservationUpdate(
                                input_data={"question": self.question},
                                model_provider=self.model_provider,
                                model_name=self.agent.model.name,
                                model_parameters=self.model_parameters.get("answer", {}),
                            ),
                        )
                        current_stage = "answer"

                if event.event != "complete" or event.response is None:
                    yield event
                    continue

                terminal_received = True
                if current_stage is not None:
                    await recorder.finish_observation(
                        stage_ids[current_stage],
                        ended_at=now,
                    )
                response = event.response.model_copy(
                    update={
                        "session_id": self.run_record.session_id,
                        "trace_id": self.run_record.trace_id,
                        "message_id": self.run_record.assistant_message_id,
                    }
                )
                await self._enrich_observations(recorder, stage_ids, response)
                await recorder.finish_observation(
                    root_id,
                    ended_at=now,
                    details=ObservationUpdate(
                        output_data={
                            "tool_name": response.tool.name.value,
                            "answer": response.answer,
                        }
                    ),
                )
                await self._complete(response, now)
                yield event.model_copy(update={"response": response})
                return

            if not terminal_received:
                raise RuntimeError("Agent 流在完整响应前结束")
        except BaseException as error:
            ended_at = datetime.now(UTC)
            error_code = type(error).__name__
            error_message = str(error) or "Agent 执行被中断"
            await recorder.fail_open_observations(
                error_code=error_code,
                error_message=error_message,
                ended_at=ended_at,
            )
            await self.repository.fail_run(
                self.run_record,
                ended_at=ended_at,
                duration_ms=_duration_ms(self.run_record.started_at, ended_at),
                error_code=error_code,
                error_message=error_message,
            )
            raise

    async def _complete(
        self,
        response: AgentResponse,
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
            markers=markers,
            sample_count=sample_count,
            data_sources=data_sources,
        )

    async def _enrich_observations(
        self,
        recorder: TraceRecorder,
        stage_ids: dict[str, UUID],
        response: AgentResponse,
    ) -> None:
        usage = response.tool.usage
        await recorder.update_observation(
            stage_ids["understand"],
            ObservationUpdate(
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
            ),
        )

        provenance = _provenance(response.result)
        marker = provenance.get("marker") or _marker_from_arguments(
            response.tool.arguments
        )
        sample_ids = _sample_ids(response.result)
        sample_count = _nonnegative_int(provenance.get("sample_count"))
        attributes = {}
        if sample_count is not None and sample_count > len(sample_ids):
            attributes["sample_ids_scope"] = "returned_result"
        await recorder.update_observation(
            stage_ids["execute"],
            ObservationUpdate(
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
            ),
        )

        usage = response.answer_usage
        await recorder.update_observation(
            stage_ids["answer"],
            ObservationUpdate(
                input_data=build_answer_model_input(
                    self.question,
                    response.tool.name,
                    response.result,
                ),
                output_data={
                    "reasoning": response.reasoning,
                    "answer": response.answer,
                    "charts": [
                        item.model_dump(mode="json") for item in response.charts
                    ],
                    "warnings": [
                        item.model_dump(mode="json") for item in response.warnings
                    ],
                    "sources": response.sources,
                },
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                context_length=usage.input_tokens if usage else None,
                attributes=_usage_attributes(usage),
            ),
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
