from __future__ import annotations

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    def __init__(self, client: object | None = None):
        self._client = client

    def complete(self, call: LLMCall) -> LLMResult:
        # Scaffold. Wire to Anthropic SDK in production.
        raise NotImplementedError("AnthropicAdapter.complete: wire provider SDK")
