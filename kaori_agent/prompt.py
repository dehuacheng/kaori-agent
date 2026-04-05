"""System prompt builder."""

from __future__ import annotations

from kaori_agent.config import Config, _DEFAULT_SYSTEM_PROMPT

_BASE_INSTRUCTIONS = """\
You are a helpful personal assistant running in a terminal.
You have access to tools for reading files and searching codebases.
Be concise and direct."""


def build_system_prompt(
    config: Config,
    memory_entries: list[dict] | None = None,
    is_resumed: bool = False,
) -> str:
    """Build the system prompt from config, memory, and session context.

    If the user has set a custom system_prompt (via YAML or personality file),
    it is placed first, followed by the base operational instructions.
    If no custom prompt, just use the base instructions.
    Memory entries and session context are appended after.
    """
    user_prompt = config.system_prompt
    has_custom = user_prompt and user_prompt != _DEFAULT_SYSTEM_PROMPT

    if has_custom:
        parts = [user_prompt, "---", _BASE_INSTRUCTIONS]
    else:
        parts = [_BASE_INSTRUCTIONS]

    # Inject persistent memory
    if memory_entries:
        lines = [f"- {e['key']}: {e['value']}" for e in memory_entries]
        parts.append(
            "## Things I remember about you\n" + "\n".join(lines)
        )

    # Note if this is a resumed session
    if is_resumed:
        parts.append(
            "## Session context\n"
            "This is a continuation of a previous conversation. "
            "The earlier messages are loaded from history."
        )

    return "\n\n".join(parts)
