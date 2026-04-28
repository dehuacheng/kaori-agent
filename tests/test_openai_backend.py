"""Tests for OpenAI backend format translation and streaming (no real API calls)."""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from kaori_agent.llm.base import ToolCall, TurnResult
from kaori_agent.llm.openai_backend import OpenAIBackend
from kaori_agent.tools.base import BaseTool, ToolResult


class DummyTool(BaseTool):
    name = "test_tool"
    description = "A test tool."
    input_schema = {
        "type": "object",
        "properties": {"arg": {"type": "string"}},
        "required": ["arg"],
    }

    async def execute(self, arg: str = "") -> ToolResult:
        return ToolResult(output=arg)


class TestFormatToolSchemas:
    def test_openai_format(self):
        # Can't construct OpenAIBackend without hitting the API,
        # so test the class method directly via a subclass trick
        backend = OpenAIBackend.__new__(OpenAIBackend)
        schemas = backend.format_tool_schemas([DummyTool()])

        assert len(schemas) == 1
        s = schemas[0]
        assert s["type"] == "function"
        assert s["function"]["name"] == "test_tool"
        assert s["function"]["parameters"]["type"] == "object"


class TestMakeAssistantMessage:
    def test_text_only(self):
        backend = OpenAIBackend.__new__(OpenAIBackend)
        result = TurnResult(text="Hello", stop_reason="end_turn")
        msg = backend.make_assistant_message(result)
        assert msg["role"] == "assistant"
        assert msg["content"] == "Hello"
        assert "reasoning_content" not in msg  # not added when empty

    def test_with_tool_calls(self):
        backend = OpenAIBackend.__new__(OpenAIBackend)
        result = TurnResult(
            text="",
            tool_calls=[ToolCall(id="tc1", name="test", input={"a": 1})],
            stop_reason="tool_use",
        )
        msg = backend.make_assistant_message(result)
        assert msg["role"] == "assistant"
        assert msg["content"] is None  # must be null, not missing
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["id"] == "tc1"
        assert tc["type"] == "function"
        assert json.loads(tc["function"]["arguments"]) == {"a": 1}

    def test_with_reasoning_content(self):
        """reasoning_content from deepseek thinking-mode must be echoed back so
        the next request doesn't 400 with 'reasoning_content must be passed back'."""
        backend = OpenAIBackend.__new__(OpenAIBackend)
        result = TurnResult(
            text="I'll search.",
            tool_calls=[ToolCall(id="tc1", name="search", input={"q": "x"})],
            stop_reason="tool_use",
            reasoning_content="Let me think through this carefully...",
        )
        msg = backend.make_assistant_message(result)
        assert msg["reasoning_content"] == "Let me think through this carefully..."
        assert msg["content"] == "I'll search."
        assert len(msg["tool_calls"]) == 1


class TestMakeToolResults:
    def test_one_per_call(self):
        backend = OpenAIBackend.__new__(OpenAIBackend)
        calls = [
            ToolCall(id="tc1", name="a", input={}),
            ToolCall(id="tc2", name="b", input={}),
        ]
        results = [
            ToolResult(output="result1"),
            ToolResult(output="oops", is_error=True),
        ]
        msgs = backend.make_tool_results(calls, results)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "tc1"
        assert msgs[0]["content"] == "result1"
        assert msgs[1]["content"].startswith("Error:")


# --- Mock objects for streaming tests ---

@dataclass
class MockFunction:
    name: str | None = None
    arguments: str | None = None


@dataclass
class MockToolCallDelta:
    index: int
    id: str | None = None
    function: MockFunction | None = None


@dataclass
class MockDelta:
    content: str | None = None
    tool_calls: list[MockToolCallDelta] | None = None
    reasoning_content: str | None = None
    model_extra: dict | None = None


@dataclass
class MockChoice:
    delta: MockDelta
    finish_reason: str | None = None


@dataclass
class MockChunk:
    choices: list[MockChoice] = field(default_factory=list)


async def mock_stream_from_chunks(chunks: list[MockChunk]):
    """Create an async iterable from a list of MockChunks."""
    for chunk in chunks:
        yield chunk


