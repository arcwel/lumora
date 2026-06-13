"""Provider adapter registry.

Concrete adapters register here so the scheduler can resolve a provider by its
stable name. Perplexity is reserved for a future adapter (key already present
in ``.env.example``).
"""

from __future__ import annotations

from app.providers.anthropic import AnthropicProvider
from app.providers.base import BaseProvider, ProviderError, ProviderResponse
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


def provider_name_for_model(model: str) -> str:
    """Map a model id to its provider name by well-known prefixes.

    Falls back to ``"anthropic"`` (the cheapest Haiku-class default) so an
    unrecognized model still routes somewhere sensible.
    """

    name = model.lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if name.startswith("gemini"):
        return "gemini"
    return "anthropic"


def provider_for_model(model: str, **kwargs) -> BaseProvider:
    """Instantiate the provider adapter that serves ``model``."""

    return get_provider(provider_name_for_model(model), model=model, **kwargs)


__all__ = [
    "AnthropicProvider",
    "BaseProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "PROVIDER_REGISTRY",
    "ProviderError",
    "ProviderResponse",
    "get_provider",
    "provider_for_model",
    "provider_name_for_model",
]
