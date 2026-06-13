"""Abstract LLM provider interface.

Each concrete provider adapter wraps a vendor SDK and returns a normalized
``ProviderResponse`` so the rest of the pipeline is vendor-agnostic.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(slots=True)
class ProviderResponse:
    """Normalized result of querying a provider with a single prompt."""

    provider: str
    model: str
    text: str
    token_count: int | None = None


class BaseProvider(abc.ABC):
    """Common interface implemented by every provider adapter."""

    #: Stable, lowercase identifier, e.g. ``"openai"``.
    name: str

    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @abc.abstractmethod
    async def query(self, prompt: str) -> ProviderResponse:
        """Send ``prompt`` to the provider and return a normalized response."""

    def is_configured(self) -> bool:
        """Return ``True`` when an API key is present for this provider."""

        return bool(self.api_key)
