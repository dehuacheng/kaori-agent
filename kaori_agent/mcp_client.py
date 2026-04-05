"""MCP client: connect to MCP servers and register their tools."""

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from kaori_agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""
    name: str
    command: str
    args: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None


class MCPTool(BaseTool):
    """A BaseTool wrapper around an MCP tool.

    Routes execute() calls through the MCP client session.
    """

    def __init__(self, name: str, description: str, input_schema: dict, session: ClientSession):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self._session = session

    async def execute(self, **kwargs) -> ToolResult:
        try:
            result = await self._session.call_tool(self.name, arguments=kwargs)
            # MCP tool results have .content (list of content blocks)
            texts = []
            for block in result.content:
                if hasattr(block, "text"):
                    texts.append(block.text)
            output = "\n".join(texts) if texts else "(no output)"
            is_error = result.isError if hasattr(result, "isError") else False
            return ToolResult(output=output, is_error=is_error)
        except Exception as e:
            return ToolResult(output=f"MCP tool error: {e}", is_error=True)


class MCPManager:
    """Manages connections to MCP servers and exposes their tools."""

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tools: list[MCPTool] = []

    async def connect(self, server_config: MCPServerConfig) -> list[MCPTool]:
        """Connect to an MCP server and return its tools as BaseTool instances."""
        env = dict(server_config.env) if server_config.env else None

        server_params = StdioServerParameters(
            command=server_config.command,
            args=server_config.args,
            cwd=server_config.cwd,
            env=env,
        )

        try:
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{server_config.name}': {e}")
            return []

        self._sessions[server_config.name] = session

        # Discover tools
        tools_result = await session.list_tools()
        server_tools: list[MCPTool] = []
        for tool_def in tools_result.tools:
            mcp_tool = MCPTool(
                name=tool_def.name,
                description=tool_def.description or "",
                input_schema=tool_def.inputSchema if hasattr(tool_def, "inputSchema") else {},
                session=session,
            )
            server_tools.append(mcp_tool)

        self._tools.extend(server_tools)
        logger.info(
            f"Connected to MCP server '{server_config.name}': "
            f"{len(server_tools)} tools"
        )
        return server_tools

    def get_all_tools(self) -> list[MCPTool]:
        return list(self._tools)

    async def close(self):
        """Shut down all MCP server connections."""
        await self._exit_stack.aclose()
