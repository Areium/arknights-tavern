"""Provider adapters — abstract LLM API differences across platforms."""

from .base import ProviderAdapter
from .openai import OpenAIAdapter
from .deepseek import DeepSeekAdapter

_adapter_registry: dict[str, type[ProviderAdapter]] = {
    "openai": OpenAIAdapter,
    "deepseek": DeepSeekAdapter,
}

# Lazy imports for heavier adapters
def _get_anthropic():
    from .anthropic import AnthropicAdapter
    return AnthropicAdapter

def _get_gemini():
    from .gemini import GeminiAdapter
    return GeminiAdapter

_LazyRegistry: dict[str, callable] = {
    "anthropic": _get_anthropic,
    "gemini": _get_gemini,
}


def get_adapter(provider: str, **kwargs) -> ProviderAdapter | None:
    """Factory: return a ProviderAdapter instance for the given provider key.

    Supported keys: openai, deepseek, anthropic, gemini, auto.
    ``auto`` returns an OpenAI adapter (the default for OpenAI-compatible APIs).
    """
    key = provider.lower().strip() or "auto"
    if key == "auto":
        key = "openai"

    if key in _adapter_registry:
        return _adapter_registry[key](**kwargs)

    if key in _LazyRegistry:
        return _LazyRegistry[key]()(**kwargs)

    return None
