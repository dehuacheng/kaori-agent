"""OpenAI-compatible backend for DeepSeek, Kimi, OpenAI, and others."""

import json
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from kaori_agent.llm.base import LLMBackend, LLMError, StreamEvent, ToolCall, TurnResult


class OpenAIBackend(LLMBackend):
    """LLM backend using the OpenAI SDK (works with any compatible API)."""

    def __init__(self, api_key: str, base_url: str, name: str = "openai"):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.name = name

    async def chat(
        self,
        messages: list,
        tool_schemas: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> TurnResult:
        # Prepend system message if not already there
        full_messages = [{"role": "system", "content": system}] + messages

        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            messages=full_messages,
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as e:
            raise LLMError(f"{self.name} API error: {e}") from e

        choice = response.choices[0]
        message = choice.message

        # Extract text
        text = message.content or ""

        # Extract reasoning_content (DeepSeek thinking-mode / R1)
        reasoning = getattr(message, "reasoning_content", "") or ""
        if not reasoning and hasattr(message, "model_extra") and message.model_extra:
            reasoning = message.model_extra.get("reasoning_content", "") or ""

        # Extract tool calls
        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        # Determine stop reason
        if choice.finish_reason == "tool_calls" or tool_calls:
            stop_reason = "tool_use"
        elif choice.finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        return TurnResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=message,
            reasoning_content=reasoning,
        )

    async def chat_stream(
        self,
        messages: list,
        tool_schemas: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> AsyncGenerator[StreamEvent, None]:
        full_messages = [{"role": "system", "content": system}] + messages

        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            messages=full_messages,
            stream=True,
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"

        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except Exception as e:
            raise LLMError(f"{self.name} API error: {e}") from e

        # Accumulate full response while yielding deltas
        text_parts: list[str] = []
        reasoning_parts: list[str] = []  # accumulated for echo-back on next turn
        # tool_calls accumulator: index -> {id, name, arguments_parts}
        tc_accum: dict[int, dict] = {}
        finish_reason = None

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # Thinking / reasoning content (DeepSeek-R1, etc.)
            reasoning = getattr(delta, "reasoning_content", None)
            if not reasoning and hasattr(delta, "model_extra") and delta.model_extra:
                reasoning = delta.model_extra.get("reasoning_content")
            if reasoning:
                reasoning_parts.append(reasoning)
                yield StreamEvent(type="thinking", text=reasoning)

            # Regular text content
            if delta.content:
                text_parts.append(delta.content)
                yield StreamEvent(type="text", text=delta.content)

            # Tool call deltas
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tc_accum:
                        tc_accum[idx] = {"id": "", "name": "", "arguments": []}
                    if tc_delta.id:
                        tc_accum[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc_accum[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc_accum[idx]["arguments"].append(tc_delta.function.arguments)

            if choice.finish_reason:
                finish_reason = choice.finish_reason

        # Build final TurnResult
        text = "".join(text_parts)
        tool_calls: list[ToolCall] = []
        for idx in sorted(tc_accum):
            acc = tc_accum[idx]
            raw_args = "".join(acc["arguments"])
            try:
                args = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                args = {"_raw": raw_args}
            tool_calls.append(ToolCall(id=acc["id"], name=acc["name"], input=args))

        if finish_reason == "tool_calls" or tool_calls:
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        yield StreamEvent(
            type="turn_complete",
            result=TurnResult(
                text=text, tool_calls=tool_calls, stop_reason=stop_reason,
                reasoning_content="".join(reasoning_parts),
            ),
        )

    def format_tool_schemas(self, tools: list) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def make_assistant_message(self, result: TurnResult) -> dict:
        msg: dict = {"role": "assistant"}
        if result.text:
            msg["content"] = result.text
        if result.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input),
                    },
                }
                for tc in result.tool_calls
            ]
            # OpenAI requires content to be null (not missing) when tool_calls present
            if "content" not in msg:
                msg["content"] = None
        # DeepSeek thinking mode (deepseek-v4-pro) requires reasoning_content to
        # be echoed back on every subsequent request — without it the API 400s
        # with "The reasoning_content in the thinking mode must be passed back".
        # Other OpenAI-compat providers ignore unknown fields, so this is safe.
        # NOTE: keep in sync with kaori/llm/agent_backend.py:OpenAIAgentBackend
        # (parallel implementation for the kaori chat service backend ABC).
        if result.reasoning_content:
            msg["reasoning_content"] = result.reasoning_content
        return msg

    def make_tool_results(
        self,
        tool_calls: list[ToolCall],
        results: list,
    ) -> list[dict]:
        # OpenAI: one message per tool result
        return [
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": r.output if not r.is_error else f"Error: {r.output}",
            }
            for tc, r in zip(tool_calls, results)
        ]