class TestChatStream:
    """Tests for OpenAI backend chat_stream accumulation logic."""

    @pytest.mark.asyncio
    async def test_text_only_stream(self):
        """Text deltas accumulate into a text TurnResult."""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Hello "))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(content="world!"))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="stop")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend._client = None  # not used directly
        backend.name = "test"

        # Monkey-patch the client call to return our mock stream
        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        # We need to patch at the right level. chat_stream calls
        # self._client.chat.completions.create(), so we build a chain.
        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        # Should have: text, text, turn_complete
        assert len(events) == 3
        assert events[0].type == "text"
        assert events[0].text == "Hello "
        assert events[1].type == "text"
        assert events[1].text == "world!"
        assert events[2].type == "turn_complete"
        assert events[2].result.text == "Hello world!"
        assert events[2].result.stop_reason == "end_turn"
        assert events[2].result.tool_calls == []

    @pytest.mark.asyncio
    async def test_reasoning_content_stream(self):
        """reasoning_content deltas yield thinking events."""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockDelta(reasoning_content="Thinking..."))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(reasoning_content=" deeper."))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Answer."))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="stop")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert events[0].type == "thinking"
        assert events[0].text == "Thinking..."
        assert events[1].type == "thinking"
        assert events[1].text == " deeper."
        assert events[2].type == "text"
        assert events[2].text == "Answer."
        assert events[3].type == "turn_complete"
        assert events[3].result.text == "Answer."
        # Reasoning must accumulate into the TurnResult so the next assistant
        # message can echo it back to deepseek thinking-mode.
        assert events[3].result.reasoning_content == "Thinking... deeper."

    @pytest.mark.asyncio
    async def test_reasoning_via_model_extra(self):
        """reasoning_content accessed via model_extra fallback."""
        # Simulate delta without direct reasoning_content attribute
        delta = MockDelta()
        delta.reasoning_content = None
        delta.model_extra = {"reasoning_content": "thinking via extra"}

        chunks = [
            MockChunk(choices=[MockChoice(delta=delta)]),
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Done."), finish_reason="stop")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert events[0].type == "thinking"
        assert events[0].text == "thinking via extra"

    @pytest.mark.asyncio
    async def test_tool_call_accumulation(self):
        """Fragmented tool call deltas accumulate into complete ToolCalls."""
        chunks = [
            # First chunk: tool call id and name
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=0,
                    id="call_123",
                    function=MockFunction(name="test_tool", arguments='{"ar'),
                )]
            ))]),
            # Second chunk: rest of arguments
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=0,
                    function=MockFunction(arguments='g": "hello"}'),
                )]
            ))]),
            # Finish
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="tool_calls")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        # Only event should be turn_complete (no text events)
        assert len(events) == 1
        assert events[0].type == "turn_complete"
        result = events[0].result
        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_123"
        assert tc.name == "test_tool"
        assert tc.input == {"arg": "hello"}

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        """Multiple tool calls accumulated by index."""
        chunks = [
            # Tool 0 starts
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=0,
                    id="call_a",
                    function=MockFunction(name="tool_a", arguments='{}'),
                )]
            ))]),
            # Tool 1 starts
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=1,
                    id="call_b",
                    function=MockFunction(name="tool_b", arguments='{"x"'),
                )]
            ))]),
            # Tool 1 more arguments
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=1,
                    function=MockFunction(arguments=': 1}'),
                )]
            ))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="tool_calls")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert events[0].type == "turn_complete"
        result = events[0].result
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].id == "call_a"
        assert result.tool_calls[0].name == "tool_a"
        assert result.tool_calls[0].input == {}
        assert result.tool_calls[1].id == "call_b"
        assert result.tool_calls[1].name == "tool_b"
        assert result.tool_calls[1].input == {"x": 1}

    @pytest.mark.asyncio
    async def test_text_with_tool_calls(self):
        """Text content followed by tool calls."""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Let me check."))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=0,
                    id="call_1",
                    function=MockFunction(name="echo", arguments='{"text": "hi"}'),
                )]
            ))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="tool_calls")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert events[0].type == "text"
        assert events[0].text == "Let me check."
        assert events[1].type == "turn_complete"
        assert events[1].result.text == "Let me check."
        assert events[1].result.stop_reason == "tool_use"
        assert len(events[1].result.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_empty_choices_chunk(self):
        """Chunks with empty choices are skipped."""
        chunks = [
            MockChunk(choices=[]),  # empty, should be skipped
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Hi"))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="stop")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert len(events) == 2
        assert events[0].type == "text"
        assert events[0].text == "Hi"
        assert events[1].type == "turn_complete"

    @pytest.mark.asyncio
    async def test_malformed_tool_args_fallback(self):
        """Malformed JSON in tool arguments falls back to _raw."""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCallDelta(
                    index=0,
                    id="call_bad",
                    function=MockFunction(name="broken", arguments="not json"),
                )]
            ))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="tool_calls")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        result = events[0].result
        assert result.tool_calls[0].input == {"_raw": "not json"}

    @pytest.mark.asyncio
    async def test_max_tokens_finish_reason(self):
        """finish_reason 'length' maps to stop_reason 'max_tokens'."""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Partial"))]),
            MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="length")]),
        ]

        backend = OpenAIBackend.__new__(OpenAIBackend)
        backend.name = "test"

        async def mock_create(**kwargs):
            return mock_stream_from_chunks(chunks)

        class MockCompletions:
            create = staticmethod(mock_create)
        class MockChat:
            completions = MockCompletions()
        class MockClient:
            chat = MockChat()

        backend._client = MockClient()

        events = []
        async for event in backend.chat_stream([], [], "sys", "model", 1000):
            events.append(event)

        assert events[-1].type == "turn_complete"
        assert events[-1].result.stop_reason == "max_tokens"
