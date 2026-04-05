"""Core agentic turn loop — backend-agnostic."""

from collections.abc import AsyncGenerator

from kaori_agent.llm.base import LLMBackend, StreamEvent, ToolCall
from kaori_agent.tools.base import BaseTool, ToolResult


async def run_turn(
    backend: LLMBackend,
    messages: list,
    tools: list[BaseTool],
    system_prompt: str,
    model: str,
    max_tokens: int,
) -> str:
    """Run one agentic turn (non-streaming). Returns the final text response."""
    tool_schemas = backend.format_tool_schemas(tools) if tools else []
    tool_map = {t.name: t for t in tools}

    while True:
        result = await backend.chat(messages, tool_schemas, system_prompt, model, max_tokens)
        messages.append(backend.make_assistant_message(result))

        if result.stop_reason != "tool_use" or not result.tool_calls:
            return result.text

        tool_results = await _execute_tool_calls(result.tool_calls, tool_map)
        messages.extend(backend.make_tool_results(result.tool_calls, tool_results))


async def run_turn_stream(
    backend: LLMBackend,
    messages: list,
    tools: list[BaseTool],
    system_prompt: str,
    model: str,
    max_tokens: int,
) -> AsyncGenerator[StreamEvent, None]:
    """Run one agentic turn with streaming. Yields StreamEvents.

    Handles the tool loop internally — yields thinking/text/tool_use events,
    executes tools, and loops until the model produces a final text response.
    Mutates `messages` in-place.
    """
    tool_schemas = backend.format_tool_schemas(tools) if tools else []
    tool_map = {t.name: t for t in tools}

    while True:
        turn_result = None
        async for event in backend.chat_stream(messages, tool_schemas, system_prompt, model, max_tokens):
            if event.type == "turn_complete":
                turn_result = event.result
            else:
                yield event  # pass through thinking/text events to CLI

        if turn_result is None:
            return

        messages.append(backend.make_assistant_message(turn_result))

        if turn_result.stop_reason != "tool_use" or not turn_result.tool_calls:
            return

        # Execute tools and yield status events
        tool_results: list[ToolResult] = []
        for tc in turn_result.tool_calls:
            yield StreamEvent(type="tool_use", text=f"calling {tc.name}", tool_call=tc)
            tool = tool_map.get(tc.name)
            if tool is None:
                res = ToolResult(output=f"Unknown tool: {tc.name}", is_error=True)
            else:
                try:
                    res = await tool.execute(**tc.input)
                except Exception as e:
                    res = ToolResult(output=f"Tool execution error: {e}", is_error=True)
            tool_results.append(res)

        messages.extend(backend.make_tool_results(turn_result.tool_calls, tool_results))


async def _execute_tool_calls(
    tool_calls: list[ToolCall],
    tool_map: dict[str, BaseTool],
) -> list[ToolResult]:
    """Execute a list of tool calls, returning results in order."""
    results: list[ToolResult] = []
    for tc in tool_calls:
        tool = tool_map.get(tc.name)
        if tool is None:
            results.append(ToolResult(output=f"Unknown tool: {tc.name}", is_error=True))
            continue
        try:
            result = await tool.execute(**tc.input)
        except Exception as e:
            result = ToolResult(output=f"Tool execution error: {e}", is_error=True)
        results.append(result)
    return results
