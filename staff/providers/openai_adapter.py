from __future__ import annotations

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    name = "openai"

    def __init__(self, client: object | None = None):
        self._client = client  # inject real SDK client in production

    def complete(self, call: LLMCall) -> LLMResult:
        # NOTE: scaffold only. Wire to OpenAI Responses/Chat API in production.
        raise NotImplementedError("OpenAIAdapter.complete: wire provider SDK")
