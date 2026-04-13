# Frontend parity: one source of truth for prompt + context

> **Read this before** adding any feature that changes how the agent behaves to the user — persona, system prompt structure, memory injection, session-continuity hints, lifestyle-feed context, summarization, "agent saved a memory" indicators, etc.

## The principle

The agent has **two frontends today** and a third coming:

1. **CLI** — `kaori_agent.cli` (interactive REPL)
2. **iOS** — talks to kaori backend's `POST /api/agent/chat` (SSE), which routes through `kaori/services/agent_chat_service.py`
3. (Future) WebSocket / web UI — same backend path

**Anything that changes what the model sees or how its work is surfaced must affect all frontends with one code change.** No more parallel `_build_system_prompt` implementations. No more "I added it to the CLI, iOS will follow later." If you need a per-frontend behavior difference, parameterize — do not fork.

## Why this exists

Until 2026-04-13 the system had two unrelated implementations of the same logic:
- `kaori_agent/prompt.py::build_system_prompt`
- `kaori/services/agent_chat_service.py::_build_system_prompt`

A change to the persona, memory header, or any prompt section had to be made twice or it silently diverged. The CLI got friend-mode + recent-session digests + feed context; iOS still ran the old "Life Enthusiast" prompt against the same database. Users experience the agent as one entity — the implementation must reflect that.

## What's shared (and where it lives)

The **prompt-and-context layer** is the single source of truth, owned by `kaori_agent` (the library). The kaori backend depends on `kaori_agent` and calls into it.

Shared module: `kaori_agent.prompt_kit` (planned name — finalize during implementation)

In scope:
- `build_system_prompt(...)` — assembles persona + base instructions + date/time + recent-session digests + feed snapshot + memory + resumed-session note
- `fetch_recent_feed(base_url, token)` — pulls today+yesterday from kaori `/api/feed` and renders compact bullets
- `build_session_digests(store, current_session_id)` — builds the "recent conversations" data used by `build_system_prompt`
- `generate_session_summary(messages, backend, model)` — friend-style 3-5 sentence summary, stored on `agent_sessions.summary`
- Persona resolution policy: **DB-active prompt (`agent_prompts` table) wins; falls back to `personality_file` from config; falls back to baseline**. Both frontends use this policy.
- "Memory was saved" surfacing: emitted as a **structured event** (typed, e.g. `{"type": "memory_saved", "key": ..., "value": ..., "category": ...}`). CLI renders as a dim line; backend forwards as a new SSE event for iOS to render as a chip/badge.

Out of scope **for now** (still parallel — consolidate later if needed):
- LLM backend abstractions (`kaori_agent/llm/` vs `kaori/llm/agent_backend.py`)
- Agentic turn loop (`engine.py` vs `agent_engine.py`)
- Tool registry and tool implementations (`tools/` vs `services/agent_tools.py`)

The reason for the narrower scope: the prompt layer is where user-visible behavior lives and where divergence has actually hurt us. Engine/tools have stable contracts; their duplication is annoying but not behaviorally risky.

## Dependency direction

```
kaori (backend)  ──depends on──>  kaori_agent (library)
```

- `kaori_agent` stays standalone and runnable on its own (the CLI is just one consumer).
- `kaori_agent` is installed into kaori's venv via editable install: `pip install -e ../kaori-agent` from kaori.
- Never the reverse: do not import from `kaori.*` inside `kaori_agent`. The agent library must not know about FastAPI, SSE, repos, or backend services.
- Anything `kaori_agent` needs from the outside (persona text, memory list, session digest data, db connection) is passed in as a parameter or fetched through a thin adapter the caller provides.

## Checklist for future sessions

Before changing prompt/persona/memory/context behavior, ask yourself:

