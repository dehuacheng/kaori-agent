"""System prompt builder."""

from kaori_agent.config import Config, _DEFAULT_SYSTEM_PROMPT

_BASE_INSTRUCTIONS = """\
You are a helpful personal assistant running in a terminal.
You have access to tools for reading files and searching codebases.
Be concise and direct."""


def build_system_prompt(config: Config) -> str:
    """Build the system prompt from config.

    If the user has set a custom system_prompt (via YAML or personality file),
    it is placed first, followed by the base operational instructions.
    If no custom prompt, just use the base instructions.
    """
    user_prompt = config.system_prompt
    has_custom = user_prompt and user_prompt != _DEFAULT_SYSTEM_PROMPT

    if has_custom:
        return f"{user_prompt}\n\n---\n\n{_BASE_INSTRUCTIONS}"
    return _BASE_INSTRUCTIONS
