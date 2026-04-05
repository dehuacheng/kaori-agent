# Kaori Agent

**[English](#english)** | **[中文](#中文)**

<details open>
<summary><h2>English</h2></summary>

Personal AI assistant agent with swappable LLM backends and MCP tool support. Privacy-first, self-hosted.

Kaori Agent is a terminal-based AI assistant that connects to the [Kaori](https://github.com/dehuacheng/kaori) life management backend via MCP, letting you query your health, nutrition, fitness, and finance data through natural conversation.

### Features

- **Swappable LLM backends** — DeepSeek, Kimi, OpenAI, Anthropic. Switch by changing one line in config.
- **Agentic tool loop** — Model calls tools, gets results, reasons, loops until done.
- **Streaming + thinking** — Real-time display of reasoning (DeepSeek-R1) and response text.
- **Session persistence** — Conversations saved to SQLite. Resume previous sessions, auto-title, cross-session memory.
- **Transcript compaction** — Auto-summarizes old messages when context window fills up.
- **MCP integration** — Connects to MCP servers for extensible tool access. Ships with Kaori backend support (15 read-only tools: meals, weight, workouts, portfolio, summaries, reminders).
- **Privacy by architecture** — All data stays local. LLM only sees what tools return on-demand.
- **Configurable personality** — Custom system prompt via YAML config or markdown file.
- **Tool management** — Enable/disable tools via config.

### Setup

**Requirements:** Python 3.12+

```bash
git clone https://github.com/dehuacheng/kaori-agent.git
cd kaori-agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[cli]"
```

### Configuration

Create `~/.kaori-agent/config.yaml`:

```yaml
backend: deepseek
deepseek:
  api_key: YOUR_API_KEY
  model: deepseek-chat

max_tokens: 4096

# Session persistence (optional — omit for ephemeral mode)
# data_db: /path/to/kaori/data/kaori.db

# Disable specific tools (optional)
# disabled_tools:
#   - read_file
#   - glob
#   - grep

# Personality (inline or from file)
system_prompt: |
  You are a helpful personal assistant.
# personality_file: ~/.kaori-agent/personality.md

# Optional: connect to Kaori backend via MCP
# mcp_servers:
#   kaori:
#     command: /path/to/kaori/.venv/bin/python
#     args: ["-m", "kaori.mcp_server"]
#     cwd: /path/to/kaori
#     env:
#       KAORI_API_TOKEN: your-token
```

### Running

```bash
source .venv/bin/activate
python -m kaori_agent
```

### Session Commands

| Command | Description |
|---------|-------------|
| `/sessions` | List saved sessions |
| `/new` | Start a new session |
| `/resume <id>` | Resume a previous session (prefix match) |
| `/delete <id>` | Delete a session |
| `/title <text>` | Set session title |
| `/memory` | Show persistent memory entries |
| `/memory set <key> <value>` | Save a memory entry |
| `/memory delete <key>` | Delete a memory entry |
| `/compact` | Force transcript compaction |
| `/help` | Show all commands |
| `/quit` | Exit |

### Architecture

Kaori Agent is built around a simple agentic loop: send messages + tool schemas to the LLM, execute any tool calls locally, feed results back, repeat until done.

The LLM backend is abstracted behind `LLMBackend` ABC with two implementations: `OpenAIBackend` (DeepSeek, Kimi, OpenAI — all via the `openai` SDK with configurable `base_url`) and `AnthropicBackend`. Swapping backends preserves conversation history.

External tools are integrated via MCP (Model Context Protocol). The Kaori backend exposes 15 read-only tools through its MCP server, giving the agent access to meals, weight, workouts, portfolio, and more — without any Kaori-specific code in the agent itself.

Session data is stored in SQLite (co-located with the Kaori backend database when configured). The agent creates its own `agent_*` tables, keeping session data alongside Kaori data for unified backup.

### Roadmap

- **Phase 0: Chat** — Bare REPL ✅
- **Phase 1: Tool Loop** — Agentic loop + read-only tools ✅
- **Phase 3: Streaming** — Real-time thinking + text display ✅
- **Phase 4: Sessions** — Conversation persistence + memory + compaction ✅
- **Phase 7: Domain Tools** — Kaori integration via MCP ✅
- **Phase 2: Write Tools** — Edit/write/bash + permissions (future)
- **Phase 5: Skills** — YAML-based `/slash-commands` (future)
- **Phase 6: WebSocket API** — Multi-frontend support (future)
- **Phase 8: iOS Chat UI** — SwiftUI client (future)

</details>

<details>
<summary><h2>中文</h2></summary>

隐私优先、自托管的个人 AI 助手，支持多 LLM 后端切换和 MCP 工具集成。

Kaori Agent 是一个终端 AI 助手，通过 MCP 连接 [Kaori](https://github.com/dehuacheng/kaori) 生活管理后端，让你通过自然对话查询健康、营养、健身和财务数据。

### 功能

- **多 LLM 后端** — 支持 DeepSeek、Kimi、OpenAI、Anthropic，一行配置即可切换。
- **Agent 工具循环** — 模型调用工具、获取结果、推理、循环直到完成。
- **流式输出 + 思考过程** — 实时显示推理过程（DeepSeek-R1）和回复文本。
- **会话持久化** — 对话保存到 SQLite，支持恢复历史会话、自动标题、跨会话记忆。
- **上下文压缩** — 当上下文窗口接近容量时，自动摘要旧消息。
- **MCP 集成** — 连接 MCP 服务器获取可扩展的工具。内置 Kaori 后端支持（15 个只读工具：饮食、体重、运动、投资组合、总结、提醒等）。
- **隐私架构** — 所有数据保存在本地，LLM 只能看到工具按需返回的内容。
- **可配置人格** — 通过 YAML 配置或 Markdown 文件自定义系统提示。
- **工具管理** — 通过配置启用/禁用工具。

### 安装

**环境要求：** Python 3.12+

```bash
git clone https://github.com/dehuacheng/kaori-agent.git
cd kaori-agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[cli]"
```

### 配置

创建 `~/.kaori-agent/config.yaml`：

```yaml
backend: deepseek
deepseek:
  api_key: 你的API密钥
  model: deepseek-chat

max_tokens: 4096

# 会话持久化（可选 — 不配置则为临时模式）
# data_db: /path/to/kaori/data/kaori.db

# 禁用特定工具（可选）
# disabled_tools:
#   - read_file
#   - glob
#   - grep

system_prompt: |
  你是一个贴心的个人助手。
```

### 运行

```bash
source .venv/bin/activate
python -m kaori_agent
```

### 会话命令

| 命令 | 说明 |
|------|------|
| `/sessions` | 列出已保存的会话 |
| `/new` | 开始新会话 |
| `/resume <id>` | 恢复历史会话（前缀匹配） |
| `/delete <id>` | 删除会话 |
| `/title <文本>` | 设置会话标题 |
| `/memory` | 显示持久化记忆 |
| `/memory set <键> <值>` | 保存记忆条目 |
| `/memory delete <键>` | 删除记忆条目 |
| `/compact` | 强制上下文压缩 |
| `/help` | 显示所有命令 |
| `/quit` | 退出 |

### 路线图

- **Phase 0: 聊天** — 基础 REPL ✅
- **Phase 1: 工具循环** — Agent 循环 + 只读工具 ✅
- **Phase 3: 流式输出** — 实时思考 + 文本显示 ✅
- **Phase 4: 会话** — 对话持久化 + 记忆系统 + 上下文压缩 ✅
- **Phase 7: 领域工具** — 通过 MCP 集成 Kaori ✅
- **Phase 2: 写入工具** — 编辑/写入/bash + 权限（未来）
- **Phase 5: 技能** — 基于 YAML 的 `/slash-commands`（未来）
- **Phase 6: WebSocket API** — 多前端支持（未来）
- **Phase 8: iOS 聊天界面** — SwiftUI 客户端（未来）

</details>

## License

[MIT](LICENSE)
