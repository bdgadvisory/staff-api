from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowBudgets:
    max_provider_calls_per_workflow: int = 30
    max_retries_per_step: int = 6
    max_review_passes: int = 3
    max_premium_provider_calls: int = 2

    @classmethod
    def from_env(cls) -> "WorkflowBudgets":
        def _i(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, str(default)))
            except Exception:
                return default

        return cls(
            max_provider_calls_per_workflow=_i("WF_MAX_PROVIDER_CALLS", 30),
            max_retries_per_step=_i("WF_MAX_RETRIES_PER_STEP", _i("PROVIDER_MAX_RETRIES_PER_STEP", 6)),
            max_review_passes=_i("WF_MAX_REVIEW_PASSES", 3),
            max_premium_provider_calls=_i("WF_MAX_PREMIUM_CALLS", 2),
        )
