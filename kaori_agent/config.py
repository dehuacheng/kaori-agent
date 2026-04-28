"""Configuration loading: defaults -> ~/.kaori-agent/config.yaml -> env vars."""

from dataclasses import dataclass, field
from pathlib import Path
import os

import yaml
from dotenv import load_dotenv

load_dotenv()

# Known backend defaults: base_url and env var name for API key
BACKEND_DEFAULTS: dict[str, dict] = {
    "deepseek": {"type": "openai", "base_url": "https://api.deepseek.com", "env_key": "DEEPSEEK_API_KEY", "model": "deepseek-chat"},
    "kimi": {"type": "openai", "base_url": "https://api.moonshot.cn/v1", "env_key": "KIMI_API_KEY", "model": "moonshot-v1-128k"},
    "openai": {"type": "openai", "base_url": "https://api.openai.com/v1", "env_key": "OPENAI_API_KEY", "model": "gpt-4o"},
    "anthropic": {"type": "anthropic", "env_key": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-6"},
}

_DEFAULT_SYSTEM_PROMPT = "You are a helpful personal assistant."


@dataclass
class BackendConfig:
    """Resolved configuration for the active LLM backend."""
    name: str                    # e.g. "deepseek", "kimi", "anthropic"
    type: str                    # "openai" or "anthropic"
    api_key: str | None = None
    base_url: str | None = None  # only for openai-compat backends
    model: str = ""


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server to connect to."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class FeedContextConfig:
    """Configuration for injecting recent kaori feed data into the system prompt."""
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8000"
    token: str | None = None


@dataclass
class VaultConfig:
    """Configuration for the Obsidian vault knowledge backend (read-only)."""
    enabled: bool = False
    root: Path | None = None
    exclude_paths: list[str] = field(default_factory=list)  # relative to root, soft-excluded from search
    preload_routing: bool = True                             # inject AGENTS.md + INDEX.md into system prompt


@dataclass
class Config:
    """Top-level agent configuration."""
    backend: BackendConfig = field(default_factory=lambda: BackendConfig(name="deepseek", type="openai", model="deepseek-chat"))
    max_tokens: int = 4096
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    personality_file: str | None = None
    user_data_dir: Path = field(default_factory=lambda: Path.home() / ".kaori-agent")
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    # Phase 4: Session persistence
    data_db: Path | None = None              # path to kaori.db (or any SQLite DB)
    auto_compact_threshold: int = 80         # % of context window to trigger compaction
    disabled_tools: list[str] = field(default_factory=list)  # tool names to exclude
    feed_context: FeedContextConfig = field(default_factory=FeedContextConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)


_config: Config | None = None


def _parse_vault_block(yaml_data: dict, cfg: VaultConfig) -> VaultConfig:
    """Apply the `vault:` block from a parsed YAML dict onto a VaultConfig."""
    vault_yaml = yaml_data.get("vault")
    if not isinstance(vault_yaml, dict):
        return cfg
    cfg.enabled = bool(vault_yaml.get("enabled", False))
    if "root" in vault_yaml:
        cfg.root = Path(vault_yaml["root"]).expanduser()
    if "exclude_paths" in vault_yaml:
        cfg.exclude_paths = list(vault_yaml["exclude_paths"])
    if "preload_routing" in vault_yaml:
        cfg.preload_routing = bool(vault_yaml["preload_routing"])
    return cfg


def load_vault_config(yaml_path: Path | None = None) -> VaultConfig:
    """Load just the `vault:` block from the kaori-agent config YAML.

    Decoupled from the full `Config` singleton so that callers like the kaori
    backend (which has its own backend resolution path — see
    `kaori.llm.agent_backend._load_kaori_agent_config`) can pull vault settings
    without paying the full config-load cost or coupling to env-var overrides.
    """
    cfg = VaultConfig()
    path = yaml_path or (Path.home() / ".kaori-agent" / "config.yaml")
    if not path.exists():
        return cfg
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return cfg
    return _parse_vault_block(data, cfg)


def get_config() -> Config:
    """Return the cached config singleton, loading on first call."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def reset_config() -> None:
    """Clear the cached config (useful for testing)."""
    global _config
    _config = None


def _load_config() -> Config:
    config = Config()

    # --- Layer 2: YAML file ---
    yaml_path = config.user_data_dir / "config.yaml"
    yaml_data: dict = {}
    if yaml_path.exists():
        with open(yaml_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Common settings from YAML
    if "max_tokens" in yaml_data:
        config.max_tokens = int(yaml_data["max_tokens"])
    if "system_prompt" in yaml_data:
        config.system_prompt = yaml_data["system_prompt"]
    if "personality_file" in yaml_data:
        config.personality_file = yaml_data["personality_file"]
    if "data_db" in yaml_data:
        config.data_db = Path(yaml_data["data_db"]).expanduser()
    if "auto_compact_threshold" in yaml_data:
        config.auto_compact_threshold = int(yaml_data["auto_compact_threshold"])
    if "disabled_tools" in yaml_data:
        config.disabled_tools = list(yaml_data["disabled_tools"])

    # Resolve backend
    backend_name = yaml_data.get("backend", "deepseek")
    defaults = BACKEND_DEFAULTS.get(backend_name, {})
    backend_yaml = yaml_data.get(backend_name, {}) if isinstance(yaml_data.get(backend_name), dict) else {}

    config.backend = BackendConfig(
        name=backend_name,
        type=backend_yaml.get("type", defaults.get("type", "openai")),
        base_url=backend_yaml.get("base_url", defaults.get("base_url")),
        model=backend_yaml.get("model", defaults.get("model", "")),
    )

    # API key: backend-specific YAML -> env var
    if "api_key" in backend_yaml:
        config.backend.api_key = backend_yaml["api_key"]
    else:
        env_key = defaults.get("env_key", f"{backend_name.upper()}_API_KEY")
        config.backend.api_key = os.environ.get(env_key)

    # --- Layer 3: Env var overrides ---
    if v := os.environ.get("KAORI_AGENT_BACKEND"):
        # Full backend switch via env var
        new_defaults = BACKEND_DEFAULTS.get(v, {})
        config.backend.name = v
        config.backend.type = new_defaults.get("type", "openai")
        config.backend.base_url = new_defaults.get("base_url")
        config.backend.model = new_defaults.get("model", config.backend.model)
        env_key = new_defaults.get("env_key", f"{v.upper()}_API_KEY")
        config.backend.api_key = os.environ.get(env_key, config.backend.api_key)
    if v := os.environ.get("KAORI_AGENT_MODEL"):
        config.backend.model = v
    if v := os.environ.get("KAORI_AGENT_MAX_TOKENS"):
        config.max_tokens = int(v)

    # --- MCP servers ---
    for name, server_data in yaml_data.get("mcp_servers", {}).items():
        if not isinstance(server_data, dict):
            continue
        config.mcp_servers.append(MCPServerConfig(
            name=name,
            command=server_data.get("command", ""),
            args=server_data.get("args", []),
            cwd=server_data.get("cwd"),
            env=server_data.get("env", {}),
        ))

    # --- Feed context ---
    feed_yaml = yaml_data.get("feed_context")
    if isinstance(feed_yaml, dict):
        config.feed_context.enabled = bool(feed_yaml.get("enabled", False))
        config.feed_context.base_url = feed_yaml.get(
            "base_url", config.feed_context.base_url
        )
        token = feed_yaml.get("token")
        if not token:
            # Fall back to KAORI_API_TOKEN from the kaori MCP server env
            for srv in config.mcp_servers:
                if srv.name == "kaori":
                    token = srv.env.get("KAORI_API_TOKEN")
                    break
        if not token:
            token = os.environ.get("KAORI_API_TOKEN")
        config.feed_context.token = token

    # --- Vault ---
    _parse_vault_block(yaml_data, config.vault)

    # --- Resolve personality file ---
    if config.personality_file:
        p = Path(config.personality_file).expanduser()
        if p.exists():
            config.system_prompt = p.read_text().strip()

    return config
