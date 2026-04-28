"""Interactive CLI REPL for kaori-agent."""

from __future__ import annotations

import sys

from kaori_agent.config import get_config
from kaori_agent.engine import run_turn_stream
from kaori_agent.feed_context import fetch_recent_feed
from kaori_agent.llm import get_backend
from kaori_agent.llm.base import LLMError
from kaori_agent.prompt import build_system_prompt
from kaori_agent.tool_registry import ToolRegistry
from kaori_agent.tools import get_default_tools
from kaori_agent.vault_context import load_vault_routing

# Try rich + prompt_toolkit; fall back to plain I/O
try:
    from rich.console import Console
    from rich.text import Text

    _console = Console()
    _has_rich = True

    def _error(text: str) -> None:
        _console.print(Text(text, style="red"))

    def _info(text: str) -> None:
        _console.print(Text(text, style="dim"))

except ImportError:
    _has_rich = False

    def _error(text: str) -> None:
        print(f"ERROR: {text}", file=sys.stderr)

    def _info(text: str) -> None:
        print(text)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    _has_prompt_toolkit = True
except ImportError:
    _has_prompt_toolkit = False


async def _handle_stream(backend, messages, tools, system_prompt, model, max_tokens) -> None:
    """Stream a turn, rendering thinking/text/tool events in real-time."""
    in_thinking = False

    async for event in run_turn_stream(backend, messages, tools, system_prompt, model, max_tokens):
        if event.type == "thinking":
            if not in_thinking:
                if _has_rich:
                    _console.print(Text("thinking... ", style="dim italic"), end="")
                else:
                    print("thinking... ", end="", flush=True)
                in_thinking = True
            if _has_rich:
                _console.print(Text(event.text, style="dim italic"), end="")
            else:
                print(event.text, end="", flush=True)

        elif event.type == "text":
            if in_thinking:
                print()  # newline to end thinking block
                in_thinking = False
            print(event.text, end="", flush=True)

        elif event.type == "tool_use":
            if in_thinking:
                print()
                in_thinking = False
            tc = event.tool_call
            if _has_rich and tc:
                args_brief = str(tc.input)[:80]
                t = Text()
                t.append(f"\n  ▶ {tc.name}", style="yellow")
                t.append(f" {args_brief}", style="dim")
                _console.print(t)
            else:
                print(f"\n  ▶ {event.text}")

    # End of stream — newline
    if in_thinking:
        print()
    print()


# ---------------------------------------------------------------------------
# Session digest + feed helpers
# ---------------------------------------------------------------------------

async def _build_session_digests(
    session_store,
    current_session_id: str | None,
    max_recent: int = 3,
    older_limit: int = 8,
) -> dict | None:
    """Fetch sessions and shape into a digest dict via the shared prompt_kit."""
    if session_store is None:
        return None
    from kaori_agent.prompt_kit import shape_session_digests
    sessions = await session_store.list_sessions(limit=max_recent + older_limit)
    return shape_session_digests(
        sessions, current_session_id=current_session_id, max_recent=max_recent,
    )


async def _get_feed_snapshot(config) -> str | None:
    """Fetch feed snapshot if enabled; print a dim note on failure."""
    if not config.feed_context.enabled:
        return None
    snap = await fetch_recent_feed(
        config.feed_context.base_url, config.feed_context.token
    )
    if snap is None:
        _info("(feed unavailable — continuing without lifestyle context)")
    return snap


def _make_on_memory_save():
    """Callback for SaveMemoryTool that prints a dim '(remembered: k = v)' line."""
    def _cb(key: str, value: str, category: str) -> None:
        if len(value) > 120:
            value = value[:120] + "…"
        msg = f"  (remembered: {key} = {value})"
        if _has_rich:
            _console.print(Text(msg, style="dim italic"))
        else:
            print(msg)
    return _cb


async def _try_generate_summary(session, backend, max_tokens: int) -> None:
    """Best-effort: generate & persist a session summary. Never raises."""
    if session is None:
        return
    try:
        # The system_prompt arg is kept for backward compat and ignored.
        await session.generate_summary(backend, "", max_tokens)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session-aware slash commands
# ---------------------------------------------------------------------------

