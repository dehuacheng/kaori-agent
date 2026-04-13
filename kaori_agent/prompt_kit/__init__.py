"""Shared prompt/context logic — single source of truth for both the CLI and
the kaori backend (iOS chat).

Why this package exists: see docs/FRONTEND-PARITY.md. The short version is that
anything affecting what the model sees or how non-chat output is surfaced to the
user must live here, not in either frontend, so behavior stays aligned across
CLI and iOS without parallel edits.

Public API:
- build_system_prompt: assembles persona + base + digests + feed + memory
- shape_session_digests: turns raw session rows into the digest dict
- generate_session_summary: LLM-backed friend-style 3-5 sentence summary
- render_feed_payload: turns a /api/feed payload into compact bullets
- fetch_and_render_feed: HTTP fetch + render (CLI helper)
- resolve_persona: DB-active prompt > file fallback > default
"""

from kaori_agent.prompt_kit.builder import build_system_prompt
from kaori_agent.prompt_kit.session_digests import shape_session_digests
from kaori_agent.prompt_kit.session_summary import generate_session_summary
from kaori_agent.prompt_kit.feed import render_feed_payload, fetch_and_render_feed
from kaori_agent.prompt_kit.persona import resolve_persona

__all__ = [
    "build_system_prompt",
    "shape_session_digests",
    "generate_session_summary",
    "render_feed_payload",
    "fetch_and_render_feed",
    "resolve_persona",
]
