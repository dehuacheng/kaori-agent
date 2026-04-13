"""Build the system prompt from persona + base instructions + context blocks.

The caller is responsible for resolving the persona (see persona.resolve_persona)
and for fetching memory/digests/feed; this module just assembles them.
"""

from __future__ import annotations

from datetime import datetime, timezone


_BASE_INSTRUCTIONS = """\
You are running in a chat environment with tool_use support.
Be concise and direct. Use the tools available to you when helpful."""


def _relative_when(timestamp_iso: str | None) -> str:
    """Turn an ISO timestamp into 'yesterday', '3 days ago', etc."""
    if not timestamp_iso:
        return ""
    try:
        ts = datetime.fromisoformat(timestamp_iso.replace(" ", "T"))
    except ValueError:
        return ""
    now = datetime.now()
    delta = now - ts
    days = delta.days
    if days < 0:
        return ""
    if days == 0:
        hours = delta.seconds // 3600
        if hours < 1:
            return "just now"
        if hours == 1:
            return "1 hour ago"
        return f"{hours} hours ago"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
    months = days // 30
    return "1 month ago" if months == 1 else f"{months} months ago"


def _render_session_digests(digests: dict) -> str:
    lines: list[str] = ["## Recent conversations"]
    recent = digests.get("recent") or []
    if recent:
        for r in recent:
            title = r.get("title") or "(untitled)"
            when = _relative_when(r.get("updated_at"))
            header = f"- **{title}**"
            if when:
                header += f" — {when}"
            lines.append(header)
            summary = (r.get("summary") or "").strip()
            if summary:
                lines.append(f"  {summary}")
    else:
        lines.append("(no prior sessions yet — this looks like your first chat)")

    older_count = digests.get("older_count") or 0
    older_titles = digests.get("older_titles") or []
    if older_count > 0:
        title_list = ", ".join(t for t in older_titles if t)
        if title_list:
            lines.append(
                f"\nBefore that, across {older_count} older conversation"
                f"{'s' if older_count != 1 else ''}, you've talked about: {title_list}."
            )
        else:
            lines.append(
                f"\nBefore that, you've had {older_count} older conversation"
                f"{'s' if older_count != 1 else ''} together."
            )
    return "\n".join(lines)


def build_system_prompt(
    persona_text: str,
    memory_entries: list[dict] | None = None,
    is_resumed: bool = False,
    session_digests: dict | None = None,
    feed_snapshot: str | None = None,
    base_instructions: str | None = None,
) -> str:
    """Assemble the full system prompt.

    Args:
        persona_text: The resolved persona (DB-active or file). If you want
            baseline behavior, pass the default from persona.resolve_persona.
        memory_entries: Rows from agent_memory — dicts with key, value.
        is_resumed: Whether this session is continuing prior messages.
        session_digests: Output of shape_session_digests(...) — or None.
        feed_snapshot: Output of render_feed_payload(...) — or None.
        base_instructions: Override the default base-instructions block.
    """
    parts: list[str] = []
    base = base_instructions or _BASE_INSTRUCTIONS
    if persona_text:
        parts.append(persona_text)
        parts.append("---")
        parts.append(base)
    else:
        parts.append(base)

    now = datetime.now()
    utc_now = datetime.now(timezone.utc)
    parts.append(
        f"Current date and time: {now.strftime('%Y-%m-%d %H:%M %A')} (local), "
        f"{utc_now.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    if session_digests:
        parts.append(_render_session_digests(session_digests))

    if feed_snapshot:
        parts.append(
            "## What's going on with you lately (today + yesterday)\n"
            + feed_snapshot.strip()
        )

    if memory_entries:
        lines = [f"- {e['key']}: {e['value']}" for e in memory_entries]
        parts.append(
            "## What I know about you\n"
            + "\n".join(lines)
            + "\n\n(Add to this list whenever you learn something new about me — "
            "save with `save_memory`, don't wait to be asked.)"
        )

    if is_resumed:
        parts.append(
            "## Session context\n"
            "This is a continuation of a previous conversation. "
            "The earlier messages are loaded from history."
        )

    return "\n\n".join(parts)