async def _cmd_sessions(session_store) -> None:
    """List recent sessions."""
    sessions = await session_store.list_sessions(limit=20)
    if not sessions:
        _info("No sessions found.")
        return
    for s in sessions:
        title = s["title"] or "(untitled)"
        count = s["message_count"]
        date = s["updated_at"][:16] if s["updated_at"] else "?"
        sid = s["id"][:8]
        _info(f"  {sid}  {title}  ({count} msgs, {date})")


async def _cmd_memory(session_store) -> None:
    """Show all memory entries."""
    entries = await session_store.list_memory()
    if not entries:
        _info("No memories saved.")
        return
    for e in entries:
        _info(f"  {e['key']}: {e['value']}  [{e['category']}]")


async def _cmd_memory_set(session_store, args: str) -> None:
    """Set a memory entry: /memory set <key> <value>"""
    parts = args.split(None, 1)
    if len(parts) < 2:
        _error("Usage: /memory set <key> <value>")
        return
    key, value = parts
    await session_store.set_memory(key, value)
    _info(f"Saved: {key} = {value}")


async def _cmd_memory_delete(session_store, key: str) -> None:
    """Delete a memory entry."""
    if await session_store.delete_memory(key.strip()):
        _info(f"Deleted: {key.strip()}")
    else:
        _error(f"No memory found for key: {key.strip()}")


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

