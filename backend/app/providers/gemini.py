"""Google Gemini provider adapter.

Stubbed for the MVP scaffold — wire up the ``google-genai`` SDK in the marked
section to make it live.
"""

from __future__ import annotations

from app.config import settings
from app.providers.base import BaseProvider, ProviderResponse


class GeminiProvider(BaseProvider):
    """Adapter for Google Gemini models."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key=api_key or settings.google_api_key,
            model=model or "gemini-2.0-flash",
        )

    async def query(self, prompt: str) -> ProviderResponse:
        if not self.is_configured():
            raise RuntimeError("GOOGLE_API_KEY is not configured")

        # TODO: integrate the google-genai SDK, e.g.
        #   from google import genai
        #   client = genai.Client(api_key=self.api_key)
        #   resp = await client.aio.models.generate_content(
        #       model=self.model, contents=prompt)
        #   tokens = resp.usage_metadata.total_token_count
        #   return ProviderResponse(self.name, self.model, resp.text, tokens)
        raise NotImplementedError("GeminiProvider.query is a scaffold stub")
