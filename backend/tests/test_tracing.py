import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tara_agent.agent.tracing import ObservationUpdate, TraceRecorder
from tara_agent.persistence.repositories import SpanRecord


class RecordingRepository:
    def __init__(self) -> None:
        self.records: dict[object, SpanRecord] = {}
        self.created: list[SpanRecord] = []
        self.updated: list[SpanRecord] = []

    async def create_span(self, record: SpanRecord) -> None:
        self.records[record.id] = record
        self.created.append(record)

    async def update_span(self, record: SpanRecord) -> None:
        self.records[record.id] = record
        self.updated.append(record)


async def _exercise_trace_lifecycle() -> None:
    repository = RecordingRepository()
    trace_id = uuid4()
    recorder = TraceRecorder(repository, trace_id)
    started_at = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)

    root_id = await recorder.start_observation(
        "工作流",
        "workflow",
        started_at=started_at,
        details=ObservationUpdate(input_data={"question": "测试问题"}),
    )
    child_id = await recorder.start_observation(
        "查询样本",
        "tool",
        parent_span_id=root_id,
        started_at=started_at + timedelta(seconds=1),
        details=ObservationUpdate(tool_name="find_samples"),
    )

    assert [record.status for record in repository.created] == ["running", "running"]
    assert repository.records[child_id].parent_span_id == root_id
    assert repository.records[child_id].sequence_no == 1

    await recorder.finish_observation(
        child_id,
        ended_at=started_at + timedelta(seconds=3),
        details=ObservationUpdate(
            output_data={"sample_count": 2},
            sample_count=2,
        ),
    )
    child = repository.records[child_id]
    assert child.status == "completed"
    assert child.duration_ms == 2_000
    assert child.tool_name == "find_samples"
    assert child.sample_count == 2

    await recorder.fail_open_observations(
        error_code="TestError",
        error_message="测试失败",
        ended_at=started_at + timedelta(seconds=4),
    )
    root = repository.records[root_id]
    assert root.status == "failed"
    assert root.duration_ms == 4_000
    assert root.error_code == "TestError"
    assert repository.records[child_id].status == "completed"


def test_trace_recorder_persists_incremental_nested_lifecycle() -> None:
    asyncio.run(_exercise_trace_lifecycle())
