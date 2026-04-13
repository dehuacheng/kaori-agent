"""Tool implementations for kaori-agent."""

from __future__ import annotations

from kaori_agent.tools.base import BaseTool
from kaori_agent.tools.read_file import ReadFileTool
from kaori_agent.tools.search import GlobTool, GrepTool
from kaori_agent.tools.web_search import WebSearchTool
from kaori_agent.tools.memory import (
    SaveMemoryTool, GetMemoryTool, ListSessionsTool, ReadSessionTool,
)


def get_default_tools(
    session_store=None,
    session_id: str | None = None,
    disabled_tools: list[str] | None = None,
    on_memory_save=None,
) -> list[BaseTool]:
    """Return built-in tools. Memory/session tools are included if session_store is provided.

    Args:
        on_memory_save: Optional callback (key, value, category) -> None, passed to
            SaveMemoryTool so the CLI can surface a subtle indicator on each save.
    """
    tools: list[BaseTool] = [ReadFileTool(), GlobTool(), GrepTool(), WebSearchTool()]
    if session_store is not None:
        tools.append(SaveMemoryTool(
            session_store=session_store,
            session_id=session_id,
            on_save=on_memory_save,
        ))
        tools.append(GetMemoryTool(session_store=session_store))
        tools.append(ListSessionsTool(session_store=session_store))
        tools.append(ReadSessionTool(session_store=session_store))
    if disabled_tools:
        disabled = set(disabled_tools)
        tools = [t for t in tools if t.name not in disabled]
    return tools
