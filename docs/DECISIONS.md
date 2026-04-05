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
