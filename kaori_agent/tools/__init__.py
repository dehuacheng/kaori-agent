"""Tool implementations for kaori-agent."""

from __future__ import annotations

from kaori_agent.tools.base import BaseTool
from kaori_agent.tools.read_file import ReadFileTool
from kaori_agent.tools.search import GlobTool, GrepTool
from kaori_agent.tools.memory import (
    SaveMemoryTool, GetMemoryTool, ListSessionsTool, ReadSessionTool,
)


def get_default_tools(
    session_store=None,
    session_id: str | None = None,
) -> list[BaseTool]:
    """Return built-in tools. Memory/session tools are included if session_store is provided."""
    tools: list[BaseTool] = [ReadFileTool(), GlobTool(), GrepTool()]
    if session_store is not None:
        tools.append(SaveMemoryTool(session_store=session_store, session_id=session_id))
        tools.append(GetMemoryTool(session_store=session_store))
        tools.append(ListSessionsTool(session_store=session_store))
        tools.append(ReadSessionTool(session_store=session_store))
    return tools
