"""Backwards-compat shim — feed logic moved to kaori_agent.prompt_kit.feed.

Existing `from kaori_agent.feed_context import fetch_recent_feed` calls keep
working. New code should import from `kaori_agent.prompt_kit` directly.
"""

from kaori_agent.prompt_kit.feed import (
    fetch_and_render_feed as fetch_recent_feed,
    render_feed_payload,
)

__all__ = ["fetch_recent_feed", "render_feed_payload"]
