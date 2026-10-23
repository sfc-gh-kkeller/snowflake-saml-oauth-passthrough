"""LLM provider factory."""
from typing import Optional
from .base import LLMProvider
from ...core.config import settings


def get_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """Create an LLM provider instance based on config or explicit name."""
    name = provider_name or settings.agent_provider

    if name == "cortex":
        from .cortex import CortexAgentClient
        return CortexAgentClient()
    elif name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {name}. Supported: cortex, openai, anthropic, ollama")
