from __future__ import annotations

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class GeminiAdapter(ProviderAdapter):
    name = "google"

    def __init__(self, client: object | None = None):
        self._client = client

    def complete(self, call: LLMCall) -> LLMResult:
        # Scaffold. Wire to Gemini SDK / Vertex AI in production.
        raise NotImplementedError("GeminiAdapter.complete: wire provider SDK")
