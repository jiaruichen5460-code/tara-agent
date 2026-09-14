"""Liveness and readiness routes."""

from fastapi import APIRouter, Request, Response, status

from tara_agent import __version__
from tara_agent.api.schemas import DatasetStatus, HealthResponse
from tara_agent.data.store import ProcessedDataStore

router = APIRouter(tags=["service"])


def _health_response(request: Request) -> HealthResponse:
    store: ProcessedDataStore | None = request.app.state.data_store
    settings = request.app.state.settings

    datasets: list[DatasetStatus] = []
    if store is not None:
        for key, source in store.manifest.sources.items():
            sample_count = 0
            if key == "18s_v4":
                sample_count = store.manifest.coverage.v4_samples
            elif key == "18s_v9":
                sample_count = store.manifest.coverage.v9_samples
            datasets.append(
                DatasetStatus(
                    key=key,
                    filename=source.filename,
                    ready=True,
                    exists=True,
                    size_bytes=source.size_bytes,
                    column_count=source.column_count,
                    sample_column_count=sample_count,
                    missing_columns=[],
                    duplicate_columns=[],
                    invalid_sample_columns=[],
                )
            )
    data_ready = store is not None
    return HealthResponse(
        status="ok" if data_ready else "degraded",
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        data_ready=data_ready,
        datasets=datasets,
    )


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return _health_response(request)


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def ready(request: Request, response: Response) -> HealthResponse:
    payload = _health_response(request)
    if not payload.data_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
