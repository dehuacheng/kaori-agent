"""Tests for config loading."""

import os

import pytest
import yaml

from kaori_agent.config import Config, _load_config, reset_config


@pytest.fixture(autouse=True)
def _clean_config():
    """Reset cached config before/after each test."""
    reset_config()
    yield
    reset_config()


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point user_data_dir to a temp directory."""
    monkeypatch.setattr("kaori_agent.config.Config.__post_init__", lambda self: None, raising=False)
    # Patch the default user_data_dir
    monkeypatch.setattr(
        "kaori_agent.config.Config.__dataclass_fields__",
        {
            **Config.__dataclass_fields__,
        },
    )
    # Simpler approach: just write YAML and load manually
    return tmp_path


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)


class TestDefaults:
    def test_default_backend_is_deepseek(self, monkeypatch):
        monkeypatch.delenv("KAORI_AGENT_BACKEND", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # With no YAML and no env, defaults should apply
        config = Config()
        assert config.backend.name == "deepseek"
        assert config.backend.type == "openai"
        assert config.max_tokens == 4096

    def test_default_system_prompt(self):
        config = Config()
        assert "personal assistant" in config.system_prompt.lower()


class TestYAMLLoading:
    def test_loads_backend_from_yaml(self, config_dir, monkeypatch):
        yaml_path = config_dir / "config.yaml"
        _write_yaml(yaml_path, {
            "backend": "kimi",
            "kimi": {"model": "moonshot-v1-32k"},
            "max_tokens": 8192,
            "system_prompt": "You are Kaori.",
        })
        original_init = Config.__init__

        def patched_init(self, **kwargs):
            original_init(self, **kwargs)
            self.user_data_dir = config_dir

        monkeypatch.setattr(Config, "__init__", patched_init)

        config = _load_config()
        assert config.backend.name == "kimi"
        assert config.backend.model == "moonshot-v1-32k"
        assert config.max_tokens == 8192
        assert config.system_prompt == "You are Kaori."

    def test_personality_file(self, config_dir, monkeypatch):
        personality = config_dir / "personality.md"
        personality.write_text("I am a custom assistant.\nI like code.")

        yaml_path = config_dir / "config.yaml"
        _write_yaml(yaml_path, {
            "backend": "deepseek",
            "personality_file": str(personality),
        })

        original_init = Config.__init__

        def patched_init(self, **kwargs):
            original_init(self, **kwargs)
            self.user_data_dir = config_dir

        monkeypatch.setattr(Config, "__init__", patched_init)

        config = _load_config()
        assert "custom assistant" in config.system_prompt


class TestEnvOverrides:
    def test_env_overrides_model(self, config_dir, monkeypatch):
        monkeypatch.setenv("KAORI_AGENT_MODEL", "my-custom-model")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

        original_init = Config.__init__

        def patched_init(self, **kwargs):
            original_init(self, **kwargs)
            self.user_data_dir = config_dir

        monkeypatch.setattr(Config, "__init__", patched_init)

        config = _load_config()
        assert config.backend.model == "my-custom-model"

    def test_env_switches_backend(self, config_dir, monkeypatch):
        monkeypatch.setenv("KAORI_AGENT_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        original_init = Config.__init__

        def patched_init(self, **kwargs):
            original_init(self, **kwargs)
            self.user_data_dir = config_dir

        monkeypatch.setattr(Config, "__init__", patched_init)

        config = _load_config()
        assert config.backend.name == "anthropic"
        assert config.backend.type == "anthropic"
        assert config.backend.api_key == "sk-ant-test"

    def test_api_key_from_env(self, config_dir, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

        original_init = Config.__init__

        def patched_init(self, **kwargs):
            original_init(self, **kwargs)
            self.user_data_dir = config_dir

        monkeypatch.setattr(Config, "__init__", patched_init)

        config = _load_config()
        assert config.backend.api_key == "sk-ds-test"
