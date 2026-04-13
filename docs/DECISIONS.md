# Decision Log

> Tracks substantial user instructions and project direction changes.
> Each entry summarizes the user's intent so future sessions have full context.

### 2026-04-04 — Project inception: standalone agent with Kaori integration path

**User intent:** Build a minimal "Claude Code"-style personal assistant agent. Priorities are privacy, token efficiency, and extensibility (tool_use + skills). Start standalone (not embedded in Kaori), but design interfaces so Kaori integration is easy later. The backend should be chat-based; the frontend is also chat-based.

**Outcome:** Created phased design (Phase 0-8) going from bare chat REPL to full iOS-integrated personal assistant. Standalone Python core with clean BaseTool interface for future Kaori domain tools. Project named `kaori-agent`, lives at `this repo`.

### 2026-04-04 — Language choice: Python

**User intent:** Considered Swift (iOS native) vs Python (Kaori backend). Decided on Python for the core engine — matches Kaori's stack, faster iteration, easier subprocess/tool execution. iOS app would connect via WebSocket API in a later phase.

**Outcome:** Python 3.12+ with `anthropic` SDK. CLI-first, WebSocket API added in Phase 6 for iOS.

### 2026-04-04 — Tool focus: generic first, domain later

**User intent:** Start with generic coding tools (file I/O, bash, search), add Kaori-specific tools (health/finance queries) in a later phase. Want to future-proof the interfaces.

**Outcome:** Phase 0-2 builds generic tools. Phase 7 adds Kaori domain tools. The BaseTool interface is the extension point — adding Kaori tools requires zero engine changes.

### 2026-04-05 — Swappable LLM backends: OpenAI-compatible + Anthropic

**User intent:** Use DeepSeek API for testing now, Kimi API later, Anthropic eventually. Must be able to swap backends while retaining sessions/memory. API keys and personality prompt should be private (not in git).

**Outcome:** Added `LLMBackend` ABC with two implementations: `OpenAIBackend` (DeepSeek, Kimi, OpenAI via `openai` SDK with configurable `base_url`) and `AnthropicBackend` (Anthropic native SDK). Engine loop is backend-agnostic — interacts only with universal `TurnResult`/`ToolCall` types. Config lives in `~/.kaori-agent/config.yaml` (personality, backend selection) + `.env` (API keys). Both gitignored.

### 2026-04-05 — Phase 0+1 implemented together

**User intent:** Get the project running. Phases should coexist in the repo — later phases add files without modifying earlier ones.

**Outcome:** Implemented Phase 0 (bare chat) and Phase 1 (tool loop + read_file, glob, grep) in one pass. Engine always runs the tool loop; with zero tools it degrades to Phase 0 behavior. All 33 unit tests passing.

### 2026-04-05 — Phase 4: Store agent sessions in kaori.db

**User intent:** Implement session persistence for kaori-agent. Store sessions/memory in kaori's SQLite database (co-located with all kaori data) so everything can be backed up together (e.g., Google Drive sync). Design with iOS integration in mind — a future iOS tab will access agent sessions via REST API.

**Outcome:** Agent session tables (`agent_sessions`, `agent_messages`, `agent_memory`, `agent_compactions`, `agent_prompts`) added directly to kaori.db. Tables are `agent_`-prefixed with no foreign keys to existing kaori tables — self-contained island. kaori-agent creates tables via CREATE TABLE IF NOT EXISTS on startup (self-bootstraps). Config points to kaori.db via `data_db` setting. Session persistence is opt-in — without `data_db`, CLI works in ephemeral mode. kaori backend REST API endpoints for iOS deferred to next session (see `kaori/docs/TODO-agent-integration.md`).

### 2026-04-11 — Web search via Tavily as a native tool

**User intent:** Add web search to the agent so it can answer questions that require current information beyond training cutoff. Reuse the existing MCP infrastructure if possible, otherwise native tool.

**Outcome:** Went native over MCP because (a) no Node toolchain installed locally, and (b) a BaseTool subclass is 70 lines total. Added `WebSearchTool` in `kaori_agent/tools/web_search.py` using the `tavily-python` SDK (read `TAVILY_API_KEY` from env, lazy import so the package is optional). Registered in `get_default_tools()`. Tavily added as `[search]` extras in pyproject. Kaori backend (separate project) reuses this class via an adapter in `kaori/services/agent_tools.py` so the tool body exists in one place.

