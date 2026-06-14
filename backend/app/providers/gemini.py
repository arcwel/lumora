"""Google Gemini provider adapter.

Wraps the official ``google-genai`` SDK (the current unified client, *not* the
legacy ``google-generativeai`` package) behind the vendor-agnostic
``BaseProvider`` interface. Defaults to ``gemini-2.5-flash`` (``2.0-flash`` was
retired by Google and now returns 404).
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

#: ``gemini-2.0-flash`` was retired (404); 2.5-flash is the current cheap model.
#: Note it is a reasoning model that spends hidden "thinking" tokens, so the
#: max-token budget must stay high enough to fit thinking + the visible answer.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class GeminiProvider(BaseProvider):
    """Adapter for Google Gemini models."""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        max_tokens: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            api_key=api_key or settings.google_api_key,
            model=model or DEFAULT_GEMINI_MODEL,
        )
        self.max_tokens = max_tokens if max_tokens is not None else settings.default_max_tokens
        self.timeout = timeout

    async def query(self, prompt: str) -> ProviderResponse:
        if not self.is_configured():
            raise ProviderError("GOOGLE_API_KEY is not configured")

        from google import genai
        from google.genai import errors as genai_errors

        # http_options.timeout is in milliseconds.
        client = genai.Client(
            api_key=self.api_key,
            http_options={"timeout": int(self.timeout * 1000)},
        )
        try:
            resp = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"max_output_tokens": self.max_tokens},
            )
        except genai_errors.APIError as exc:
            # ClientError (4xx incl. 429) and ServerError (5xx) subclass APIError.
            raise ProviderError(f"Gemini API error: {exc}") from exc
        except (TimeoutError, ConnectionError) as exc:
            raise ProviderError(
                f"Gemini request failed after {self.timeout}s: {exc}"
            ) from exc

        text = (resp.text or "").strip()
        tokens = None
        if resp.usage_metadata is not None:
            tokens = resp.usage_metadata.total_token_count
        return ProviderResponse(self.name, self.model, text, tokens)
