"""Anthropic (Claude) provider adapter.

Wraps the official ``anthropic`` SDK behind the vendor-agnostic
``BaseProvider`` interface. Defaults to Claude Haiku 4.5 — cheap and fast,
which makes it a good fit for both answer capture and LLM-as-judge scoring.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.providers.base import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    BaseProvider,
    ProviderError,
    ProviderResponse,
)

logger = logging.getLogger(__name__)

#: Cheapest/fastest current Claude model.
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


class AnthropicProvider(BaseProvider):
    """Adapter for Anthropic Claude models."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            api_key=api_key or settings.anthropic_api_key,
            model=model or DEFAULT_ANTHROPIC_MODEL,
        )
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def query(self, prompt: str) -> ProviderResponse:
        if not self.is_configured():
            raise ProviderError("ANTHROPIC_API_KEY is not configured")

        from anthropic import (
            APIError,
            APITimeoutError,
            AsyncAnthropic,
            RateLimitError,
        )

        client = AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
        try:
            # The SDK retries 429/5xx with exponential backoff by default.
            msg = await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except RateLimitError as exc:
            raise ProviderError(f"Anthropic rate limit exceeded: {exc}") from exc
        except APITimeoutError as exc:
            raise ProviderError(
                f"Anthropic request timed out after {self.timeout}s: {exc}"
            ) from exc
        except APIError as exc:
            raise ProviderError(f"Anthropic API error: {exc}") from exc
        finally:
            await client.close()

        text = "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        ).strip()
        tokens = None
        if msg.usage is not None:
            tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
        return ProviderResponse(self.name, self.model, text, tokens)
