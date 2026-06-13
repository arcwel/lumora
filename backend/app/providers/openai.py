"""OpenAI (ChatGPT) provider adapter.

The actual SDK call is intentionally left as a stub for the MVP scaffold so
the project imports cleanly without network access or an installed key. Wire
up the ``openai`` SDK in the marked section to make it live.
"""

from __future__ import annotations

from app.config import settings
from app.providers.base import BaseProvider, ProviderResponse


class OpenAIProvider(BaseProvider):
    """Adapter for OpenAI chat completion / responses models."""

    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key=api_key or settings.openai_api_key,
            model=model or settings.default_provider_model,
        )

    async def query(self, prompt: str) -> ProviderResponse:
        if not self.is_configured():
            raise RuntimeError("OPENAI_API_KEY is not configured")

        # TODO: integrate the openai SDK, e.g.
        #   from openai import AsyncOpenAI
        #   client = AsyncOpenAI(api_key=self.api_key)
        #   resp = await client.responses.create(model=self.model, input=prompt)
        #   return ProviderResponse(self.name, self.model, resp.output_text,
        #                           resp.usage.total_tokens)
        raise NotImplementedError("OpenAIProvider.query is a scaffold stub")