### 2026-04-13 — Frontend parity migration: kaori_agent.prompt_kit landed, kaori backend rewired

**User intent:** Implement the parity principle from the prior decision. CLI and iOS should now share the prompt-and-context layer through one module.

**Outcome:** Created `kaori_agent/prompt_kit/` with five submodules — `builder` (assembles persona + base + digests + feed + memory + resumed-session note), `session_digests` (pure shaping function), `session_summary` (LLM-backed friend-style summary generator), `feed` (HTTP fetch + payload renderer), `persona` (DB-first / file-fallback resolver). CLI's `prompt.py`, `feed_context.py`, `Session.generate_summary`, and CLI's `_build_session_digests` are now thin wrappers calling into prompt_kit. Backend (kaori): installed kaori_agent editable into kaori's venv (`pip install -e ../kaori-agent --no-deps`), removed `agent_chat_service._build_system_prompt`, replaced with calls into `prompt_kit.build_system_prompt` plus `_fetch_feed_snapshot` (calls `feed_service.get_feed()` directly, in-process — no HTTP round-trip), `_fetch_session_digests`, `_resolved_persona`, and `_maybe_summarize_inactive` (fire-and-forget background task that summarizes the previous inactive user session on every new chat start). Added `memory_saved` SSE event: backend's `SaveMemoryTool` now accepts an `on_save` callback, the chat service drains those into the SSE stream so iOS can render a chip / CLI a dim line. Schema: added `summary` and `summary_updated_at` to kaori's `agent_sessions` CREATE TABLE plus a `_migrate_agent_sessions_summary` migration. New `agent_session_repo.update_summary()`. Test suite stayed intact: kaori-agent 108/108 pass; kaori backend gained 2 new prompt_kit tests (104→106 pass), the 31 pre-existing API auth failures are unrelated to this migration. Migration checklist in `docs/FRONTEND-PARITY.md` checked off.

### 2026-04-13 — Frontend parity principle: one source of truth for prompt + context

**User intent:** The friend-mode + continuity + feed work from earlier today only landed in the CLI; the iOS path goes through kaori backend's parallel `_build_system_prompt` and missed everything. User wants future cross-cutting changes to apply to all frontends without extra work, and wants the principle codified so later Claude Code sessions don't reintroduce the divergence.

**Outcome:** Wrote `docs/FRONTEND-PARITY.md` stating the rule: anything that changes what the model sees or how non-chat output is surfaced lives in shared code under `kaori_agent`. Direction of dependency is `kaori → kaori_agent` (library-ify the agent; never the reverse). Scope intentionally narrow — prompt-and-context layer only (engine/tools/LLM backend duplication stays for now). Persona resolution unified to "DB-active prompt → file fallback". Non-chat surfacings (e.g. memory-saved) flow as structured events that each frontend renders in its native idiom. Added pointers from both `kaori-agent/CLAUDE.md` and `kaori/CLAUDE.md`. Migration checklist captured at the bottom of the parity doc; implementation pending.

### 2026-04-13 — Make Kaori feel like a friend, not an assistant

**User intent:** Every new session felt cold — the agent had no memory of prior chats, no awareness of the user's recent day, and its tone leaned productivity-cheerleader. User wants continuity (summary of recent sessions injected at startup), lifestyle context (recent feed items from kaori backend), more active memory use, and a friend-first persona with assistant-mode only on explicit request.

**Outcome:** Added a per-session narrative summary (`summary` column on `agent_sessions` + startup migration; `Session.generate_summary()` produces a 3-5 sentence friend-style summary, fired on `/new`, `/resume`, and `/quit`). Extended `build_system_prompt` with a `## Recent conversations` block (last 2-3 sessions with relative dates + older titles roll-up) and a `## What's going on with you lately` block fed by a new `feed_context.fetch_recent_feed()` helper that hits `/api/feed?start_date=yesterday&end_date=today` on the kaori backend. Added `feed_context` config section (token falls back to the kaori MCP server's `KAORI_API_TOKEN` env to avoid duplication). Memory saves now surface a dim `(remembered: key = value)` line in the CLI via an `on_save` callback on `SaveMemoryTool` — agent saves silently, user still sees what was captured. New `~/.kaori-agent/personality-friend.md` replaces the "Life Enthusiast" persona as the active one: friend-first, assistant-on-trigger, memory/continuity/feed rules baked in. Old `personality.md` left untouched for rollback.
