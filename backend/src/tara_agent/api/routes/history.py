"""会话历史与 Agent 链路追溯查询接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from tara_agent.api.dependencies import CurrentUserDependency
from tara_agent.api.schemas import (
    MessageResponse,
    PageInfo,
    SessionDeleteRequest,
    SessionDeleteResponse,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
    SessionUpdateRequest,
    TraceDetail,
    TraceListResponse,
    TraceSpanResponse,
    TraceSummary,
)
from tara_agent.persistence.models import AgentTrace, TraceSpan
from tara_agent.persistence.repositories import (
    AgentRunRepository,
    SessionNotFoundError,
    TraceNotFoundError,
)

router = APIRouter(tags=["history"])


def _repository(request: Request) -> AgentRunRepository:
    repository: AgentRunRepository | None = request.app.state.run_repository
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库持久化服务不可用。",
        )
    return repository


def _trace_summary(record: object) -> TraceSummary:
    summary = TraceSummary.model_validate(record)
    input_data = getattr(record, "input_data", None)
    question = input_data.get("question") if isinstance(input_data, dict) else None
    return summary.model_copy(
        update={"question": question if isinstance(question, str) else None}
    )


def _trace_detail(trace: AgentTrace, spans: list[TraceSpan]) -> TraceDetail:
    summary = _trace_summary(trace)
    return TraceDetail(
        **summary.model_dump(),
        model_parameters=trace.model_parameters,
        input_data=trace.input_data,
        output_data=trace.output_data,
        error_data=trace.error_data,
        attributes=trace.attributes,
        spans=[TraceSpanResponse.model_validate(item) for item in spans],
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    user: CurrentUserDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionListResponse:
    records, total = await _repository(request).list_sessions(
        user_id=user.id,
        limit=limit,
        offset=offset,
    )
    return SessionListResponse(
        items=[SessionSummary.model_validate(item) for item in records],
        page=PageInfo(limit=limit, offset=offset, total=total),
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: UUID,
    request: Request,
    user: CurrentUserDependency,
) -> SessionDetail:
    try:
        conversation, messages, responses = await _repository(request).get_session(
            session_id,
            user_id=user.id,
        )
    except SessionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在。",
        ) from error

    summary = SessionSummary.model_validate(conversation)
    return SessionDetail(
        **summary.model_dump(),
        messages=[
            MessageResponse.model_validate(item).model_copy(
                update={
                    "agent_response": (
                        responses.get(item.trace_id) if item.role == "assistant" else None
                    )
                }
            )
            for item in messages
        ],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    request: Request,
    user: CurrentUserDependency,
) -> Response:
    deleted = await _repository(request).delete_session(session_id, user_id=user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在。",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
async def update_session(
    session_id: UUID,
    payload: SessionUpdateRequest,
    request: Request,
    user: CurrentUserDependency,
) -> SessionSummary:
    try:
        conversation = await _repository(request).update_session(
            session_id,
            user_id=user.id,
            title=payload.title,
            pinned=payload.pinned,
        )
    except SessionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在。",
        ) from error
    return SessionSummary.model_validate(conversation)


@router.delete("/sessions", response_model=SessionDeleteResponse)
async def delete_sessions(
    payload: SessionDeleteRequest,
    request: Request,
    user: CurrentUserDependency,
) -> SessionDeleteResponse:
    deleted_ids = await _repository(request).delete_sessions(
        payload.session_ids,
        user_id=user.id,
    )
    return SessionDeleteResponse(
        deleted_ids=deleted_ids,
        deleted_count=len(deleted_ids),
    )


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    request: Request,
    user: CurrentUserDependency,
    session_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TraceListResponse:
    records, total = await _repository(request).list_traces(
        user_id=user.id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return TraceListResponse(
        items=[_trace_summary(item) for item in records],
        page=PageInfo(limit=limit, offset=offset, total=total),
    )


@router.get("/sessions/{session_id}/traces", response_model=TraceListResponse)
async def list_session_traces(
    session_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TraceListResponse:
    repository = _repository(request)
    if not await repository.session_exists(session_id, user_id=user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在。",
        )
    records, total = await repository.list_traces(
        user_id=user.id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return TraceListResponse(
        items=[_trace_summary(item) for item in records],
        page=PageInfo(limit=limit, offset=offset, total=total),
    )


@router.get("/traces/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: UUID,
    request: Request,
    user: CurrentUserDependency,
) -> TraceDetail:
    try:
        trace, spans = await _repository(request).get_trace(trace_id, user_id=user.id)
    except TraceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="链路记录不存在。",
        ) from error

    return _trace_detail(trace, spans)


@router.get(
    "/sessions/{session_id}/traces/{trace_id}",
    response_model=TraceDetail,
)
async def get_session_trace(
    session_id: UUID,
    trace_id: UUID,
    request: Request,
    user: CurrentUserDependency,
) -> TraceDetail:
    try:
        trace, spans = await _repository(request).get_trace(
            trace_id,
            user_id=user.id,
            session_id=session_id,
        )
    except TraceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="链路记录不存在。",
        ) from error
    return _trace_detail(trace, spans)
