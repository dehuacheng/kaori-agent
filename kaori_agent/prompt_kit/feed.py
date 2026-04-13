"""Render a kaori /api/feed payload into compact bullets for the system prompt.

Split into:
- render_feed_payload: pure renderer (used by both frontends)
- fetch_and_render_feed: HTTP fetch + render (CLI convenience)

The backend can call `kaori.services.feed_service.get_feed()` directly and pass
the dict into render_feed_payload without going through HTTP.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


async def fetch_and_render_feed(base_url: str, token: str | None) -> str | None:
    """HTTP-fetch today+yesterday feed and render compact bullets.

    Returns a multi-line string on success, None on any failure. Never raises.
    """
    if not base_url:
        return None
    import httpx  # lazy — only CLI needs this

    today = date.today()
    yesterday = today - timedelta(days=1)
    url = base_url.rstrip("/") + "/api/feed"
    params = {
        "start_date": yesterday.isoformat(),
        "end_date": today.isoformat(),
    }
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return None
    return render_feed_payload(payload)


def render_feed_payload(payload: dict[str, Any]) -> str | None:
    """Turn a FeedResponse-shaped dict into compact bullets, or None if empty.

    Expected shape:
        {"dates": [{date, items: [{type, data, ...}], nutrition_totals,
                    portfolio, summary, weather}, ...]}
    """
    dates = payload.get("dates") or []
    if not dates:
        return None

    today_iso = date.today().isoformat()
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()

    sections: list[str] = []
    for group in dates:
        d = group.get("date")
        if d == today_iso:
            label = f"Today ({d})"
        elif d == yesterday_iso:
            label = f"Yesterday ({d})"
        else:
            label = d or "(unknown date)"

        bullets = _render_group(group)
        if bullets:
            sections.append(f"**{label}**\n" + "\n".join(bullets))

    if not sections:
        return None
    return "\n\n".join(sections)


def _render_group(group: dict[str, Any]) -> list[str]:
    """Render a single date group as a list of bullet strings."""
    bullets: list[str] = []
    items = group.get("items") or []

    meals: list[str] = []
    workouts: list[str] = []
    weights: list[str] = []
    posts: list[str] = []
    reminders: list[str] = []

    for item in items:
        itype = item.get("type")
        data = item.get("data") or {}
        if itype == "meal":
            label = data.get("name") or data.get("meal_type") or "meal"
            cal = data.get("total_calories") or data.get("calories")
            if cal:
                meals.append(f"{label} (~{int(cal)} kcal)")
            else:
                meals.append(str(label))
        elif itype in ("workout", "healthkit_workout"):
            name = data.get("name") or data.get("activity_type") or data.get("type") or "workout"
            dur = data.get("duration_minutes") or data.get("duration")
            if dur:
                workouts.append(f"{name} ({dur} min)")
            else:
                workouts.append(str(name))
        elif itype == "weight":
            val = data.get("weight_kg") or data.get("weight")
            unit = data.get("unit") or ("kg" if data.get("weight_kg") else "")
            if val:
                weights.append(f"{val}{unit}".strip())
        elif itype == "post":
            title = data.get("title") or ""
            content = (data.get("content") or "").strip().replace("\n", " ")
            if len(content) > 120:
                content = content[:120] + "…"
            if title and content:
                posts.append(f"post: {title} — {content}")
            elif title:
                posts.append(f"post: {title}")
            elif content:
                posts.append(f"post: {content}")
        elif itype == "reminder":
            text = data.get("text") or data.get("title") or data.get("description") or ""
            done = data.get("completed") or data.get("done")
            if text:
                reminders.append(f"reminder: {text}{' (done)' if done else ''}")

    if meals:
        bullets.append(f"- meals: {', '.join(meals)}")
    totals = group.get("nutrition_totals") or {}
    if totals:
        cal = totals.get("total_cal") or totals.get("calories")
        protein = totals.get("total_protein") or totals.get("protein")
        pieces = []
        if cal:
            pieces.append(f"{int(cal)} kcal")
        if protein:
            pieces.append(f"{int(protein)}g protein")
        if pieces:
            bullets.append(f"- nutrition totals: {', '.join(pieces)}")
    if workouts:
        bullets.append(f"- workouts: {', '.join(workouts)}")
    if weights:
        bullets.append(f"- weight: {', '.join(weights)}")
    portfolio = group.get("portfolio") or {}
    combined = portfolio.get("combined") if isinstance(portfolio, dict) else None
    if combined:
        total = combined.get("total_value")
        change = combined.get("day_change")
        pct = combined.get("day_change_pct")
        pieces = []
        if total is not None:
            pieces.append(f"total ${int(total):,}")
        if change is not None:
            arrow = "▲" if change >= 0 else "▼"
            if pct is not None:
                pieces.append(f"{arrow} ${abs(int(change)):,} ({pct:+.2f}%)")
            else:
                pieces.append(f"{arrow} ${abs(int(change)):,}")
        if pieces:
            bullets.append(f"- portfolio: {', '.join(pieces)}")
    summary = group.get("summary") or {}
    if isinstance(summary, dict):
        text = summary.get("summary_text") or summary.get("text") or ""
        if text:
            text = text.strip().replace("\n", " ")
            if len(text) > 200:
                text = text[:200] + "…"
            bullets.append(f"- daily summary: {text}")
    if posts:
        for p in posts:
            bullets.append(f"- {p}")
    if reminders:
        for r in reminders:
            bullets.append(f"- {r}")

    return bullets
