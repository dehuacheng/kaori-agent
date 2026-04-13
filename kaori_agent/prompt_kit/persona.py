"""Persona resolution: DB-active prompt > file fallback > default.

Both the CLI and the kaori backend call this so there is one policy for which
persona text ends up in the system prompt.
"""

from __future__ import annotations

from pathlib import Path


_DEFAULT = (
    "You are a helpful personal assistant. "
    "Be concise and direct."
)


def resolve_persona(
    db_active_text: str | None,
    file_path: str | Path | None,
    default: str = _DEFAULT,
) -> str:
    """Return the persona text to use in the system prompt.

    Resolution order:
      1. db_active_text (from agent_prompts table — DB-stored user persona)
      2. file at file_path (e.g. ~/.kaori-agent/personality-friend.md)
      3. default

    Callers pass in whatever they've already fetched; this function does no I/O
    except reading the file if db_active_text is None and the file exists.
    """
    if db_active_text and db_active_text.strip():
        return db_active_text.strip()
    if file_path:
        p = Path(file_path).expanduser()
        if p.exists():
            try:
                text = p.read_text().strip()
                if text:
                    return text
            except OSError:
                pass
    return default
