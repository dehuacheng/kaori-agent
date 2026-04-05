# Personal Assistant Agent: Phased Design

## What This Is

A phased blueprint for building a minimal personal assistant agent, inspired by Claude Code's architecture (analyzed via the `instructkr/claw-code` Python port). Each phase is independently useful and shippable. Later phases build on earlier ones without requiring rewrites.

## Core Insight

Claude Code's architecture reduces to:

```
User message → [System Prompt + History + Tool Schemas] → Claude API
            ← [Text or Tool Calls]
            → Execute tools → Feed results back → Loop until done
```

Everything else — 184 tools, 207 commands, 30 subsystems, remote modes, MCP, plugins — is layered on top of this loop. **The minimum viable agent is this loop + a tool registry + session state.**

## Design Principles

1. **Chat-native** — the engine IS a conversation. Frontends (CLI, WebSocket, REST) are just transports.
2. **Tools as the extension point** — adding capability = adding a tool. No engine changes needed.
3. **Skills as prompt augmentation** — skills are prompt templates invoked via `/slash-commands`, not new code.
4. **Privacy by architecture** — system prompt contains zero user data. All personal data flows through tool calls on-demand.
5. **Token efficiency by laziness** — never pre-load context. Let the model ask for what it needs via tools.
6. **Standalone core, pluggable domain** — the engine knows nothing about health/finance/etc. Domain tools register themselves.

---

## Phase 0: Chat — The Simplest Possible Thing

**What:** A CLI that sends messages to Claude and prints responses. No tools, no streaming, no sessions. Just a REPL + API call.

**Files (3):**

```
kaori_agent/
├── __main__.py       # Entry point: python -m kaori_agent
├── cli.py            # Input loop: read prompt, print response
└── config.py         # API key, model name, max_tokens
```

**How it works:**

```python
# cli.py (pseudocode)
client = anthropic.Anthropic()
messages = []

while True:
    user_input = input("> ")
    messages.append({"role": "user", "content": user_input})
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system="You are a helpful personal assistant.",
        messages=messages,
    )
    
    assistant_text = response.content[0].text
    messages.append({"role": "assistant", "content": assistant_text})
    print(assistant_text)
```

**What you get:**
- A working chat with Claude in your terminal
- Full conversation context (within context window)
- ~30 lines of code

**Dependencies:** `anthropic`

---

## Phase 1: Tool Loop — The Agent Becomes Useful

**What:** Add the tool_use agentic loop + 3 read-only tools. The model can now inspect files and search code.

**New files (5):**

```
kaori_agent/
├── engine.py              # Core agentic turn loop
├── tool_registry.py       # Register tools, generate Anthropic schemas
├── tools/
│   ├── base.py            # BaseTool ABC + ToolResult dataclass
│   ├── read_file.py       # Read file contents with line ranges
│   └── search.py          # Glob pattern + content grep
```

**The tool_use loop:**

```python
async def run_turn(messages, tools, system_prompt):
    tool_schemas = [t.to_anthropic_schema() for t in tools]
    
    while True:
        response = client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system_prompt, messages=messages, tools=tool_schemas,
        )
        messages.append({"role": "assistant", "content": response.content})
        
        if response.stop_reason == "end_turn":
            return extract_text(response)
        
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool = registry.get(block.name)
                    result = await tool.execute(**block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.to_string(),
                    })
            messages.append({"role": "user", "content": tool_results})
```

**Tool interface:**

```python
class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult: ...

    def to_anthropic_schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}
```

---

## Phase 2: Write Tools + Permissions

**New tools:** `edit_file`, `write_file`, `bash`, `list_dir`

**Permission model:**

```python
class SafetyLevel(Enum):
    SAFE = "safe"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
```

| Tool | Safety | Notes |
|------|--------|-------|
| `read_file` | safe | |
| `search_files` | safe | |
| `list_dir` | safe | |
| `edit_file` | safe | Only modifies existing content |
| `write_file` | approval_required | Creates new files |
| `bash` | dynamic | Allowlist for safe commands, approval otherwise |

---

## Phase 3: Streaming

Switch from blocking `messages.create()` to streaming `messages.stream()`. Define event types (TextDelta, ToolUseStart, ToolResult, ApprovalRequest, TurnDone) and render them in real-time.

---

## Phase 4: Sessions ✅

**Implemented:** Session persistence in SQLite (co-located with kaori.db).

**Key files:**
- `kaori_agent/session.py` — `SessionStore` + `Session` classes
- `kaori_agent/tools/memory.py` — `SaveMemoryTool`, `GetMemoryTool`

**Data model:** 5 tables in kaori.db (`agent_sessions`, `agent_messages`, `agent_memory`, `agent_compactions`, `agent_prompts`). All `agent_`-prefixed, no FK coupling to existing kaori tables.

