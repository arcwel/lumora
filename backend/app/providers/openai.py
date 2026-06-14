"""OpenAI (ChatGPT) provider adapter.

Wraps the official ``openai`` SDK behind the vendor-agnostic ``BaseProvider``
interface. Defaults to ``gpt-4o-mini`` for cost efficiency; the model is
configurable per instance or via ``DEFAULT_PROVIDER_MODEL``.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.providers.base import (
    DEFAULT_TIMEOUT_SECONDS,
    BaseProvider,
    ProviderError,
    ProviderResponse,
)

logger = logging.getLogger(__name__)

#: Cheap, capable default. Override per-instance or via settings.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAIProvider(BaseProvider):
    """Adapter for OpenAI chat completion models."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        max_tokens: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            api_key=api_key or settings.openai_api_key,
            model=model or settings.default_provider_model or DEFAULT_OPENAI_MODEL,
        )
        self.max_tokens = max_tokens if max_tokens is not None else settings.default_max_tokens
        self.timeout = timeout

    async def query(self, prompt: str) -> ProviderResponse:
        if not self.is_configured():
            raise ProviderError("OPENAI_API_KEY is not configured")

        # Imported lazily so the package imports without the SDK installed.
        from openai import (
            APIError,
            APITimeoutError,
            AsyncOpenAI,
            RateLimitError,
        )

        client = AsyncOpenAI(api_key=self.api_key, timeout=self.timeout)
        try:
            # The SDK retries 429/5xx with exponential backoff by default.
            resp = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
            )
        except RateLimitError as exc:
            raise ProviderError(f"OpenAI rate limit exceeded: {exc}") from exc
        except APITimeoutError as exc:
            raise ProviderError(f"OpenAI request timed out after {self.timeout}s: {exc}") from exc
        except APIError as exc:
            raise ProviderError(f"OpenAI API error: {exc}") from exc
        finally:
            await client.close()

        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content or "").strip() if choice else ""
        tokens = resp.usage.total_tokens if resp.usage else None
        return ProviderResponse(self.name, self.model, text, tokens)