1. **Will the user see this difference whether they're on the CLI or on iOS?** If yes, the change goes in `kaori_agent.prompt_kit` (or a new sibling module under `kaori_agent`), not in either frontend.
2. **Are you adding a new prompt section?** Add a new parameter to `build_system_prompt`. Both frontends call it, both get the new section by passing the data. Do not add a new prompt-builder anywhere.
3. **Are you adding new context to fetch (e.g. weather, calendar)?** Write the fetcher in `kaori_agent` (or a new `kaori_agent/context/` module), keep it side-effect-free and best-effort (returns `None` on failure, never raises). Both frontends call it at session start.
4. **Are you surfacing something to the user that's not chat text** (memory saved, summary regenerated, mode flip)? Emit a **structured event** from the shared layer. The CLI prints it as a dim line; the backend forwards it as a new SSE event type. Add the event type to this doc.
5. **Are you changing the persona file?** It applies to both. There is one persona resolution policy (DB-first, file fallback). If you want different personas per frontend, that is a feature request — discuss before implementing.

If you find yourself writing `_build_system_prompt` or `_render_<thing>` inside `kaori/services/agent_chat_service.py`, **stop**. That code should be a call into `kaori_agent`.

## Active SSE event types (extend this list when adding new ones)

| Event | From | Data | Rendered as |
|---|---|---|---|
| `session` | backend | `{session_id, title}` | initial state |
| `thinking` | shared | `{text}` | dim italic stream |
| `text` | shared | `{text}` | response text stream |
| `tool_use` | shared | `{name, input}` | tool invocation indicator |
| `memory_saved` | shared | `{key, value, category}` | CLI dim line / iOS chip |
| `done` | shared | `{message_count}` | turn end |
| `error` | shared | `{message}` | error |

## Migration status (initial migration done 2026-04-13)

- [x] Extract `kaori_agent.prompt_kit` and move shared logic in (builder, session_digests, session_summary, feed, persona)
- [x] Replace `kaori/services/agent_chat_service.py::_build_system_prompt` with a call into `kaori_agent.prompt_kit.build_system_prompt`
- [x] Add `kaori_agent` as an editable dependency in kaori's venv (`pip install -e ../kaori-agent --no-deps`)
- [x] Unify persona resolution (DB-first, file fallback) via `prompt_kit.persona.resolve_persona` — both frontends call it
- [x] Add `memory_saved` SSE event — backend's `SaveMemoryTool` accepts an `on_save` callback that the chat service drains into the SSE stream; CLI renders as a dim line
- [x] Wire feed snapshot into backend chat startup — `_fetch_feed_snapshot()` calls `feed_service.get_feed()` directly and renders via shared `render_feed_payload`
- [x] Wire session-summary generation on backend — fire-and-forget `_maybe_summarize_inactive()` summarizes the most recent prior user session lacking a summary, on every new chat start

Steady-state nice-to-haves still on the table (not blocking parity):
- [ ] Add `summary` column to backend's `agent_session_repo.update()` allowed list (only `update_summary()` writes it today; `update()` would silently ignore if added by a future PR)
- [ ] Consolidate the parallel `SaveMemoryTool` implementations (CLI: `kaori_agent/tools/memory.py`, backend: `kaori/services/agent_tools.py`) — currently both honor an `on_save` callback so behavior matches; consider merging if churn shows up
- [ ] Backend: emit `summary_generated` SSE event when the lazy summarizer completes (so iOS can refresh its session list UI)

## Feed-snapshot freshness model

The agent's "What's going on with you lately" block is fed by an in-process call
to `feed_service.get_feed(yesterday, today)`. To avoid refetching on every chat
turn, the chat service caches the rendered snapshot per session_id.

**Freshness signal: pull-to-refresh.** The `GET /api/feed` route calls
`agent_chat_service.invalidate_feed_cache()` on every request. So whenever the
iOS app fetches the feed (initial load, pull-to-refresh, switching back to the
feed tab), the agent's snapshot is dropped and the next chat turn refetches. The
user model: "what I see on the feed is what the agent sees."

**Trade-off:** mid-session writes that don't go through a feed view refresh
won't show up in the agent's snapshot until the next refresh. For example, if
the user logs a meal via a quick-action and immediately chats without opening
the feed view, the agent won't see the new meal. The fix when this matters is
to also call `invalidate_feed_cache()` from the relevant write path. Until
that's needed, the pull-to-refresh signal is the single, simple freshness hook.

**For new write paths that should appear in the agent snapshot immediately:**
add `from kaori.services.agent_chat_service import invalidate_feed_cache;
invalidate_feed_cache()` after the write completes.
