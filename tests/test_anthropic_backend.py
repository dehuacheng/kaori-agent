"""Tests for Anthropic backend format translation and fallback streaming."""

import pytest

from kaori_agent.llm.base import ToolCall, TurnResult
from kaori_agent.llm.anthropic_backend import AnthropicBackend
from kaori_agent.tools.base import BaseTool, ToolResult


class DummyTool(BaseTool):
    name = "search"
    description = "Search for something."
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, query: str = "") -> ToolResult:
        return ToolResult(output=query)


class DummyTool2(BaseTool):
    name = "calculator"
    description = "Do math."
    input_schema = {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    }

    async def execute(self, expression: str = "") -> ToolResult:
        return ToolResult(output=expression)


# --- Format tool schemas ---

class TestFormatToolSchemas:
    def test_anthropic_format_uses_input_schema(self):
        """Anthropic format uses 'input_schema' not 'parameters'."""
        backend = AnthropicBackend.__new__(AnthropicBackend)
        schemas = backend.format_tool_schemas([DummyTool()])

        assert len(schemas) == 1
        s = schemas[0]
        assert "input_schema" in s
        assert "parameters" not in s
        assert s["name"] == "search"
        assert s["description"] == "Search for something."
        assert s["input_schema"]["type"] == "object"
        assert "query" in s["input_schema"]["properties"]

    def test_multiple_tools(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        schemas = backend.format_tool_schemas([DummyTool(), DummyTool2()])

        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"search", "calculator"}

    def test_no_type_field(self):
        """Anthropic schemas should NOT have a top-level 'type' field (unlike OpenAI)."""
        backend = AnthropicBackend.__new__(AnthropicBackend)
        schemas = backend.format_tool_schemas([DummyTool()])

        s = schemas[0]
        assert "type" not in s


# --- Make assistant message ---

