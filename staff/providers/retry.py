from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any


class RetryableProviderError(Exception):
    """Raised (or wrapped) when a provider error is retryable.

    This is an internal normalization type so workflow/executor logic can be provider-agnostic.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str | None = None,
        error_type: str = "unknown",
        http_status: int | None = None,
        retry_after_s: float | None = None,
        raw: Any = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.error_type = error_type
        self.http_status = http_status
        self.retry_after_s = retry_after_s
        self.raw = raw


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 6
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    jitter: float = 0.25
    respect_retry_after: bool = True


def _extract_retry_after_seconds(exc: Exception) -> float | None:
    # Best-effort: some SDK exceptions carry headers/response metadata.
    for attr in ("retry_after", "retry_after_seconds", "retry_after_s"):
        v = getattr(exc, attr, None)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    # Common pattern: exc.response.headers.get('retry-after')
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if headers and hasattr(headers, "get"):
        ra = headers.get("retry-after") or headers.get("Retry-After")
        if ra:
            try:
                return float(ra)
            except Exception:
                return None
    return None


def is_retryable_error(exc: Exception) -> tuple[bool, dict[str, Any]]:
    """Classify an exception as retryable overload/rate-limit/temporary capacity.

    Returns: (retryable, meta)
    meta: {http_status, error_type, retry_after_s}
    """

    msg = (str(exc) or "").lower()

    http_status = getattr(exc, "status_code", None)
    if http_status is None:
        http_status = getattr(getattr(exc, "response", None), "status_code", None)

    retry_after_s = _extract_retry_after_seconds(exc)

    # Status-based
    if http_status in (429, 503, 502, 504):
        return True, {
            "http_status": int(http_status),
            "error_type": "http_%s" % http_status,
            "retry_after_s": retry_after_s,
        }

    # Network / timeout strings (SDK-agnostic)
    transient_markers = [
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "temporary",
        "try again",
        "overloaded",
        "capacity",
        "rate limit",
        "too many requests",
        "throttl",
        "server is busy",
    ]
    if any(m in msg for m in transient_markers):
        return True, {
            "http_status": http_status,
            "error_type": "transient",
            "retry_after_s": retry_after_s,
        }

    return False, {"http_status": http_status, "error_type": "non_retryable", "retry_after_s": retry_after_s}


def compute_backoff(policy: RetryPolicy, attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter; respects Retry-After when available."""

    # attempt is 0-based (first retry attempt == 0)
    exp = min(policy.max_delay_s, policy.base_delay_s * (2 ** attempt))

    if policy.respect_retry_after and retry_after and retry_after > 0:
        exp = max(exp, float(retry_after))

    # jitter in range [1-jitter, 1+jitter]
    j = policy.jitter
    factor = 1.0
    if j and j > 0:
        factor = random.uniform(max(0.0, 1.0 - j), 1.0 + j)

    return max(0.0, min(policy.max_delay_s, exp * factor))


def sleep_backoff(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))
