"""Provider adapter registry.

Concrete adapters register here so the scheduler can resolve a provider by its
stable name. Perplexity is reserved for a future adapter (key already present
in ``.env.example``).
"""

from __future__ import annotations

from app.providers.anthropic import AnthropicProvider
from app.providers.base import BaseProvider, ProviderResponse
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider

PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    OpenAIProvider.name: OpenAIProvider,
    AnthropicProvider.name: AnthropicProvider,
    GeminiProvider.name: GeminiProvider,
}


def get_provider(name: str, **kwargs) -> BaseProvider:
    """Instantiate a provider adapter by its registered ``name``."""

    try:
        provider_cls = PROVIDER_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {name!r}") from exc
    return provider_cls(**kwargs)


__all__ = [
    "AnthropicProvider",
    "BaseProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "PROVIDER_REGISTRY",
    "ProviderResponse",
    "get_provider",
]
