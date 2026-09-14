"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tara_agent import __version__
from tara_agent.agent import AgentModel, DeepSeekChatModel, TaraAgent
from tara_agent.agent.gateway import MCPToolGateway
from tara_agent.api.routes import chat_router, health_router
from tara_agent.config import Settings, get_settings
from tara_agent.data.store import ProcessedDataError, ProcessedDataStore
from tara_agent.mcp import create_server


def create_app(
    settings: Settings | None = None,
    *,
    agent_model: AgentModel | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()

    application = FastAPI(
        title=runtime_settings.app_name,
        version=__version__,
        description="Deterministic analysis API for the Tara-Agent MVP.",
    )
    application.state.settings = runtime_settings
    try:
        application.state.data_store = ProcessedDataStore(runtime_settings.processed_data_dir)
    except ProcessedDataError:
        application.state.data_store = None

    application.state.agent = None
    if application.state.data_store is not None:
        model = agent_model
        if model is None and runtime_settings.deepseek_api_key is not None:
            model = DeepSeekChatModel(runtime_settings)
        if model is not None:
            mcp_server = create_server(application.state.data_store)
            application.state.agent = TaraAgent(model, MCPToolGateway(mcp_server))

    if runtime_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.include_router(health_router, prefix=runtime_settings.api_prefix)
    application.include_router(chat_router, prefix=runtime_settings.api_prefix)
    return application


app = create_app()
