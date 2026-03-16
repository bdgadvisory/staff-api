from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from staff.workflows.checkpoints import FileCheckpointStore


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))
    except Exception:
        return None


def load_halted_workflows_from_checkpoints(
    *,
    now_ts: float | None = None,
) -> dict[str, Any]:
    now = float(now_ts or time.time())

    try:
        store = FileCheckpointStore(os.environ.get("WORKFLOW_CHECKPOINT_DIR", "./.workflow_checkpoints"))
        paths = store.list_checkpoints()
    except Exception as e:
        return {
            "ok": False,
            "error": repr(e),
            "halted_count": 0,
            "due_now_count": 0,
            "auto_resume_scheduled_count": 0,
            "manual_intervention_required_count": 0,
            "invalid_checkpoint_count": 0,
            "items": [],
            "_status": "down",
        }

    items: list[dict[str, Any]] = []
    invalid = 0

    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = __import__("json").load(f)

            if not data.get("halted"):
                continue

            # Only include halted/waiting workflows
            next_resume_at = data.get("next_resume_at")
            retry_state = data.get("retry_state") or {}

            current_step = int(data.get("current_step_index") or 0)
            current_step_id = data.get("current_step_id") or (data.get("call_spec") or {}).get("step_id")

            last_error = retry_state.get("last_error")

            # Try to infer next_action/halt metadata from last artifact if present
            last_art = data.get("last_artifact") or {}

            next_action = last_art.get("next_action")
            halt_reason = data.get("halt_reason") or last_art.get("halt_reason")

            provider_name = retry_state.get("provider_name") or last_art.get("provider_name")
            model_name = retry_state.get("model_name") or last_art.get("model_name")
            retry_count = None
            try:
                rc_by_step = (retry_state.get("retry_count_by_step") or {})
                if current_step_id and current_step_id in rc_by_step:
                    retry_count = int(rc_by_step.get(current_step_id) or 0)
                else:
                    retry_count = int(last_art.get("retry_count") or 0)
            except Exception:
                retry_count = None

            resumed_from_checkpoint = bool(last_art.get("resumed_from_checkpoint") or False)

            checkpoint_path = (data.get("checkpoint") or {}).get("checkpoint_path") or str(p)

            items.append(
                {
                    "workflow_id": data.get("workflow_id"),
                    "workflow_type": data.get("workflow_type"),
                    "department": data.get("department"),
                    "current_step": current_step,
                    "current_step_id": current_step_id,
                    "halt_reason": halt_reason,
                    "next_action": next_action,
                    "next_resume_at": _iso(next_resume_at),
                    "next_resume_at_ts": next_resume_at,
                    "retry_count": retry_count,
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "resumed_from_checkpoint": resumed_from_checkpoint,
                    "last_error": last_error,
                    "checkpoint_path": checkpoint_path,
                }
            )

        except Exception:
            invalid += 1
            continue

    # sort by next_resume_at ascending (None last)
    def _key(it: dict[str, Any]):
        v = it.get("next_resume_at_ts")
        return (1, 0) if v is None else (0, float(v))

    items.sort(key=_key)

    halted_count = len(items)
    due_now = sum(1 for it in items if it.get("next_resume_at_ts") is not None and float(it["next_resume_at_ts"]) <= now)

    auto_resume_scheduled = 0
    manual_required = 0

    for it in items:
        na = str(it.get("next_action") or "")
        hr = str(it.get("halt_reason") or "")

        if na == "auto_resume_scheduled" or hr in ("provider_rate_limit", "provider_overloaded", "provider_timeout"):
            auto_resume_scheduled += 1

        if na in ("manual_intervention_required", "manual_resume_required") or hr in (
            "provider_retry_budget_exhausted",
            "budget_exhausted",
            "non_retryable_provider_error",
        ):
            manual_required += 1

    # health semantics
    status = "ok"
    overdue = False
    for it in items:
        ts = it.get("next_resume_at_ts")
        if ts is None:
            continue
        if float(ts) < now - 120:
            overdue = True
            break

    if overdue and halted_count > 0:
        status = "degraded"

    return {
        "ok": True,
        "halted_count": halted_count,
        "due_now_count": due_now,
        "auto_resume_scheduled_count": auto_resume_scheduled,
        "manual_intervention_required_count": manual_required,
        "invalid_checkpoint_count": invalid,
        "items": [
            {k: v for k, v in it.items() if k != "next_resume_at_ts"} for it in items
        ],
        "_status": status,
    }
