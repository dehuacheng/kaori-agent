"""Tests for the agentic engine loop."""

import pytest

from kaori_agent.engine import run_turn, run_turn_stream
from kaori_agent.llm.base import LLMBackend, StreamEvent, ToolCall, TurnResult
from kaori_agent.tools.base import BaseTool, ToolResult


# --- Mock backend ---

class MockBackend(LLMBackend):
    """Backend that returns pre-configured responses."""

    def __init__(self, responses: list[TurnResult], stream_sequences: list[list[StreamEvent]] | None = None):
        self._responses = list(responses)
        self._call_count = 0
        # stream_sequences: list of event sequences, one per chat_stream call
        self._stream_sequences = list(stream_sequences) if stream_sequences else []
        self._stream_call_count = 0

    async def chat(self, messages, tool_schemas, system, model, max_tokens):
        result = self._responses[self._call_count]
        self._call_count += 1
        return result

    async def chat_stream(self, messages, tool_schemas, system, model, max_tokens):
        events = self._stream_sequences[self._stream_call_count]
        self._stream_call_count += 1
        for event in events:
            yield event

    def format_tool_schemas(self, tools):
        return [{"name": t.name} for t in tools]

    def make_assistant_message(self, result):
        return {"role": "assistant", "content": result.text, "_tool_calls": result.tool_calls}

    def make_tool_results(self, tool_calls, results):
        return [
            {"role": "tool", "tool_call_id": tc.id, "content": r.output}
            for tc, r in zip(tool_calls, results)
        ]


# --- Mock tool ---

class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes input."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    async def execute(self, text: str = "") -> ToolResult:
        return ToolResult(output=f"echo: {text}")


class FailTool(BaseTool):
    name = "fail"
    description = "Always fails."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        raise RuntimeError("intentional failure")


# --- Tests ---

class TestRunTurn:
    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        """No tools, single API call returns text."""
        backend = MockBackend([
            TurnResult(text="Hello!", stop_reason="end_turn"),
        ])
        messages = []
        result = await run_turn(backend, messages, [], "system", "model", 1000)
        assert result == "Hello!"
        assert len(messages) == 1  # assistant message appended

    @pytest.mark.asyncio
    async def test_tool_use_loop(self):
        """Model calls a tool, gets result, then responds."""
        backend = MockBackend([
            TurnResult(
                text="",
                tool_calls=[ToolCall(id="tc_1", name="echo", input={"text": "hi"})],
                stop_reason="tool_use",
            ),
            TurnResult(text="The tool said: echo: hi", stop_reason="end_turn"),
        ])
        messages = []
        result = await run_turn(backend, messages, [EchoTool()], "system", "model", 1000)
        assert "echo: hi" in result
        # messages: assistant (tool_use) + tool_result + assistant (final)
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Model calls a tool that doesn't exist."""
        backend = MockBackend([
            TurnResult(
                text="",
                tool_calls=[ToolCall(id="tc_1", name="nonexistent", input={})],
                stop_reason="tool_use",
            ),
            TurnResult(text="Sorry, that tool failed.", stop_reason="end_turn"),
        ])
        messages = []
        result = await run_turn(backend, messages, [EchoTool()], "system", "model", 1000)
        # Should not crash, error fed back to model
        assert result == "Sorry, that tool failed."

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        """Tool raises an exception."""
        backend = MockBackend([
            TurnResult(
                text="",
                tool_calls=[ToolCall(id="tc_1", name="fail", input={})],
                stop_reason="tool_use",
            ),
            TurnResult(text="Tool failed, sorry.", stop_reason="end_turn"),
        ])
        messages = []
        result = await run_turn(backend, messages, [FailTool()], "system", "model", 1000)
        assert result == "Tool failed, sorry."

    @pytest.mark.asyncio
    async def test_empty_tools_phase0(self):
        """With no tools, behaves like Phase 0 (single call)."""
        backend = MockBackend([
            TurnResult(text="Just chatting.", stop_reason="end_turn"),
        ])
        messages = []
        result = await run_turn(backend, messages, [], "system", "model", 1000)
        assert result == "Just chatting."
        assert backend._call_count == 1

    @pytest.mark.asyncio
    async def test_max_tokens_stops(self):
        """max_tokens stop reason returns partial text."""
        backend = MockBackend([
            TurnResult(text="Partial...", stop_reason="max_tokens"),
        ])
        messages = []
        result = await run_turn(backend, messages, [], "system", "model", 100)
        assert result == "Partial..."


# --- Helpers for collecting stream events ---

async def collect_events(gen) -> list[StreamEvent]:
    """Collect all events from an async generator."""
    events = []
    async for event in gen:
        events.append(event)
    return events


# --- Streaming engine tests ---

