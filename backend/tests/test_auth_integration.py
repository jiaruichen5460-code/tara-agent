import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from tara_agent.api.app import create_app
from tara_agent.api.routes.auth import UserResponse
from tara_agent.config import PROJECT_ROOT, Settings
from tara_agent.persistence import (
    AgentTrace,
    AuthSession,
    ChatMessage,
    ChatSession,
    Database,
    TraceSpan,
    User,
)

pytestmark = pytest.mark.integration


def _settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "cors_origins": ["http://test"],
        "_env_file": PROJECT_ROOT / ".env",
        **overrides,
    }
    return Settings(**values)


@pytest.mark.anyio
async def test_auth_cookie_and_user_data_isolation() -> None:
    if os.environ.get("TARA_RUN_DATABASE_TESTS") != "1":
        pytest.skip("设置 TARA_RUN_DATABASE_TESTS=1 后执行本地 PostgreSQL 集成测试")

    settings = _settings()
    database = Database(settings)
    app: FastAPI = create_app(settings, database=database)
    created_user_ids: list[str] = []
    session_id = uuid4()
    trace_id = uuid4()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as first_client:
            anonymous = await first_client.get("/api/v1/auth/me")
            assert anonymous.status_code == 401

            registered = await first_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "First.User@example.com",
                    "display_name": "第一位用户",
                    "password": "first-user-password",
                },
            )
            assert registered.status_code == 201
            first_user_id = registered.json()["user"]["id"]
            created_user_ids.append(first_user_id)
            assert registered.json()["user"]["email"] == "first.user@example.com"
            assert registered.json()["user"]["is_guest"] is False
            assert "HttpOnly" in registered.headers["set-cookie"]
            assert "SameSite=lax" in registered.headers["set-cookie"]
            assert registered.headers["cache-control"] == "no-store"

            raw_token = first_client.cookies[settings.auth_cookie_name]
            async with database.session() as session:
                stored_login = await session.scalar(
                    select(AuthSession).where(AuthSession.user_id == first_user_id)
                )
                assert stored_login is not None
                assert stored_login.token_hash != raw_token
                session.add(
                    ChatSession(
                        id=session_id,
                        user_id=first_user_id,
                        title="仅第一位用户可见",
                    )
                )
                await session.flush()
                session.add(
                    AgentTrace(
                        id=trace_id,
                        session_id=session_id,
                        workflow_name="isolation-test",
                        status="completed",
                    )
                )

            own_sessions = await first_client.get("/api/v1/sessions")
            assert own_sessions.status_code == 200
            assert own_sessions.json()["page"]["total"] == 1

            duplicate = await first_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "first.user@example.com",
                    "display_name": "重复用户",
                    "password": "another-long-password",
                },
            )
            assert duplicate.status_code == 409

            rejected_origin = await first_client.post(
                "/api/v1/auth/logout",
                headers={"Origin": "https://untrusted.example"},
            )
            assert rejected_origin.status_code == 403
            assert (await first_client.get("/api/v1/auth/me")).status_code == 200

            logged_out = await first_client.post("/api/v1/auth/logout")
            assert logged_out.status_code == 204
            assert (await first_client.get("/api/v1/auth/me")).status_code == 401

            invalid_login = await first_client.post(
                "/api/v1/auth/login",
                json={"email": "first.user@example.com", "password": "incorrect"},
            )
            assert invalid_login.status_code == 401

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as second_client:
            registered = await second_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "second.user@example.com",
                    "display_name": "第二位用户",
                    "password": "second-user-password",
                },
            )
            second_user_id = registered.json()["user"]["id"]
            created_user_ids.append(second_user_id)

            other_sessions = await second_client.get("/api/v1/sessions")
            assert other_sessions.status_code == 200
            assert other_sessions.json()["page"]["total"] == 0
            hidden_session = await second_client.get(f"/api/v1/sessions/{session_id}")
            assert hidden_session.status_code == 404
            hidden_session_traces = await second_client.get(
                f"/api/v1/sessions/{session_id}/traces"
            )
            assert hidden_session_traces.status_code == 404
            other_traces = await second_client.get("/api/v1/traces")
            assert other_traces.status_code == 200
            assert other_traces.json()["page"]["total"] == 0
            hidden_trace = await second_client.get(f"/api/v1/traces/{trace_id}")
            assert hidden_trace.status_code == 404
            hidden_session_trace = await second_client.get(
                f"/api/v1/sessions/{session_id}/traces/{trace_id}"
            )
            assert hidden_session_trace.status_code == 404
    finally:
        async with database.session() as session:
            await session.execute(delete(User).where(User.id.in_(created_user_ids)))
        await database.dispose()


@pytest.mark.anyio
async def test_guest_login_reuses_one_shared_user_and_is_disabled_in_production() -> None:
    if os.environ.get("TARA_RUN_DATABASE_TESTS") != "1":
        pytest.skip("设置 TARA_RUN_DATABASE_TESTS=1 后执行本地 PostgreSQL 集成测试")

    guest_email = f"guest-{uuid4()}@example.com"
    settings = _settings(auth_guest_email=guest_email)
    database = Database(settings)
    app = create_app(settings, database=database)
    guest_user_id: str | None = None
    shared_session_id = uuid4()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as first_guest:
            first_login = await first_guest.post("/api/v1/auth/guest")
            assert first_login.status_code == 200
            first_user = first_login.json()["user"]
            guest_user_id = first_user["id"]
            assert first_user["is_guest"] is True

            async with database.session() as session:
                session.add(
                    ChatSession(
                        id=shared_session_id,
                        user_id=guest_user_id,
                        title="游客共享对话",
                    )
                )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as second_guest:
            second_login = await second_guest.post("/api/v1/auth/guest")
            assert second_login.status_code == 200
            assert second_login.json()["user"]["id"] == guest_user_id
            sessions = await second_guest.get("/api/v1/sessions")
            assert sessions.status_code == 200
            assert sessions.json()["page"]["total"] == 1
            assert sessions.json()["items"][0]["title"] == "游客共享对话"

        production_settings = _settings(
            environment="production",
            auth_guest_email=guest_email,
        )
        production_app = create_app(production_settings, database=database)
        async with AsyncClient(
            transport=ASGITransport(app=production_app),
            base_url="http://test",
        ) as production_client:
            rejected = await production_client.post("/api/v1/auth/guest")
            assert rejected.status_code == 403
    finally:
        if guest_user_id is not None:
            async with database.session() as session:
                await session.execute(delete(User).where(User.id == guest_user_id))
        await database.dispose()


