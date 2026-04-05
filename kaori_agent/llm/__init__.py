"""LLM backend factory."""

from kaori_agent.config import BackendConfig
from kaori_agent.llm.base import LLMBackend, LLMError


def get_backend(backend_config: BackendConfig) -> LLMBackend:
    """Create an LLM backend instance from config."""
    if not backend_config.api_key:
        raise LLMError(
            f"No API key for backend '{backend_config.name}'. "
            f"Set it in ~/.kaori-agent/config.yaml or via environment variable."
        )

    if backend_config.type == "anthropic":
        from kaori_agent.llm.anthropic_backend import AnthropicBackend
        return AnthropicBackend(api_key=backend_config.api_key)

    # Default: openai-compatible
    from kaori_agent.llm.openai_backend import OpenAIBackend
    if not backend_config.base_url:
        raise LLMError(
            f"No base_url for OpenAI-compatible backend '{backend_config.name}'."
        )
    return OpenAIBackend(
        api_key=backend_config.api_key,
        base_url=backend_config.base_url,
        name=backend_config.name,
    )