class TestRunTurnStream:
    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        """No tools, yields text events only (no turn_complete forwarded)."""
        final_result = TurnResult(text="Hello world!", stop_reason="end_turn")
        stream_events = [
            StreamEvent(type="text", text="Hello "),
            StreamEvent(type="text", text="world!"),
            StreamEvent(type="turn_complete", result=final_result),
        ]
        backend = MockBackend([], stream_sequences=[stream_events])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [], "system", "model", 1000)
        )
        # Should yield the two text events (turn_complete is consumed, not yielded)
        assert len(events) == 2
        assert all(e.type == "text" for e in events)
        assert events[0].text == "Hello "
        assert events[1].text == "world!"
        # messages should have the assistant message appended
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_thinking_then_text(self):
        """Yields thinking events then text events."""
        final_result = TurnResult(text="The answer is 42.", stop_reason="end_turn")
        stream_events = [
            StreamEvent(type="thinking", text="Let me think..."),
            StreamEvent(type="thinking", text=" about this."),
            StreamEvent(type="text", text="The answer is 42."),
            StreamEvent(type="turn_complete", result=final_result),
        ]
        backend = MockBackend([], stream_sequences=[stream_events])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [], "system", "model", 1000)
        )
        assert len(events) == 3
        assert events[0].type == "thinking"
        assert events[0].text == "Let me think..."
        assert events[1].type == "thinking"
        assert events[1].text == " about this."
        assert events[2].type == "text"
        assert events[2].text == "The answer is 42."

    @pytest.mark.asyncio
    async def test_tool_use_loop(self):
        """Model calls a tool, gets result, then responds with text."""
        # First call: model wants to use a tool
        tool_call = ToolCall(id="tc_1", name="echo", input={"text": "hi"})
        first_result = TurnResult(
            text="",
            tool_calls=[tool_call],
            stop_reason="tool_use",
        )
        first_stream = [
            StreamEvent(type="thinking", text="I should echo."),
            StreamEvent(type="turn_complete", result=first_result),
        ]
        # Second call: model responds with final text
        second_result = TurnResult(text="Done: echo: hi", stop_reason="end_turn")
        second_stream = [
            StreamEvent(type="text", text="Done: echo: hi"),
            StreamEvent(type="turn_complete", result=second_result),
        ]
        backend = MockBackend([], stream_sequences=[first_stream, second_stream])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [EchoTool()], "system", "model", 1000)
        )
        # Expected events: thinking, tool_use, text
        types = [e.type for e in events]
        assert "thinking" in types
        assert "tool_use" in types
        assert "text" in types
        # The tool_use event should have the tool_call info
        tool_events = [e for e in events if e.type == "tool_use"]
        assert len(tool_events) == 1
        assert tool_events[0].tool_call.name == "echo"
        assert "echo" in tool_events[0].text
        # messages: assistant (tool_use) + tool_result + assistant (final)
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Unknown tool yields tool_use event and feeds error back."""
        tool_call = ToolCall(id="tc_1", name="nonexistent", input={})
        first_result = TurnResult(
            text="",
            tool_calls=[tool_call],
            stop_reason="tool_use",
        )
        first_stream = [
            StreamEvent(type="turn_complete", result=first_result),
        ]
        second_result = TurnResult(text="Sorry, that tool failed.", stop_reason="end_turn")
        second_stream = [
            StreamEvent(type="text", text="Sorry, that tool failed."),
            StreamEvent(type="turn_complete", result=second_result),
        ]
        backend = MockBackend([], stream_sequences=[first_stream, second_stream])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [EchoTool()], "system", "model", 1000)
        )
        # Should have tool_use event and text event
        tool_events = [e for e in events if e.type == "tool_use"]
        assert len(tool_events) == 1
        assert tool_events[0].tool_call.name == "nonexistent"
        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) == 1
        assert text_events[0].text == "Sorry, that tool failed."
        # Error message should be in the tool result message
        tool_result_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_result_msgs) == 1
        assert "Unknown tool" in tool_result_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_empty_tools_phase0(self):
        """With no tools, single streaming call, text events only."""
        final_result = TurnResult(text="Just chatting.", stop_reason="end_turn")
        stream_events = [
            StreamEvent(type="text", text="Just chatting."),
            StreamEvent(type="turn_complete", result=final_result),
        ]
        backend = MockBackend([], stream_sequences=[stream_events])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [], "system", "model", 1000)
        )
        assert len(events) == 1
        assert events[0].type == "text"
        assert events[0].text == "Just chatting."
        assert backend._stream_call_count == 1

    @pytest.mark.asyncio
    async def test_no_turn_complete_returns_gracefully(self):
        """If chat_stream yields no turn_complete, the generator stops."""
        stream_events = [
            StreamEvent(type="text", text="partial"),
        ]
        backend = MockBackend([], stream_sequences=[stream_events])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [], "system", "model", 1000)
        )
        assert len(events) == 1
        assert events[0].type == "text"
        # No messages appended since turn_result is None
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_tool_execution_error_stream(self):
        """Tool raises an exception during streaming loop."""
        tool_call = ToolCall(id="tc_1", name="fail", input={})
        first_result = TurnResult(
            text="",
            tool_calls=[tool_call],
            stop_reason="tool_use",
        )
        first_stream = [
            StreamEvent(type="turn_complete", result=first_result),
        ]
        second_result = TurnResult(text="Tool failed, sorry.", stop_reason="end_turn")
        second_stream = [
            StreamEvent(type="text", text="Tool failed, sorry."),
            StreamEvent(type="turn_complete", result=second_result),
        ]
        backend = MockBackend([], stream_sequences=[first_stream, second_stream])
        messages = []
        events = await collect_events(
            run_turn_stream(backend, messages, [FailTool()], "system", "model", 1000)
        )
        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) == 1
        assert text_events[0].text == "Tool failed, sorry."
        # Error should be fed back in messages
        tool_result_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_result_msgs) == 1
        assert "Tool execution error" in tool_result_msgs[0]["content"]