async def main() -> None:
    """Run the interactive REPL."""
    config = get_config()

    if not config.backend.api_key:
        _error(
            f"No API key for backend '{config.backend.name}'. "
            f"Set it in ~/.kaori-agent/config.yaml or .env file. "
            f"See .env.example for details."
        )
        sys.exit(1)

    try:
        backend = get_backend(config.backend)
    except LLMError as e:
        _error(str(e))
        sys.exit(1)

    # --- Session store (optional) ---
    session_store = None
    session = None
    is_resumed = False

    if config.data_db:
        from kaori_agent.session import SessionStore
        session_store = SessionStore(config.data_db)
        await session_store.initialize()
        session = await session_store.create_session(
            config.backend.name, config.backend.model
        )

    on_mem_save = _make_on_memory_save()

    # --- Tools ---
    registry = ToolRegistry()
    for tool in get_default_tools(
        session_store=session_store,
        session_id=session.id if session else None,
        disabled_tools=config.disabled_tools,
        on_memory_save=on_mem_save,
        vault_config=config.vault,
    ):
        registry.register(tool)

    # Connect to MCP servers
    mcp_manager = None
    if config.mcp_servers:
        from kaori_agent.mcp_client import MCPManager, MCPServerConfig as MCPSrvCfg
        mcp_manager = MCPManager()
        for srv in config.mcp_servers:
            _info(f"Connecting to MCP server '{srv.name}'...")
            mcp_srv_cfg = MCPSrvCfg(
                name=srv.name,
                command=srv.command,
                args=srv.args,
                cwd=srv.cwd,
                env=srv.env,
            )
            try:
                mcp_tools = await mcp_manager.connect(mcp_srv_cfg)
                for tool in mcp_tools:
                    registry.register(tool)
                _info(f"  {len(mcp_tools)} tools from '{srv.name}'")
            except Exception as e:
                _error(f"Failed to connect to MCP server '{srv.name}': {e}")

    # --- Context to inject: memory, session digests, feed snapshot, vault routing ---
    memory_entries: list = []
    if session_store:
        memory_entries = await session_store.list_memory()
    session_digests = await _build_session_digests(
        session_store, session.id if session else None
    )
    feed_snapshot = await _get_feed_snapshot(config)
    vault_routing: str | None = None
    if config.vault.enabled and config.vault.root and config.vault.preload_routing:
        vault_routing = load_vault_routing(config.vault.root)

    system_prompt = build_system_prompt(
        config,
        memory_entries=memory_entries,
        is_resumed=is_resumed,
        session_digests=session_digests,
        feed_snapshot=feed_snapshot,
        vault_routing=vault_routing,
    )

    # Use session's messages list if persistent, else ephemeral
    messages: list = session.messages if session else []

    _info(f"kaori-agent  backend={config.backend.name}  model={config.backend.model}")
    _info(f"Tools: {', '.join(registry.names()) or '(none)'}")
    if session_store:
        _info(f"Session: {session.id[:8]}  (persistent)")
    else:
        _info("Session: ephemeral (set data_db in config for persistence)")
    if session_digests and session_digests.get("recent"):
        _info(f"Continuity: loaded {len(session_digests['recent'])} recent session summaries")
    if feed_snapshot:
        _info("Feed: loaded recent lifestyle context")
    if vault_routing:
        _info(f"Vault: loaded routing preamble from {config.vault.root}")
    _info("Type /quit to exit, /help for commands.\n")

    if _has_prompt_toolkit:
        history_path = config.user_data_dir / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_session: PromptSession = PromptSession(history=FileHistory(str(history_path)))
        async def _get_input() -> str:
            return await prompt_session.prompt_async("you> ")
    else:
        import asyncio
        async def _get_input() -> str:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: input("you> "))

    # Helper: rebuild tool registry when the active session changes
    def _rebuild_registry() -> ToolRegistry:
        reg = ToolRegistry()
        for tool in get_default_tools(
            session_store=session_store,
            session_id=session.id if session else None,
            disabled_tools=config.disabled_tools,
            on_memory_save=on_mem_save,
            vault_config=config.vault,
        ):
            reg.register(tool)
        if mcp_manager:
            for tool in mcp_manager.get_all_tools():
                reg.register(tool)
        return reg

    while True:
        try:
            user_input = await _get_input()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # --- Slash commands ---
        if user_input.startswith("/"):
            cmd = user_input.lower()

            if cmd in ("/quit", "/exit", "/q"):
                break

            elif cmd == "/help":
                _info("Commands:")
                _info("  /quit          Exit")
                _info("  /sessions      List saved sessions")
                _info("  /new           Start a new session")
                _info("  /resume [id]   Resume a previous session")
                _info("  /delete <id>   Delete a session")
                _info("  /title <text>  Set session title")
                _info("  /memory        Show persistent memory")
                _info("  /memory set <key> <value>")
                _info("  /memory delete <key>")
                _info("  /compact       Trigger transcript compaction")
                continue

            elif cmd == "/sessions":
                if not session_store:
                    _error("No session store configured (set data_db in config).")
                else:
                    await _cmd_sessions(session_store)
                continue

            elif cmd == "/new":
                if not session_store:
                    _error("No session store configured.")
                else:
                    # Close out the current session: title + summary
                    if session:
                        await session.auto_title()
                        _info("Summarizing current session...")
                        await _try_generate_summary(session, backend, config.max_tokens)
                    session = await session_store.create_session(
                        config.backend.name, config.backend.model
                    )
                    messages = session.messages
                    is_resumed = False
                    # Refresh injected context
                    memory_entries = await session_store.list_memory()
                    session_digests = await _build_session_digests(
                        session_store, session.id
                    )
                    feed_snapshot = await _get_feed_snapshot(config)
                    system_prompt = build_system_prompt(
                        config,
                        memory_entries=memory_entries,
                        is_resumed=False,
                        session_digests=session_digests,
                        feed_snapshot=feed_snapshot,
                        vault_routing=vault_routing,
                    )
                    registry = _rebuild_registry()
                    _info(f"New session: {session.id[:8]}")
                continue

            elif cmd.startswith("/resume"):
                if not session_store:
                    _error("No session store configured.")
                    continue
                parts = user_input.split(None, 1)
                if len(parts) < 2:
                    await _cmd_sessions(session_store)
                    _info("Usage: /resume <id-prefix>")
                    continue
                prefix = parts[1].strip()
                sessions_list = await session_store.list_sessions(limit=50)
                matches = [s for s in sessions_list if s["id"].startswith(prefix)]
                if not matches:
                    _error(f"No session found starting with '{prefix}'.")
                    continue
                if len(matches) > 1:
                    _error(f"Ambiguous prefix '{prefix}' — matches {len(matches)} sessions.")
                    continue
                # Close out the current session before switching
                if session:
                    await session.auto_title()
                    _info("Summarizing current session...")
                    await _try_generate_summary(session, backend, config.max_tokens)
                target = matches[0]
                try:
                    session = await session_store.load_session(target["id"])
                except ValueError as e:
                    _error(str(e))
                    continue
                messages = session.messages
                is_resumed = True
                memory_entries = await session_store.list_memory()
                session_digests = await _build_session_digests(
                    session_store, session.id
                )
                feed_snapshot = await _get_feed_snapshot(config)
                system_prompt = build_system_prompt(
                    config,
                    memory_entries=memory_entries,
                    is_resumed=True,
                    session_digests=session_digests,
                    feed_snapshot=feed_snapshot,
                    vault_routing=vault_routing,
                )
                registry = _rebuild_registry()
                title = session.title or "(untitled)"
                _info(f"Resumed session: {session.id[:8]} — {title} ({len(messages)} messages)")
                continue

            elif cmd.startswith("/delete"):
                if not session_store:
                    _error("No session store configured.")
                    continue
                parts = user_input.split(None, 1)
                if len(parts) < 2:
                    _error("Usage: /delete <id-prefix>")
                    continue
                prefix = parts[1].strip()
                sessions_list = await session_store.list_sessions(limit=50)
                matches = [s for s in sessions_list if s["id"].startswith(prefix)]
                if not matches:
                    _error(f"No session found starting with '{prefix}'.")
                elif len(matches) > 1:
                    _error(f"Ambiguous prefix '{prefix}'.")
                else:
                    target = matches[0]
                    if session and target["id"] == session.id:
                        _error("Cannot delete the current session. Use /new first.")
                    else:
                        await session_store.delete_session(target["id"])
                        _info(f"Deleted session {target['id'][:8]}.")
                continue

            elif cmd.startswith("/title"):
                if not session:
                    _error("No active session.")
                    continue
                title_text = user_input[len("/title"):].strip()
                if not title_text:
                    _error("Usage: /title <text>")
                    continue
                await session.set_title(title_text)
                _info(f"Title set: {title_text}")
                continue

            elif cmd == "/memory":
                if not session_store:
                    _error("No session store configured.")
                else:
                    await _cmd_memory(session_store)
                continue

            elif cmd.startswith("/memory set "):
                if not session_store:
                    _error("No session store configured.")
                else:
                    await _cmd_memory_set(session_store, user_input[len("/memory set "):])
                continue

            elif cmd.startswith("/memory delete "):
                if not session_store:
                    _error("No session store configured.")
                else:
                    await _cmd_memory_delete(session_store, user_input[len("/memory delete "):])
                continue

            elif cmd == "/compact":
                if not session:
                    _error("No active session.")
                elif not session_store:
                    _error("No session store configured.")
                else:
                    _info("Compacting...")
                    did_compact = await session.compact_if_needed(
                        backend, system_prompt, config.max_tokens,
                        threshold_pct=0,  # force compaction
                    )
                    if did_compact:
                        messages = session.get_effective_messages()
                        _info("Compaction complete.")
                    else:
                        _info("Nothing to compact.")
                continue

            else:
                _error(f"Unknown command: {user_input.split()[0]}. Type /help for commands.")
                continue

        # --- Normal message ---
        messages.append({"role": "user", "content": user_input})

        # Persist user message
        if session:
            await session.append_message("user", {"role": "user", "content": user_input})

        msg_count_before = len(messages)

        # Rebuild system prompt each turn so date/time stays current (digests + feed are cached)
        system_prompt = build_system_prompt(
            config,
            memory_entries=memory_entries,
            is_resumed=is_resumed,
            session_digests=session_digests,
            feed_snapshot=feed_snapshot,
            vault_routing=vault_routing,
        )

        try:
            await _handle_stream(
                backend, messages, registry.get_all(),
                system_prompt, config.backend.model, config.max_tokens,
            )
        except LLMError as e:
            _error(f"LLM error: {e}")
            messages.pop()
            continue
        except Exception as e:
            _error(f"Unexpected error: {e}")
            messages.pop()
            continue

        # Persist new messages added by engine (assistant + tool results)
        if session:
            new_messages = messages[msg_count_before:]
            for msg in new_messages:
                if isinstance(msg, dict):
                    role = msg.get("role", "assistant")
                    if role == "tool":
                        role = "tool_result"
                    elif isinstance(msg.get("content"), list):
                        first = msg["content"][0] if msg["content"] else {}
                        if isinstance(first, dict) and first.get("type") == "tool_result":
                            role = "tool_result"
                    await session.append_message(role, msg)

            # Auto-title after first exchange
            await session.auto_title()

            # Live memory refresh so the system prompt reflects anything the agent
            # saved during this turn (next turn's prompt will include it).
            memory_entries = await session_store.list_memory()

            # Check if compaction needed
            await session.compact_if_needed(
                backend, system_prompt, config.max_tokens,
                threshold_pct=config.auto_compact_threshold,
            )

    # --- Cleanup: title + summary before exit ---
    if session:
        await session.auto_title()
        await _try_generate_summary(session, backend, config.max_tokens)

    if mcp_manager:
        await mcp_manager.close()
