from __future__ import annotations

import os
import time
from dataclasses import fields
from typing import Any

from staff.llm_router.types import OutputClass, TaskContext
from staff.workflows.checkpoints import FileCheckpointStore
from staff.workflows.executor import WorkflowExecutor
from staff.workflows.loader import load_workflow
from staff.workflows.runtime import build_executor_from_env
from staff.workflows.types import StepArtifact, WorkflowState


def _artifact_from_dict(d: dict[str, Any]) -> StepArtifact:
    # Only accept known dataclass fields
    allowed = {f.name for f in fields(StepArtifact)}
    clean = {k: v for k, v in d.items() if k in allowed}
    return StepArtifact(**clean)  # type: ignore[arg-type]


def _state_from_checkpoint(data: dict[str, Any]) -> WorkflowState:
    st = WorkflowState(
        workflow_id=data["workflow_id"],
        workflow_type=data.get("workflow_type") or "unknown",
        department=data.get("department") or "unknown",
        task_type=data.get("task_type") or "unknown",
        output_class=OutputClass(str(data.get("output_class") or "B")),
        current_step=int(data.get("current_step_index") or 0),
        input_payload=data.get("input_payload") or {},
        audit_context=data.get("audit_context") or {},
    )

    st.halted = bool(data.get("halted") or False)
    st.halt_reason = data.get("halt_reason")
    st.next_resume_at = data.get("next_resume_at")

    st.retry_state = data.get("retry_state") or st.retry_state
    st.checkpoint = data.get("checkpoint") or st.checkpoint
    st.workflow_call_counts = data.get("workflow_call_counts") or st.workflow_call_counts
    st.review_pass_count = int(data.get("review_pass_count") or 0)

    for a in data.get("completed_artifacts") or []:
        try:
            st.step_artifacts.append(_artifact_from_dict(a))
        except Exception:
            continue

    return st


def workflow_resume_tick(*, now_ts: float | None = None) -> dict[str, Any]:
    """Tick processor: resume workflows that were halted due to provider overload/rate limits.

    Storage: File checkpoints in WORKFLOW_CHECKPOINT_DIR.
    """

    now = float(now_ts or time.time())
    store = FileCheckpointStore(os.environ.get("WORKFLOW_CHECKPOINT_DIR", "./.workflow_checkpoints"))

    processed = 0
    resumed = 0
    skipped = 0
    errored = 0

    ex: WorkflowExecutor = build_executor_from_env(live_mode=None)

    for p in store.list_checkpoints():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = __import__("json").load(f)

            if not data.get("halted"):
                continue

            next_resume_at = data.get("next_resume_at")
            if not next_resume_at or float(next_resume_at) > now:
                continue

            processed += 1

            # Only auto-resume for provider overload / rate limit halts
            reason = str(data.get("halt_reason") or "")
            if reason not in ("provider_rate_limit", "provider_overloaded", "provider_timeout"):
                skipped += 1
                continue

            st = _state_from_checkpoint(data)

            # Workflow path must be provided by the runner (stored in audit_context)
            wf_path = (st.audit_context.get("workflow_path") or st.audit_context.get("workflow_yaml"))
            if not wf_path:
                # Cannot resume without a definition; mark as manual.
                st.halted = True
                st.halt_reason = "manual_resume_required"
                st.next_resume_at = None
                store.save_pre_call(st.workflow_id, st, "workflow_resume_tick", {"error": "missing_workflow_path"})
                skipped += 1
                continue

            wf = load_workflow(str(wf_path))

            ctx = TaskContext(
                request_id=f"tick:{st.workflow_id}",
                department=st.department,
                task_type=st.task_type,
                actor={"actor_type": "tick", "actor_id": "workflow_resume_tick"},
                human_facing=True,
                privacy_class=str(st.input_payload.get("privacy_class") or "internal"),
                scope=str(st.input_payload.get("scope") or st.department),
            )

            # clear halt and resume
            st.halted = False
            st.halt_reason = None
            st.next_resume_at = None

            ex.run(ctx, wf, st)

            # persist after resume attempt
            store.save_post_call(st.workflow_id, st, "workflow_resume_tick", StepArtifact(step_id="workflow_resume_tick", step_type="audit", status="DONE"))

            resumed += 1

        except Exception:
            errored += 1
            continue

    return {
        "ok": True,
        "processed": processed,
        "resumed": resumed,
        "skipped": skipped,
        "errored": errored,
    }
