"""System prompt builder — CLI-side thin wrapper around kaori_agent.prompt_kit.

Keeps the old `build_system_prompt(config, ...)` signature so existing CLI code
continues to work. The shared logic lives in `kaori_agent.prompt_kit`; both the
CLI and the kaori backend call through it. See docs/FRONTEND-PARITY.md.
"""

from __future__ import annotations

from kaori_agent.config import Config, _DEFAULT_SYSTEM_PROMPT
from kaori_agent.prompt_kit import build_system_prompt as _kit_build


def build_system_prompt(
    config: Config,
    memory_entries: list[dict] | None = None,
    is_resumed: bool = False,
    session_digests: dict | None = None,
    feed_snapshot: str | None = None,
    vault_routing: str | None = None,
) -> str:
    """Build the system prompt using config's persona, delegating assembly to prompt_kit.

    The CLI's persona resolution currently reads the personality file at
    config-load time; a custom `config.system_prompt` different from the default
    is treated as the active persona. In the backend, persona is fetched from
    the agent_prompts DB table with the file as fallback — see
    kaori_agent.prompt_kit.persona.resolve_persona.
    """
    user_prompt = config.system_prompt
    has_custom = user_prompt and user_prompt != _DEFAULT_SYSTEM_PROMPT
    persona = user_prompt if has_custom else ""

    return _kit_build(
        persona_text=persona,
        memory_entries=memory_entries,
        is_resumed=is_resumed,
        session_digests=session_digests,
        feed_snapshot=feed_snapshot,
        vault_routing=vault_routing,
    )
