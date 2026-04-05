"""Anthropic backend using the native anthropic SDK."""

from anthropic import AsyncAnthropic

from kaori_agent.llm.base import LLMBackend, LLMError, ToolCall, TurnResult


class AnthropicBackend(LLMBackend):
    """LLM backend using the Anthropic Python SDK."""

    def __init__(self, api_key: str):
        self._client = AsyncAnthropic(api_key=api_key)

    async def chat(
        self,
        messages: list,
        tool_schemas: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> TurnResult:
        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas

        try:
            response = await self._client.messages.create(**kwargs)
        except Exception as e:
            raise LLMError(f"Anthropic API error: {e}") from e

        # Extract text and tool calls from content blocks
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        if response.stop_reason == "tool_use":
            stop_reason = "tool_use"
        elif response.stop_reason == "max_tokens":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        return TurnResult(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=response.content,
        )

    def format_tool_schemas(self, tools: list) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    def make_assistant_message(self, result: TurnResult) -> dict:
        # Reconstruct Anthropic content blocks from TurnResult
        content: list[dict] = []
        if result.text:
            content.append({"type": "text", "text": result.text})
        for tc in result.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        return {"role": "assistant", "content": content}

    def make_tool_results(
        self,
        tool_calls: list[ToolCall],
        results: list,
    ) -> list[dict]:
        # Anthropic: single user message with all tool_result blocks
        tool_result_blocks = []
        for tc, r in zip(tool_calls, results):
            content = r.output if not r.is_error else f"Error: {r.output}"
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": content,
                **({"is_error": True} if r.is_error else {}),
            })
        return [{"role": "user", "content": tool_result_blocks}]