class TestMakeAssistantMessage:
    def test_text_only(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        result = TurnResult(text="Hello", stop_reason="end_turn")
        msg = backend.make_assistant_message(result)

        assert msg["role"] == "assistant"
        assert len(msg["content"]) == 1
        assert msg["content"][0] == {"type": "text", "text": "Hello"}

    def test_with_tool_calls(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        result = TurnResult(
            text="Let me search.",
            tool_calls=[ToolCall(id="tu_1", name="search", input={"query": "test"})],
            stop_reason="tool_use",
        )
        msg = backend.make_assistant_message(result)

        assert msg["role"] == "assistant"
        assert len(msg["content"]) == 2
        # First block: text
        assert msg["content"][0] == {"type": "text", "text": "Let me search."}
        # Second block: tool_use
        tc_block = msg["content"][1]
        assert tc_block["type"] == "tool_use"
        assert tc_block["id"] == "tu_1"
        assert tc_block["name"] == "search"
        assert tc_block["input"] == {"query": "test"}

    def test_tool_calls_no_text(self):
        """Tool calls with empty text produce only tool_use blocks."""
        backend = AnthropicBackend.__new__(AnthropicBackend)
        result = TurnResult(
            text="",
            tool_calls=[ToolCall(id="tu_1", name="search", input={"query": "q"})],
            stop_reason="tool_use",
        )
        msg = backend.make_assistant_message(result)

        assert msg["role"] == "assistant"
        # No text block since text is empty
        assert len(msg["content"]) == 1
        assert msg["content"][0]["type"] == "tool_use"

    def test_multiple_tool_calls(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        result = TurnResult(
            text="Doing both.",
            tool_calls=[
                ToolCall(id="tu_1", name="search", input={"query": "a"}),
                ToolCall(id="tu_2", name="calculator", input={"expression": "1+1"}),
            ],
            stop_reason="tool_use",
        )
        msg = backend.make_assistant_message(result)

        # text + 2 tool_use blocks
        assert len(msg["content"]) == 3
        assert msg["content"][1]["name"] == "search"
        assert msg["content"][2]["name"] == "calculator"


# --- Make tool results ---

class TestMakeToolResults:
    def test_single_user_message(self):
        """Anthropic returns a single user message with tool_result blocks."""
        backend = AnthropicBackend.__new__(AnthropicBackend)
        calls = [ToolCall(id="tu_1", name="search", input={"query": "test"})]
        results = [ToolResult(output="found it")]

        msgs = backend.make_tool_results(calls, results)

        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        blocks = msgs[0]["content"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_result"
        assert blocks[0]["tool_use_id"] == "tu_1"
        assert blocks[0]["content"] == "found it"
        assert "is_error" not in blocks[0]

    def test_error_result(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        calls = [ToolCall(id="tu_1", name="search", input={})]
        results = [ToolResult(output="something broke", is_error=True)]

        msgs = backend.make_tool_results(calls, results)

        block = msgs[0]["content"][0]
        assert block["is_error"] is True
        assert block["content"].startswith("Error:")

    def test_multiple_results_in_one_message(self):
        """Multiple tool results go into the same user message."""
        backend = AnthropicBackend.__new__(AnthropicBackend)
        calls = [
            ToolCall(id="tu_1", name="search", input={}),
            ToolCall(id="tu_2", name="calculator", input={}),
        ]
        results = [
            ToolResult(output="result1"),
            ToolResult(output="result2"),
        ]

        msgs = backend.make_tool_results(calls, results)

        # One message, two blocks
        assert len(msgs) == 1
        blocks = msgs[0]["content"]
        assert len(blocks) == 2
        assert blocks[0]["tool_use_id"] == "tu_1"
        assert blocks[1]["tool_use_id"] == "tu_2"

    def test_mixed_success_and_error(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        calls = [
            ToolCall(id="tu_1", name="search", input={}),
            ToolCall(id="tu_2", name="calculator", input={}),
        ]
        results = [
            ToolResult(output="good"),
            ToolResult(output="bad", is_error=True),
        ]

        msgs = backend.make_tool_results(calls, results)

        blocks = msgs[0]["content"]
        assert "is_error" not in blocks[0]
        assert blocks[0]["content"] == "good"
        assert blocks[1]["is_error"] is True
        assert blocks[1]["content"].startswith("Error:")


# --- Default chat_stream fallback ---

class TestDefaultChatStreamFallback:
    """AnthropicBackend doesn't override chat_stream, so it uses the base class fallback."""

    @pytest.mark.asyncio
    async def test_fallback_yields_text_then_turn_complete(self):
        """Default chat_stream calls chat() and yields text + turn_complete."""
        backend = AnthropicBackend.__new__(AnthropicBackend)

        # Mock the chat() method to return a known TurnResult
        chat_result = TurnResult(text="Hello from Anthropic!", stop_reason="end_turn")

        async def mock_chat(messages, tool_schemas, system, model, max_tokens):
            return chat_result

        backend.chat = mock_chat

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert len(events) == 2
        assert events[0].type == "text"
        assert events[0].text == "Hello from Anthropic!"
        assert events[1].type == "turn_complete"
        assert events[1].result is chat_result

    @pytest.mark.asyncio
    async def test_fallback_empty_text_skips_text_event(self):
        """When chat() returns empty text, no text event is yielded."""
        backend = AnthropicBackend.__new__(AnthropicBackend)

        chat_result = TurnResult(
            text="",
            tool_calls=[ToolCall(id="tu_1", name="search", input={"query": "x"})],
            stop_reason="tool_use",
        )

        async def mock_chat(messages, tool_schemas, system, model, max_tokens):
            return chat_result

        backend.chat = mock_chat

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        # Only turn_complete, no text event since text is empty
        assert len(events) == 1
        assert events[0].type == "turn_complete"
        assert events[0].result.stop_reason == "tool_use"
        assert len(events[0].result.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_fallback_with_tool_calls_has_correct_result(self):
        """Fallback preserves tool calls in the turn_complete result."""
        backend = AnthropicBackend.__new__(AnthropicBackend)

        tc = ToolCall(id="tu_1", name="search", input={"query": "test"})
        chat_result = TurnResult(
            text="Searching...",
            tool_calls=[tc],
            stop_reason="tool_use",
        )

        async def mock_chat(messages, tool_schemas, system, model, max_tokens):
            return chat_result

        backend.chat = mock_chat

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert len(events) == 2
        assert events[0].type == "text"
        assert events[0].text == "Searching..."
        assert events[1].type == "turn_complete"
        assert events[1].result.tool_calls == [tc]
