"""Tool implementations for kaori-agent."""

from __future__ import annotations

from kaori_agent.config import VaultConfig
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
    vault_config: VaultConfig | None = None,
) -> list[BaseTool]:
    """Return built-in tools. Memory/session tools are included if session_store is provided.

    Args:
        on_memory_save: Optional callback (key, value, category) -> None, passed to
            SaveMemoryTool so the CLI can surface a subtle indicator on each save.
        vault_config: When set and enabled, read_file/glob/grep are scoped to the
            vault root; glob/grep additionally soft-exclude vault_config.exclude_paths.
    """
    if vault_config and vault_config.enabled and vault_config.root:
        vault_root = vault_config.root
        excludes = vault_config.exclude_paths
    else:
        vault_root = None
        excludes = []

    tools: list[BaseTool] = [
        ReadFileTool(vault_root=vault_root),
        GlobTool(vault_root=vault_root, exclude_paths=excludes),
        GrepTool(vault_root=vault_root, exclude_paths=excludes),
        WebSearchTool(),
    ]
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
