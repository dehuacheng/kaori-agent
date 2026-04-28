"""Load a compact routing preamble from the vault's top-level AGENTS.md / INDEX.md.

This is injected into the system prompt so the agent knows the vault layout
and routing heuristics without having to read AGENTS.md every session — the
"progressive disclosure" rule from my_vault/AGENTS.md.
"""

from __future__ import annotations

from pathlib import Path


def load_vault_routing(vault_root: Path) -> str | None:
    """Build a compact routing block from AGENTS.md + INDEX.md.

    Extracts the 'Subtree map' and 'When the user asks for something — routing'
    sections from AGENTS.md, plus the 'Subtrees' list from INDEX.md. Returns
    None if neither file exists.
    """
    if not vault_root or not vault_root.exists():
        return None

    sections: list[str] = []

    agents = vault_root / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(errors="replace")
        subtree_map = _extract_section(text, "Subtree map")
        if subtree_map:
            sections.append("### Subtree map\n" + subtree_map.strip())
        routing = _extract_section(text, "When the user asks for something")
        if routing:
            sections.append("### Routing heuristics\n" + routing.strip())

    index = vault_root / "INDEX.md"
    if index.is_file():
        text = index.read_text(errors="replace")
        subtrees = _extract_section(text, "Subtrees")
        if subtrees:
            sections.append("### Top-level INDEX\n" + subtrees.strip())

    if not sections:
        return None

    body = "\n\n".join(sections)
    return (
        f"Vault root: {vault_root}\n\n"
        "Read-only tools available: `read_file`, `glob`, `grep` — all paths "
        "are relative to the vault root. Start from the routing heuristics "
        "below; drill into a subtree's AGENTS.md only when the user's question "
        "lands there. Do not blind-grep the whole vault.\n\n"
        f"{body}"
    )


def _extract_section(text: str, heading_starts_with: str) -> str | None:
    """Return the body of a `## <heading_starts_with>...` section.

    Reads from the matching header line up to the next `## ` header
    (or end of file). The header line itself is dropped.
    """
    lines = text.splitlines()
    start: int | None = None
    needle = heading_starts_with.lower()
    for i, line in enumerate(lines):
        if line.startswith("## ") and needle in line[3:].strip().lower():
            start = i + 1
            break
    if start is None:
        return None

    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break

    body = "\n".join(lines[start:end]).strip()
    return body or None
