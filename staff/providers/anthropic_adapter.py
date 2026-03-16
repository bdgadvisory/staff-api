from __future__ import annotations

import os
import time
from typing import Any

import anthropic

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class AnthropicAdapter(ProviderAdapter):
    """Real Anthropic adapter (editorial/review lane).

    Normalizes:
    - input: LLMCall(model, messages, temperature, max_tokens)
    - output: LLMResult

    Env:
      ANTHROPIC_API_KEY (required)
      ANTHROPIC_BASE_URL (optional)
      ANTHROPIC_TIMEOUT_S (optional, default 20)
      ANTHROPIC_MAX_RETRIES (optional, default 2)
    """

    name = "anthropic"

    def __init__(self, client: anthropic.Anthropic | None = None):
        if client is not None:
            self._client = client
            return

        if os.environ.get("STAFF_LIVE_MODE", "0") != "1":
            raise RuntimeError("AnthropicAdapter disabled (STAFF_LIVE_MODE != 1)")

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        timeout_s = float(os.environ.get("ANTHROPIC_TIMEOUT_S", "20"))

        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout_s)

    def complete(self, call: LLMCall) -> LLMResult:
        max_retries = int(os.environ.get("ANTHROPIC_MAX_RETRIES", "2"))

        # Convert OpenAI-style messages into Anthropic Messages API.
        system_parts = [m.get("content", "") for m in call.messages if m.get("role") == "system"]
        system = "\n\n".join([p for p in system_parts if p]).strip() or None

        msgs = []
        for m in call.messages:
            role = m.get("role")
            if role == "system":
                continue
            if role not in ("user", "assistant"):
                # Treat unknown roles as user input
                role = "user"
            msgs.append({"role": role, "content": m.get("content", "")})

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            start = time.time()
            try:
                resp = self._client.messages.create(
                    model=call.model,
                    system=system,
                    messages=msgs,
                    max_tokens=call.max_tokens,
                    temperature=call.temperature,
                )

                # Extract text blocks
                chunks = []
                for b in resp.content:
                    if getattr(b, "type", None) == "text" and getattr(b, "text", None):
                        chunks.append(b.text)
                text = "\n".join(chunks).strip()

                latency_ms = int((time.time() - start) * 1000)

                usage: Any = getattr(resp, "usage", None)
                raw = {
                    "id": getattr(resp, "id", None),
                    "model": getattr(resp, "model", None),
                    "usage": usage.model_dump() if hasattr(usage, "model_dump") else usage,
                    "stop_reason": getattr(resp, "stop_reason", None),
                }

                return LLMResult(
                    text=text,
                    raw=raw,
                    provider="anthropic",
                    model=call.model,
                    latency_ms=latency_ms,
                    cost_estimate=None,
                )

            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                break

        raise RuntimeError(f"AnthropicAdapter.complete failed after retries: {last_err}")
