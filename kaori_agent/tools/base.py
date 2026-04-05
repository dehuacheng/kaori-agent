"""Base tool interface and result type."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Result from executing a tool."""
    output: str
    is_error: bool = False


class BaseTool(ABC):
    """Abstract base for all agent tools.

    Subclasses define name, description, input_schema and implement execute().
    The LLM backend translates these into provider-specific schemas.
    """
    name: str
    description: str
    input_schema: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Run the tool with the given arguments."""
        ...
