"""Interactive CLI REPL for kaori-agent."""

import sys

from kaori_agent.config import get_config
from kaori_agent.engine import run_turn_stream
from kaori_agent.llm import get_backend
from kaori_agent.llm.base import LLMError
from kaori_agent.prompt import build_system_prompt
from kaori_agent.tool_registry import ToolRegistry
from kaori_agent.tools import get_default_tools

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

    registry = ToolRegistry()
    for tool in get_default_tools():
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

    system_prompt = build_system_prompt(config)
    messages: list = []

    _info(f"kaori-agent  backend={config.backend.name}  model={config.backend.model}")
    _info(f"Tools: {', '.join(registry.names()) or '(none)'}")
    _info("Type /quit to exit.\n")

    if _has_prompt_toolkit:
        history_path = config.user_data_dir / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        session: PromptSession = PromptSession(history=FileHistory(str(history_path)))
        async def _get_input() -> str:
            return await session.prompt_async("you> ")
    else:
        import asyncio
        async def _get_input() -> str:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: input("you> "))

    while True:
        try:
            user_input = await _get_input()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            break

        messages.append({"role": "user", "content": user_input})

        try:
            await _handle_stream(
                backend, messages, registry.get_all(),
                system_prompt, config.backend.model, config.max_tokens,
            )
        except LLMError as e:
            _error(f"LLM error: {e}")
            messages.pop()
        except Exception as e:
            _error(f"Unexpected error: {e}")
            messages.pop()

    # Cleanup MCP connections
    if mcp_manager:
        await mcp_manager.close()
