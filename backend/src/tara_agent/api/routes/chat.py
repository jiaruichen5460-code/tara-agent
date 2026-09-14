"""Traceable chat and Server-Sent Events endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from tara_agent.agent.gateway import AgentToolError
from tara_agent.agent.graph import TaraAgent
from tara_agent.agent.models import AgentResponse, AgentStreamEvent, ChatRequest
from tara_agent.agent.provider import AgentModelError

router = APIRouter(prefix="/chat", tags=["agent"])


def _agent(request: Request) -> TaraAgent:
    agent: TaraAgent | None = request.app.state.agent
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent is unavailable. Check processed data and DEEPSEEK_API_KEY.",
        )
    return agent


@router.post("", response_model=AgentResponse)
async def chat(payload: ChatRequest, request: Request) -> AgentResponse:
    """Run one complete Tara-Agent workflow."""

    try:
        return await _agent(request).run(payload.question)
    except AgentToolError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except AgentModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/stream", response_class=StreamingResponse)
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream workflow steps and the final response as SSE."""

    agent = _agent(request)

    async def events() -> AsyncIterator[str]:
        try:
            async for event in agent.stream(payload.question):
                yield _sse(event)
        except (AgentToolError, AgentModelError) as exc:
            yield _sse(AgentStreamEvent(event="error", error=str(exc)))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: AgentStreamEvent) -> str:
    data = event.model_dump_json(exclude_none=True)
    return f"event: {event.event}\ndata: {data}\n\n"
