import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from tara_agent.agent.models import ModelStreamDelta
from tara_agent.agent.provider import AgentModelError
from tara_agent.api.app import create_app
from tara_agent.config import PROJECT_ROOT, Settings
from tara_agent.data.preprocess import preprocess
from tara_agent.persistence import Database, User

from .test_agent import RepresentativeModel

pytestmark = pytest.mark.integration


class FailingModel:
    name = "failing-model"
    provider = "test"
    trace_parameters: dict = {}

    async def plan(self, question, tools):
        raise AgentModelError("测试模型规划失败")

    async def stream_answer(self, question, plan, result):
        if False:
            yield ModelStreamDelta(kind="answer", content="")


def _settings(dataset_dir: Path, processed_dir: Path) -> Settings:
    return Settings(
        environment="test",
        dataset_dir=dataset_dir,
        processed_data_dir=processed_dir,
        cors_origins=[],
        _env_file=PROJECT_ROOT / ".env",
    )


def _sse_events(body: str) -> list[dict]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        )
        if data:
            events.append(json.loads(data))
    return events


async def _register(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "集成测试用户",
            "password": "integration-test-password",
        },
    )
    assert response.status_code == 201
    return response.json()["user"]["id"]


@pytest.mark.anyio
async def test_chat_persists_session_messages_and_trace_tree(
    preprocessable_dataset_dir: Path,
    tmp_path: Path,
) -> None:
    if os.environ.get("TARA_RUN_DATABASE_TESTS") != "1":
        pytest.skip("设置 TARA_RUN_DATABASE_TESTS=1 后执行本地 PostgreSQL 集成测试")

    processed_dir = tmp_path / "processed"
    preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    database = Database(_settings(preprocessable_dataset_dir, processed_dir))
    app: FastAPI = create_app(
        _settings(preprocessable_dataset_dir, processed_dir),
        agent_model=RepresentativeModel(),
        database=database,
    )
    session_id: str | None = None
    user_id: str | None = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            user_id = await _register(client, "chat-integration@example.com")
            first = await client.post(
                "/api/v1/chat/stream",
                json={"question": "找一个 Tara 样本"},
            )
            assert first.status_code == 200
            events = _sse_events(first.text)
            assert events[0]["event"] == "run_started"
            session_id = events[0]["session_id"]
            first_trace_id = events[0]["trace_id"]
            assert events[-1]["response"]["session_id"] == session_id
            assert events[-1]["response"]["trace_id"] == first_trace_id

            second = await client.post(
                "/api/v1/chat",
                json={
                    "question": "查看 TARA_TEST_001",
                    "session_id": session_id,
                },
            )
            assert second.status_code == 200
            second_payload = second.json()
            assert second_payload["session_id"] == session_id
            assert second_payload["trace_id"] != first_trace_id

            conversation = await client.get(f"/api/v1/sessions/{session_id}")
            assert conversation.status_code == 200
            messages = conversation.json()["messages"]
            assert [item["sequence_no"] for item in messages] == [0, 1, 2, 3]
            assert [item["role"] for item in messages] == [
                "user",
                "assistant",
                "user",
                "assistant",
            ]
            assert all(item["status"] == "completed" for item in messages)
            assert messages[0]["agent_response"] is None
            live_response = events[-1]["response"]
            restored_response = messages[1]["agent_response"]
            for key in (
                "question",
                "reasoning",
                "answer",
                "model",
                "steps",
                "result",
                "charts",
                "warnings",
                "sources",
                "session_id",
                "trace_id",
                "message_id",
            ):
                assert restored_response[key] == live_response[key]
            assert restored_response["tool"]["name"] == live_response["tool"]["name"]
            assert restored_response["tool"]["arguments"] == live_response["tool"]["arguments"]
            assert messages[3]["agent_response"] == second_payload

            traces = await client.get(
                f"/api/v1/sessions/{session_id}/traces",
            )
            assert traces.status_code == 200
            assert traces.json()["page"]["total"] == 2

            trace = await client.get(
                f"/api/v1/sessions/{session_id}/traces/{first_trace_id}"
            )
            assert trace.status_code == 200
            trace_payload = trace.json()
            assert trace_payload["status"] == "completed"
            assert [item["sequence_no"] for item in trace_payload["spans"]] == [0, 1, 2, 3]
            assert [item["span_kind"] for item in trace_payload["spans"]] == [
                "workflow",
                "llm",
                "tool",
                "llm",
            ]
            root_span = trace_payload["spans"][0]
            assert root_span["parent_span_id"] is None
            assert all(
                item["parent_span_id"] == root_span["id"]
                for item in trace_payload["spans"][1:]
            )
            assert trace_payload["spans"][2]["tool_name"] == "find_samples"
            assert trace_payload["spans"][2]["sample_count"] == 2
            assert trace_payload["spans"][2]["sample_ids"] == ["TARA_TEST_001"]
            assert trace_payload["spans"][2]["attributes"] == {
                "sample_ids_scope": "returned_result"
            }
            assert trace_payload["spans"][1]["total_tokens"] == 120
            assert trace_payload["spans"][3]["total_tokens"] == 240
            assert trace_payload["spans"][3]["context_length"] == 200
            answer_input = trace_payload["spans"][3]["input_data"]
            assert answer_input["question"] == "找一个 Tara 样本"
            assert answer_input["tool_name"] == "find_samples"
            assert "tool_result" in answer_input
            assert "items" not in answer_input["tool_result"]
            assert trace_payload["spans"][3]["attributes"] == {
                "reasoning_tokens": 10
            }
    finally:
        if user_id is not None:
            async with database.session() as session:
                await session.execute(delete(User).where(User.id == user_id))
        await database.dispose()


@pytest.mark.anyio
async def test_failed_model_call_is_persisted(
    preprocessable_dataset_dir: Path,
    tmp_path: Path,
) -> None:
    if os.environ.get("TARA_RUN_DATABASE_TESTS") != "1":
        pytest.skip("设置 TARA_RUN_DATABASE_TESTS=1 后执行本地 PostgreSQL 集成测试")

    processed_dir = tmp_path / "processed"
    preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    settings = _settings(preprocessable_dataset_dir, processed_dir)
    database = Database(settings)
    app = create_app(settings, agent_model=FailingModel(), database=database)
    title = "持久化失败链路测试"
    session_id: str | None = None
    user_id: str | None = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            user_id = await _register(client, "failed-integration@example.com")
            response = await client.post("/api/v1/chat", json={"question": title})
            assert response.status_code == 502

            sessions = await client.get("/api/v1/sessions")
            session = next(item for item in sessions.json()["items"] if item["title"] == title)
            session_id = session["id"]

            conversation = await client.get(f"/api/v1/sessions/{session_id}")
            assert [item["status"] for item in conversation.json()["messages"]] == [
                "completed",
                "failed",
            ]

            traces = await client.get(
                f"/api/v1/sessions/{session_id}/traces",
            )
            trace = traces.json()["items"][0]
            assert trace["status"] == "failed"
            assert trace["question"] == title
            assert trace["error_code"] == "AgentModelError"

            detail = await client.get(
                f"/api/v1/sessions/{session_id}/traces/{trace['id']}"
            )
            spans = detail.json()["spans"]
            assert len(spans) == 2
            assert [item["status"] for item in spans] == ["failed", "failed"]
            assert [item["span_kind"] for item in spans] == ["workflow", "llm"]
            assert spans[1]["parent_span_id"] == spans[0]["id"]
    finally:
        if user_id is not None:
            async with database.session() as session:
                await session.execute(delete(User).where(User.id == user_id))
        await database.dispose()