def test_default_guest_identity_is_accepted_by_response_schema() -> None:
    settings = _settings()
    response = UserResponse(
        id="guest-test",
        email=settings.auth_guest_email,
        display_name=settings.auth_guest_display_name,
        is_guest=True,
    )

    assert response.email == settings.auth_guest_email


@pytest.mark.anyio
async def test_session_deletion_is_hard_scoped_and_supports_batch() -> None:
    if os.environ.get("TARA_RUN_DATABASE_TESTS") != "1":
        pytest.skip("设置 TARA_RUN_DATABASE_TESTS=1 后执行本地 PostgreSQL 集成测试")

    settings = _settings()
    database = Database(settings)
    app = create_app(settings, database=database)
    owner_id: str | None = None
    other_id: str | None = None
    owner_session_ids = [uuid4(), uuid4()]
    owner_trace_ids = [uuid4(), uuid4()]
    owner_message_ids = [uuid4(), uuid4()]
    owner_span_ids = [uuid4(), uuid4()]
    other_session_id = uuid4()

    try:
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as owner,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other,
        ):
            owner_registration = await owner.post(
                "/api/v1/auth/register",
                json={
                    "email": f"owner-{uuid4()}@example.com",
                    "display_name": "会话所有者",
                    "password": "owner-session-password",
                },
            )
            other_registration = await other.post(
                "/api/v1/auth/register",
                json={
                    "email": f"other-{uuid4()}@example.com",
                    "display_name": "其他用户",
                    "password": "other-session-password",
                },
            )
            owner_id = owner_registration.json()["user"]["id"]
            other_id = other_registration.json()["user"]["id"]

            async with database.session() as session:
                session.add_all(
                    [
                        ChatSession(id=session_id, user_id=owner_id, title="待删除会话")
                        for session_id in owner_session_ids
                    ]
                    + [ChatSession(id=other_session_id, user_id=other_id, title="其他用户会话")]
                )
                await session.flush()
                for index, session_id in enumerate(owner_session_ids):
                    session.add(
                        AgentTrace(
                            id=owner_trace_ids[index],
                            session_id=session_id,
                            workflow_name="delete-test",
                        )
                    )
                await session.flush()
                for index, session_id in enumerate(owner_session_ids):
                    session.add_all(
                        [
                            ChatMessage(
                                id=owner_message_ids[index],
                                session_id=session_id,
                                trace_id=owner_trace_ids[index],
                                sequence_no=0,
                                role="user",
                                content="待删除消息",
                            ),
                            TraceSpan(
                                id=owner_span_ids[index],
                                trace_id=owner_trace_ids[index],
                                sequence_no=0,
                                name="待删除步骤",
                                span_kind="tool",
                            ),
                        ]
                    )

            updated = await owner.patch(
                f"/api/v1/sessions/{owner_session_ids[0]}",
                json={"title": "重命名后的会话", "pinned": True},
            )
            assert updated.status_code == 200
            assert updated.json()["title"] == "重命名后的会话"
            assert updated.json()["pinned_at"] is not None

            sessions = await owner.get("/api/v1/sessions")
            assert sessions.json()["items"][0]["id"] == str(owner_session_ids[0])

            unpinned = await owner.patch(
                f"/api/v1/sessions/{owner_session_ids[0]}",
                json={"pinned": False},
            )
            assert unpinned.status_code == 200
            assert unpinned.json()["pinned_at"] is None

            protected = await owner.patch(
                f"/api/v1/sessions/{other_session_id}",
                json={"title": "不允许修改"},
            )
            assert protected.status_code == 404

            single = await owner.delete(f"/api/v1/sessions/{owner_session_ids[0]}")
            assert single.status_code == 204

            hidden = await owner.delete(f"/api/v1/sessions/{other_session_id}")
            assert hidden.status_code == 404

            batch = await owner.request(
                "DELETE",
                "/api/v1/sessions",
                json={"session_ids": [str(owner_session_ids[1]), str(other_session_id)]},
            )
            assert batch.status_code == 200
            assert batch.json() == {
                "deleted_ids": [str(owner_session_ids[1])],
                "deleted_count": 1,
            }

            async with database.session() as session:
                for session_id in owner_session_ids:
                    assert await session.get(ChatSession, session_id) is None
                for trace_id in owner_trace_ids:
                    assert await session.get(AgentTrace, trace_id) is None
                for message_id in owner_message_ids:
                    assert await session.get(ChatMessage, message_id) is None
                for span_id in owner_span_ids:
                    assert await session.get(TraceSpan, span_id) is None
                assert await session.get(ChatSession, other_session_id) is not None
    finally:
        user_ids = [user_id for user_id in (owner_id, other_id) if user_id is not None]
        if user_ids:
            async with database.session() as session:
                await session.execute(delete(User).where(User.id.in_(user_ids)))
        await database.dispose()
