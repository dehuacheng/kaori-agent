"""LLM backend abstraction: provider-agnostic types and ABC."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """Raised when an LLM backend encounters an error."""


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class TurnResult:
    """Provider-agnostic result from a single LLM API call."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    raw: Any = None  # provider-specific response for message history


@dataclass
class StreamEvent:
    """A single streaming event from the LLM."""
    type: str  # "thinking" | "text" | "tool_use" | "turn_complete"
    text: str = ""
    tool_call: ToolCall | None = None
    result: TurnResult | None = None  # only on "turn_complete"


class LLMBackend(ABC):
    """Abstract interface for LLM chat with tool support.

    Each backend translates between provider-specific formats and
    the universal TurnResult / ToolCall types. The engine loop is
    backend-agnostic — it only touches these types.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list,
        tool_schemas: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> TurnResult:
        """Send messages + tool schemas to the LLM, return a TurnResult."""
        ...

    async def chat_stream(
        self,
        messages: list,
        tool_schemas: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream events from the LLM. Last event is always turn_complete.

        Default implementation falls back to non-streaming chat().
        """
        result = await self.chat(messages, tool_schemas, system, model, max_tokens)
        if result.text:
            yield StreamEvent(type="text", text=result.text)
        yield StreamEvent(type="turn_complete", result=result)

    @abstractmethod
    def format_tool_schemas(self, tools: list) -> list[dict]:
        """Convert BaseTool instances to provider-specific tool schema dicts."""
        ...

    @abstractmethod
    def make_assistant_message(self, result: TurnResult) -> Any:
        """Create a provider-formatted assistant message from a TurnResult."""
        ...

    @abstractmethod
    def make_tool_results(
        self,
        tool_calls: list[ToolCall],
        results: list,  # list[ToolResult]
    ) -> list:
        """Create provider-formatted tool result message(s)."""
        ...
