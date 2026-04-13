"""Generate a friend-style 3-5 sentence summary of a session transcript.

Pure generator — persistence is the caller's job (CLI persists via Session's
SessionStore, backend persists via agent_session_repo.update_summary).
"""

from __future__ import annotations


_SUMMARY_SYSTEM_PROMPT = (
    "You produce short, warm, friend-style summaries of conversations. "
    "Plain prose, 3-5 sentences, no headers or bullets."
)

_SUMMARY_USER_PROMPT_TEMPLATE = (
    "Summarize the following conversation as if you were telling a friend "
    "what you two talked about, in 3-5 sentences. Warm and natural, not a "
    "bullet list. Include: what the user was thinking about or working on, "
    "how they seemed, and any open threads or things they mentioned wanting "
    "to do. Mirror the user's language (English or Chinese). "
    "Do not start with 'In this conversation' — just tell the story.\n\n"
    "{transcript}"
)


def _messages_to_transcript(messages: list) -> str:
    """Flatten a list of backend-agnostic message dicts into plain text."""
    parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"{role}: {content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(f"{role}: {block.get('text', '')}")
    return "\n".join(parts)


async def generate_session_summary(
    backend,
    model: str,
    messages: list,
    max_tokens: int = 1024,
    min_user_messages: int = 2,
) -> str | None:
    """Ask the LLM for a friend-style session summary.

    Args:
        backend: Any LLM backend with an async `chat(messages, tools, system_prompt,
            model, max_tokens) -> TurnResult`-shaped method (the shape used by
            both kaori_agent.llm.base and kaori.llm.agent_backend). Either works.
        model: Model identifier to pass to the backend.
        messages: The session's messages (backend-agnostic dicts). Tool calls
            and non-text blocks are stripped by the renderer.
        max_tokens: Cap on the summary length.
        min_user_messages: Skip if fewer user turns than this — not enough to
            summarize.

    Returns:
        The summary text, or None if the session was too short, empty after
        flattening, or the LLM call failed.
    """
    user_count = sum(
        1 for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
    )
    if user_count < min_user_messages:
        return None

    transcript = _messages_to_transcript(messages)
    if not transcript.strip():
        return None

    prompt = _SUMMARY_USER_PROMPT_TEMPLATE.format(transcript=transcript)
    try:
        result = await backend.chat(
            [{"role": "user", "content": prompt}],
            [],
            _SUMMARY_SYSTEM_PROMPT,
            model,
            max_tokens,
        )
    except Exception:
        return None
    text = (getattr(result, "text", "") or "").strip()
    return text or None
