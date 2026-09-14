"""FastAPI route modules."""

from tara_agent.api.routes.chat import router as chat_router
from tara_agent.api.routes.health import router as health_router

__all__ = ["chat_router", "health_router"]
