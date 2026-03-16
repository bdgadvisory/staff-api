from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Cooldown:
    until_ts: float = 0.0
    last_retry_after_s: float | None = None
    strikes: int = 0


@dataclass
class ProviderThrottleState:
    """In-process provider throttling.

    MVP: simple cooldown + concurrency semaphores.
    """

    cooldown_base_s: float = 5.0
    cooldown_max_s: float = 120.0

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cooldowns: dict[tuple[str, str], _Cooldown] = field(default_factory=dict)  # (provider, model)
    _semaphores: dict[str, threading.Semaphore] = field(default_factory=dict)  # provider -> semaphore

    def _provider_limit(self, provider: str) -> int:
        key = f"PROVIDER_CONCURRENCY_{provider.upper()}"
        try:
            return int(os.environ.get(key, "2"))
        except Exception:
            return 2

    def acquire(self, provider: str, model: str) -> None:
        sem = None
        with self._lock:
            sem = self._semaphores.get(provider)
            if sem is None:
                sem = threading.Semaphore(self._provider_limit(provider))
                self._semaphores[provider] = sem

        # block on concurrency
        assert sem is not None
        sem.acquire()

        # cooldown delay (done after acquiring to avoid stampede)
        delay = self.should_delay(provider, model)
        if delay > 0:
            time.sleep(delay)

    def release(self, provider: str, model: str) -> None:
        with self._lock:
            sem = self._semaphores.get(provider)
        if sem:
            sem.release()

    def note_rate_limit(self, provider: str, model: str, retry_after_s: float | None) -> dict[str, Any]:
        now = time.time()
        key = (provider, model)
        with self._lock:
            cd = self._cooldowns.get(key) or _Cooldown()
            cd.strikes += 1
            cd.last_retry_after_s = retry_after_s

            # Exponential-ish cooldown escalation, capped
            base = float(os.environ.get("PROVIDER_COOLDOWN_BASE_S", str(self.cooldown_base_s)))
            cap = float(os.environ.get("PROVIDER_COOLDOWN_MAX_S", str(self.cooldown_max_s)))
            delay = min(cap, base * (2 ** max(0, cd.strikes - 1)))
            if retry_after_s and retry_after_s > 0:
                delay = max(delay, float(retry_after_s))

            cd.until_ts = max(cd.until_ts, now + delay)
            self._cooldowns[key] = cd

            return {
                "provider": provider,
                "model": model,
                "cooldown_until": cd.until_ts,
                "cooldown_delay_s": delay,
                "strikes": cd.strikes,
                "retry_after_s": retry_after_s,
            }

    def should_delay(self, provider: str, model: str) -> float:
        now = time.time()
        key = (provider, model)
        with self._lock:
            cd = self._cooldowns.get(key)
            if not cd:
                return 0.0
            if cd.until_ts <= now:
                return 0.0
            return float(cd.until_ts - now)
