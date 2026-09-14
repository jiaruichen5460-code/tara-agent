"""Whitelisted in-memory MCP client used by the Agent workflow."""

from __future__ import annotations

from mcp import Client
from mcp.server import MCPServer

from tara_agent.agent.models import ToolDefinition, ToolName


class AgentToolError(RuntimeError):
    """Raised when an allowed MCP tool cannot complete a call."""


class MCPToolGateway:
    """Expose only the six approved Tara tools to the Agent."""

    def __init__(self, server: MCPServer) -> None:
        self.server = server
        self.allowed_tools = frozenset(ToolName)

    async def list_tools(self) -> list[ToolDefinition]:
        async with Client(self.server) as client:
            listed = await client.list_tools()

        definitions = []
        for tool in listed.tools:
            if tool.name not in self.allowed_tools:
                continue
            definitions.append(
                ToolDefinition(
                    name=ToolName(tool.name),
                    description=tool.description or "",
                    input_schema=tool.input_schema,
                )
            )
        return definitions

    async def call(self, tool_name: ToolName, arguments: dict) -> dict:
        if tool_name not in self.allowed_tools:
            raise AgentToolError(f"Tool is not allowed: {tool_name}")

        async with Client(self.server) as client:
            result = await client.call_tool(tool_name.value, arguments)
        if result.is_error:
            message = " ".join(
                block.text for block in result.content if hasattr(block, "text")
            )
            raise AgentToolError(message or f"Tool failed: {tool_name}")
        if result.structured_content is None:
            raise AgentToolError(f"Tool returned no structured result: {tool_name}")
        return result.structured_content
