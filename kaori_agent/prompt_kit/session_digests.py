"""Shape raw session rows into a digest dict consumed by build_system_prompt.

Pure function — the caller fetches sessions from its own store (CLI's
SessionStore or the backend's agent_session_repo) and passes the rows in.
"""

from __future__ import annotations


def shape_session_digests(
    sessions: list[dict],
    current_session_id: str | None = None,
    max_recent: int = 3,
    max_older_titles: int = 8,
    min_messages: int = 2,
) -> dict | None:
    """Turn session rows into the digest dict that build_system_prompt expects.

    Args:
        sessions: List of dicts as returned by SessionStore.list_sessions or
            agent_session_repo.list_all. Each should have at least: id, title,
            message_count, updated_at, summary (optional).
        current_session_id: If set, rows with this id are excluded (so the
            active chat doesn't digest itself).
        max_recent: How many sessions get a full summary block.
        max_older_titles: Cap on titles shown in the "older" roll-up.
        min_messages: Drop sessions with fewer messages than this (skeleton
            / empty sessions aren't worth recalling).

    Returns:
        A dict with keys `recent` (list of {title, summary, updated_at}),
        `older_count`, and `older_titles`. Returns None if there are no
        qualifying sessions.
    """
    filtered = [
        s for s in sessions
        if s.get("id") != current_session_id
        and (s.get("message_count") or 0) >= min_messages
    ]
    if not filtered:
        return None

    recent = filtered[:max_recent]
    older = filtered[max_recent:]

    recent_items = [
        {
            "title": s.get("title"),
            "summary": s.get("summary") or "(no summary yet)",
            "updated_at": s.get("updated_at"),
        }
        for s in recent
    ]
    older_titles = [s.get("title") for s in older if s.get("title")][:max_older_titles]
    return {
        "recent": recent_items,
        "older_count": len(older),
        "older_titles": older_titles,
    }