**Features:**
- Session create/load/list/delete with `/sessions`, `/new`, `/resume`, `/delete` commands
- Message persistence on every turn (auto-save)
- Auto-title from first user message
- Cross-session memory (key-value facts) via `/memory` commands and agent tools
- Transcript compaction when token usage exceeds threshold (default 80% of context window)
- Versioned compaction summaries (rollback-safe, following kaori's append-only pattern)
- Personal prompt storage in DB (for future iOS editing)
- Opt-in: without `data_db` config, CLI works in ephemeral mode

**Config:** `data_db: /path/to/kaori/data/kaori.db` in `~/.kaori-agent/config.yaml`

**iOS integration:** Schema designed for REST API exposure. Backend endpoints deferred to next session (see `kaori/docs/TODO-agent-integration.md`).

---

## Phase 5: Skills

YAML-based skill definitions invoked as `/slash-commands`. Each skill injects a system prompt addition and optionally auto-sends a first message. No code needed for new skills.

---

## Phase 6: WebSocket API

FastAPI + WebSocket server exposing the engine to any frontend (iOS, web). JSON event protocol matching the streaming events. REST endpoints for session CRUD.

---

## Phase 7: Domain Tools (Kaori Integration)

Tools that query/update Kaori data: `kaori_query`, `kaori_log`, `kaori_summary`, `kaori_portfolio`. Can call Kaori's REST API when standalone, or import services directly when co-deployed.

---

## Phase 8: iOS Chat UI

SwiftUI chat view consuming the WebSocket endpoint. Markdown rendering, tool action cards, approval sheets, skill menu.

---

## Phase Dependencies

```
Phase 0: Chat (bare REPL)
  │
  ▼
Phase 1: Tool Loop (read-only agent)
  │
  ├──▶ Phase 2: Write Tools + Permissions (full coding agent)
  │       │
  │       ├──▶ Phase 3: Streaming (real-time UX)
  │       │
  │       └──▶ Phase 4: Sessions (persistence)
  │               │
  │               └──▶ Phase 5: Skills (workflow shortcuts)
  │
  └──▶ Phase 6: WebSocket API (multi-frontend)
          │
          ├──▶ Phase 7: Domain Tools (Kaori integration)
          │
          └──▶ Phase 8: iOS Chat UI
```

## Privacy Architecture

```
Your machine (private)                    Cloud (Anthropic API)
┌────────────────────────────┐            ┌──────────────────┐
│  Kaori DB (health/finance) │            │                  │
│  Local files               │──tools──▶  │  Only sees:      │
│  Session history           │            │  - System prompt  │
│                            │            │  - Messages       │
│  Tool execution happens    │            │  - Tool schemas   │
│  HERE — results sent to    │            │  - Tool results   │
│  API only when model asks  │            │                  │
└────────────────────────────┘            └──────────────────┘
```

## Technology Choices

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.12+ | Matches Kaori, fast iteration, async native |
| LLM SDK | `anthropic` | Native tool_use + streaming support |
| CLI UI | `rich` | Markdown rendering, syntax highlighting |
| Input | `prompt_toolkit` | History, multiline, key bindings |
| WebSocket | `fastapi` + `websockets` | Matches Kaori, async native |
| Session storage | JSON files → SQLite | Start simple, migrate later |
| Skills format | YAML | Human-editable, no code needed |

## Final File Structure (All Phases)

```
kaori_agent/
├── __init__.py
├── __main__.py              # python -m kaori_agent
├── engine.py                # Core agentic turn loop          (Phase 1)
├── tool_registry.py         # Tool registration + schemas     (Phase 1)
├── permissions.py           # Safety levels + approval        (Phase 2)
├── session.py               # Conversation persistence        (Phase 4)
├── prompt.py                # System prompt builder           (Phase 1)
├── skills.py                # Skill loading + invocation      (Phase 5)
├── config.py                # Settings + env vars             (Phase 0)
├── events.py                # Streaming event types           (Phase 3)
├── cli.py                   # Terminal REPL frontend          (Phase 0)
├── server.py                # FastAPI + WebSocket server      (Phase 6)
├── tools/
│   ├── __init__.py
│   ├── base.py              # BaseTool ABC + ToolResult       (Phase 1)
│   ├── read_file.py         #                                (Phase 1)
│   ├── search.py            # Glob + grep                    (Phase 1)
│   ├── list_dir.py          #                                (Phase 2)
│   ├── edit_file.py         # String replacement             (Phase 2)
│   ├── write_file.py        #                                (Phase 2)
│   ├── bash.py              # Shell execution                (Phase 2)
│   ├── web_fetch.py         # URL fetching                   (Phase 6)
│   ├── kaori_query.py       # Read Kaori data                (Phase 7)
│   ├── kaori_log.py         # Write Kaori entries            (Phase 7)
│   ├── kaori_summary.py     # Health summaries               (Phase 7)
│   └── kaori_portfolio.py   # Portfolio queries              (Phase 7)
└── skills/
    ├── commit.yaml           #                               (Phase 5)
    ├── review.yaml           #                               (Phase 5)
    ├── explain.yaml          #                               (Phase 5)
    ├── daily-review.yaml     #                               (Phase 7)
    ├── log-meal.yaml         #                               (Phase 7)
    └── weekly-plan.yaml      #                               (Phase 7)
```

~20 files for the full vision. ~8 files for Phase 0-2 (a working coding agent).
