# Documentation Plan

> Index of all kaori-agent documentation with version tracking.

## Feature Docs

| Feature | Version | Status | Doc |
|---------|---------|--------|-----|
| Phased Design | 1.0.0 | Stable | [design.md](design.md) |
| Decision Log | 1.0.0 | Ongoing | [DECISIONS.md](DECISIONS.md) |

## Architecture Overview

- **Design doc** — `docs/design.md`: 8-phase blueprint from bare chat to iOS integration.
- **Decision log** — `docs/DECISIONS.md`: Tracks user instructions and direction changes.
- **CLAUDE.md** — Project instructions for Claude Code sessions.

## Key Files

```
kaori_agent/
├── config.py            # Config loading (YAML + env vars)
├── engine.py            # Backend-agnostic agentic loop
├── prompt.py            # System prompt builder
├── tool_registry.py     # Tool registration
├── mcp_client.py        # MCP server connection manager
├── cli.py               # Terminal REPL
├── __main__.py          # Entry point
├── llm/
│   ├── base.py          # LLMBackend ABC + StreamEvent types
│   ├── openai_backend.py    # DeepSeek, Kimi, OpenAI
│   └── anthropic_backend.py # Anthropic
└── tools/
    ├── base.py          # BaseTool ABC + ToolResult
    ├── read_file.py     # File reading
    └── search.py        # Glob + Grep
```
