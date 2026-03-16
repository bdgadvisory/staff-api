from __future__ import annotations

import os
import time
from typing import Any

from openai import OpenAI

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    """Real OpenAI adapter (single-provider live path).

    Normalizes:
    - input: LLMCall(model, messages, temperature, max_tokens)
    - output: LLMResult(text, raw, provider, model, latency_ms, cost_estimate)

    Env:
      OPENAI_API_KEY (required)
      OPENAI_BASE_URL (optional)
      OPENAI_TIMEOUT_S (optional, default 20)
      OPENAI_MAX_RETRIES (optional, default 2)
    """

    name = "openai"

    def __init__(self, client: OpenAI | None = None):
        if client is not None:
            self._client = client
            return

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        base_url = os.environ.get("OPENAI_BASE_URL")
        timeout_s = float(os.environ.get("OPENAI_TIMEOUT_S", "20"))

        # OpenAI python client uses httpx under the hood; timeout is supported via `timeout`.
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)

    def complete(self, call: LLMCall) -> LLMResult:
        max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            start = time.time()
            try:
                # Use Responses API (primary OpenAI interface).
                # Convert OpenAI-style messages into Responses "input" message content blocks.
                input_msgs = []
                for m in call.messages:
                    role = m.get("role")
                    content = m.get("content") or ""
                    input_msgs.append(
                        {
                            "role": role,
                            "content": [{"type": "input_text", "text": content}],
                        }
                    )

                resp = self._client.responses.create(
                    model=call.model,
                    input=input_msgs,
                    temperature=call.temperature,
                    max_output_tokens=call.max_tokens,
                )

                text = (getattr(resp, "output_text", None) or "").strip()
                if not text:
                    # Fallback: try to extract text from output blocks if output_text isn't populated
                    try:
                        out_blocks = []
                        for item in getattr(resp, "output", []) or []:
                            for c in getattr(item, "content", []) or []:
                                if getattr(c, "type", None) in ("output_text", "text") and getattr(c, "text", None):
                                    out_blocks.append(c.text)
                        text = "\n".join(out_blocks).strip()
                    except Exception:
                        text = ""

                latency_ms = int((time.time() - start) * 1000)

                # Cost estimate: optional/approx (prices are governed elsewhere). Keep None for now.
                usage: Any = getattr(resp, "usage", None)
                raw = {
                    "id": getattr(resp, "id", None),
                    "created": getattr(resp, "created", None),
                    "usage": usage.model_dump() if hasattr(usage, "model_dump") else usage,
                }

                return LLMResult(
                    text=text,
                    raw=raw,
                    provider="openai",
                    model=call.model,
                    latency_ms=latency_ms,
                    cost_estimate=None,
                )

            except Exception as e:
                last_err = e
                # minimal retry for transient errors
                if attempt < max_retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                break

        raise RuntimeError(f"OpenAIAdapter.complete failed after retries: {last_err}")
