"""Tool implementations for kaori-agent."""

from kaori_agent.tools.base import BaseTool
from kaori_agent.tools.read_file import ReadFileTool
from kaori_agent.tools.search import GlobTool, GrepTool


def get_default_tools() -> list[BaseTool]:
    """Return all Phase 1 read-only tools."""
    return [ReadFileTool(), GlobTool(), GrepTool()]
