from __future__ import annotations

import json
import time
from typing import Any


def _emit(event_type: str, payload: dict[str, Any]) -> None:
    rec = {"ts": time.time(), "event_type": event_type, **payload}
    print(json.dumps(rec, default=str))


def log_retry_event(
    *,
    workflow_id: str,
    step_id: str,
    provider: str,
    model: str,
    error_type: str,
    retry_count: int,
    backoff_s: float,
    auto_resume_scheduled: bool,
) -> None:
    _emit(
        "provider_retry",
        {
            "workflow_id": workflow_id,
            "step_id": step_id,
            "provider": provider,
            "model": model,
            "error_type": error_type,
            "retry_count": retry_count,
            "backoff_s": backoff_s,
            "auto_resume_scheduled": auto_resume_scheduled,
        },
    )


def log_checkpoint_event(*, workflow_id: str, step_id: str, stage: str, checkpoint_path: str) -> None:
    _emit(
        "workflow_checkpoint",
        {"workflow_id": workflow_id, "step_id": step_id, "stage": stage, "checkpoint_path": checkpoint_path},
    )


def log_throttle_event(*, workflow_id: str, provider: str, model: str, cooldown_state: dict[str, Any]) -> None:
    _emit(
        "provider_throttle",
        {"workflow_id": workflow_id, "provider": provider, "model": model, "cooldown_state": cooldown_state},
    )


def log_auto_resume_event(
    *, workflow_id: str, step_id: str, scheduled_for_ts: float, resumed_from_checkpoint: bool
) -> None:
    _emit(
        "workflow_auto_resume",
        {
            "workflow_id": workflow_id,
            "step_id": step_id,
            "scheduled_for_ts": scheduled_for_ts,
            "resumed_from_checkpoint": resumed_from_checkpoint,
        },
    )
