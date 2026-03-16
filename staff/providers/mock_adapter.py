from __future__ import annotations

import time

from staff.llm_router.types import LLMResult
from staff.providers.base import LLMCall, ProviderAdapter


class MockAdapter(ProviderAdapter):
    """Deterministic testing adapter.

    Controlled entirely via `behavior` dict + call.metadata.

    behavior keys:
      - default_prefix: str
      - by_step_type: {step_type: {text: str}}
      - by_step_id: {step_id: {text: str}}
      - qa_status_by_step_id: {step_id: "PASS"|"PASS_WITH_WARNINGS"|"REWRITE_REQUIRED"|"ESCALATE_TO_HUMAN"}
      - failures_by_step_id: {step_id: {times: int, error: "rate_limit"|"overloaded"|"timeout", retry_after_s: float}}
      - inject_disagreement: bool (adds marker)

    The executor supplies metadata: workflow_id, step_id, step_type, department, task_type.
    """

    def __init__(self, name: str, behavior: dict | None = None):
        self.name = name
        self.behavior = behavior or {}

    def complete(self, call: LLMCall) -> LLMResult:
        start = time.time()
        md = call.metadata or {}
        step_id = str(md.get("step_id") or "")
        step_type = str(md.get("step_type") or "")

        # Deterministic failure injection (rate-limit/overload simulation)
        failures = (self.behavior.get("failures_by_step_id") or {}).get(step_id)
        if failures:
            times = int(failures.get("times") or 0)
            key = f"__fail_count__:{step_id}"
            so_far = int(self.behavior.get(key) or 0)
            if so_far < times:
                self.behavior[key] = so_far + 1

                class _MockHTTPError(RuntimeError):
                    def __init__(self, msg: str, status_code: int, retry_after_s: float | None):
                        super().__init__(msg)
                        self.status_code = status_code
                        self.retry_after_s = retry_after_s

                err = str(failures.get("error") or "rate_limit")
                retry_after_s = failures.get("retry_after_s")
                if err == "rate_limit":
                    raise _MockHTTPError("429 rate limit (mock)", 429, retry_after_s)
                if err == "overloaded":
                    raise _MockHTTPError("503 overloaded (mock)", 503, retry_after_s)
                if err == "timeout":
                    raise TimeoutError("timeout (mock)")
                raise RuntimeError(f"mock failure: {err}")

        # Priority: by_step_id -> by_step_type -> QA status helper -> default echo
        by_step_id = (self.behavior.get("by_step_id") or {}).get(step_id)
        if by_step_id and "text" in by_step_id:
            text = str(by_step_id["text"])
        else:
            by_step_type = (self.behavior.get("by_step_type") or {}).get(step_type)
            if by_step_type and "text" in by_step_type:
                text = str(by_step_type["text"])
            else:
                qa_status = (self.behavior.get("qa_status_by_step_id") or {}).get(step_id)
                if qa_status:
                    text = f"{qa_status}: mock critique output for {step_id}"
                else:
                    user = "\n\n".join([m["content"] for m in call.messages if m["role"] == "user"])
                    prefix = self.behavior.get("default_prefix") or "[MOCK]"
                    text = (
                        f"{prefix} provider={self.name} model={call.model} step_type={step_type} step_id={step_id}\n"
                        f"temperature={call.temperature} max_tokens={call.max_tokens}\n"
                        f"--- user ---\n{user[:1200]}\n"
                    )

        if self.behavior.get("inject_disagreement"):
            text += "\n[MOCK_DISAGREEMENT_MARKER]"

        return LLMResult(
            text=text,
            raw={"mock": True, "metadata": md},
            provider=self.name,
            model=call.model,
            latency_ms=int((time.time() - start) * 1000),
            cost_estimate=0.0,
        )
