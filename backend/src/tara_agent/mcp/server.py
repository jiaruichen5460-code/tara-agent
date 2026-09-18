"""MCP 服务工厂和标准输入输出入口。"""

from mcp.server import MCPServer

from tara_agent.analysis import TaraQueryService, TaraScientificService
from tara_agent.config import get_settings
from tara_agent.data.reader import ProcessedDataReader
from tara_agent.mcp.tools import register_tools


def create_server(reader: ProcessedDataReader | None = None) -> MCPServer:
    """基于一个已校验的处理后数据读取器创建 Tara MCP 服务。"""

    if reader is None:
        settings = get_settings()
        reader = ProcessedDataReader(settings.processed_data_dir)

    server = MCPServer(
        name="tara-agent",
        title="Tara Agent",
        version="0.1.0",
        instructions=(
            "Query and analyze the validated Tara Oceans MVP datasets. "
            "Always choose one marker explicitly; V4 and V9 results are independent."
        ),
    )
    register_tools(
        server,
        query_service=TaraQueryService(reader),
        scientific_service=TaraScientificService(reader),
    )
    return server


def main() -> None:
    """通过标准输入输出传输方式运行 Tara MCP 服务。"""

    create_server().run(transport="stdio")
