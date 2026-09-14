"""MCP server factory and stdio entrypoint."""

from mcp.server import MCPServer

from tara_agent.analysis import TaraQueryService, TaraScientificService
from tara_agent.config import get_settings
from tara_agent.data.store import ProcessedDataStore
from tara_agent.mcp.tools import register_tools


def create_server(store: ProcessedDataStore | None = None) -> MCPServer:
    """Create the Tara MCP server over one validated processed-data store."""

    if store is None:
        settings = get_settings()
        store = ProcessedDataStore(settings.processed_data_dir)

    server = MCPServer(
        name="tara-agent",
        title="Tara-Agent",
        version="0.1.0",
        instructions=(
            "Query and analyze the validated Tara Oceans MVP datasets. "
            "Always choose one marker explicitly; V4 and V9 results are independent."
        ),
    )
    register_tools(
        server,
        query_service=TaraQueryService(store),
        scientific_service=TaraScientificService(store),
    )
    return server


def main() -> None:
    """Run the Tara MCP server over the standard stdio transport."""

    create_server().run(transport="stdio")
