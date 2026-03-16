from __future__ import annotations

import time

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class MockAdapter(ProviderAdapter):
    """Local testing adapter.

    Produces deterministic text without calling external providers.
    Useful for wiring retrieval/prompt/audit paths end-to-end.
    """

    def __init__(self, name: str):
        self.name = name

    def complete(self, call: LLMCall) -> LLMResult:
        start = time.time()
        user = "\n\n".join([m["content"] for m in call.messages if m["role"] == "user"])
        txt = (
            f"[MOCK:{self.name}:{call.model}]\n"
            f"temperature={call.temperature} max_tokens={call.max_tokens}\n"
            f"--- user ---\n{user[:2000]}\n"
        )
        return LLMResult(
            text=txt,
            raw={"mock": True},
            provider=self.name,
            model=call.model,
            latency_ms=int((time.time() - start) * 1000),
            cost_estimate=0.0,
        )
