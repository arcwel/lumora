"""Anthropic (Claude) provider adapter.

Stubbed for the MVP scaffold — wire up the ``anthropic`` SDK in the marked
section to make it live.
"""

from __future__ import annotations

from app.config import settings
from app.providers.base import BaseProvider, ProviderResponse


class AnthropicProvider(BaseProvider):
    """Adapter for Anthropic Claude models."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key=api_key or settings.anthropic_api_key,
            model=model or "claude-sonnet-4-6",
        )

    async def query(self, prompt: str) -> ProviderResponse:
        if not self.is_configured():
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        # TODO: integrate the anthropic SDK, e.g.
        #   from anthropic import AsyncAnthropic
        #   client = AsyncAnthropic(api_key=self.api_key)
        #   msg = await client.messages.create(
        #       model=self.model, max_tokens=1024,
        #       messages=[{"role": "user", "content": prompt}])
        #   text = "".join(b.text for b in msg.content if b.type == "text")
        #   tokens = msg.usage.input_tokens + msg.usage.output_tokens
        #   return ProviderResponse(self.name, self.model, text, tokens)
        raise NotImplementedError("AnthropicProvider.query is a scaffold stub")
