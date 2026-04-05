# kaori-agent

Personal assistant agent with tool_use support, inspired by Claude Code's architecture.

## Project Overview

- **Language:** Python 3.12+
- **LLM SDK:** `openai` (DeepSeek, Kimi, OpenAI) + `anthropic` (Anthropic) — swappable backends
- **Architecture:** Chat-based engine with pluggable tools, swappable LLM backends, and YAML-based skills
- **Design doc:** `docs/design.md`
- **Decision log:** `docs/DECISIONS.md`

## Key Architecture

The core is an **agentic turn loop** in `engine.py`:
1. Send messages + tool schemas to LLM backend
2. If response has tool calls → execute tools locally → feed results back → loop
3. If response is text → return to user

**LLM backend abstraction** (`kaori_agent/llm/`):
- `LLMBackend` ABC with `chat()`, `format_tool_schemas()`, `make_assistant_message()`, `make_tool_results()`
- `OpenAIBackend` — works with DeepSeek, Kimi, OpenAI (any OpenAI-compatible API)
- `AnthropicBackend` — works with Anthropic's native API
- Backend selection via `~/.kaori-agent/config.yaml` → `backend: deepseek`

**Extension points:**
- **Tools:** Implement `BaseTool` in `kaori_agent/tools/` — each tool has name, description, input_schema, execute()
- **Skills:** YAML files in `kaori_agent/skills/` — prompt templates invoked as `/slash-commands`
- **Frontends:** CLI (Phase 0), WebSocket (Phase 6), iOS (Phase 8) — all consume the same engine
- **Backends:** Add new LLM providers by implementing `LLMBackend`

## Configuration

**Private config** (not in repo):
- `~/.kaori-agent/config.yaml` — backend selection, model, personality/system prompt, data_db path
- `.env` file — API keys (`DEEPSEEK_API_KEY`, `KIMI_API_KEY`, `ANTHROPIC_API_KEY`)

**Session persistence** (Phase 4):
- Set `data_db: /path/to/kaori/data/kaori.db` in config.yaml to enable
- Without `data_db`, CLI runs in ephemeral mode (no persistence)
- Sessions, memory, and prompts are stored as `agent_*` tables in kaori.db

See `.env.example` for available env vars.

## Development

```bash
# Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[cli,dev]"

# Run CLI
python -m kaori_agent

# Run tests
pytest
```

## Implementation Phases

| Phase | Status | What |
|-------|--------|------|
| 0 | Done | Bare chat REPL |
| 1 | Done | Tool_use loop + read tools (read_file, glob, grep) |
| 2 | Not started | Write tools + permissions |
| 3 | Done | Streaming |
| 4 | Done | Session persistence + memory + compaction |
| 5 | Not started | Skills (YAML) |
| 6 | Not started | WebSocket API |
| 7 | Done | Kaori domain tools (MCP) |
| 8 | Not started | iOS chat UI |

## Session Commands (Phase 4)

| Command | Description |
|---------|-------------|
| `/sessions` | List saved sessions |
| `/new` | Start a new session |
| `/resume <id>` | Resume a previous session (prefix match) |
| `/delete <id>` | Delete a session |
| `/title <text>` | Set session title |
| `/memory` | Show persistent memory entries |
| `/memory set <key> <value>` | Set a memory entry |
| `/memory delete <key>` | Delete a memory entry |
| `/compact` | Force transcript compaction |

## Related Projects

- **Kaori backend:** `../kaori` — health/finance/life management. Phase 7 integrates with this via MCP.
