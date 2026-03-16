from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from db import get_db_conn
from staff.llm_router.types import RetrievalBundle, TaskContext
from staff.providers.base import LLMCall, ProviderAdapter
from staff.workflows.checkpoints import PostgresCheckpointStore
from staff.workflows.executor import WorkflowExecutor
from staff.workflows.loader import load_workflow
from staff.workflows.runtime import build_executor_from_env
from staff.workflows.types import WorkflowState

router = APIRouter(prefix="/internal/workflows", tags=["internal-workflows"])


class ProbeRequest(BaseModel):
    workflow_path: str = Field(..., description="Path to internal probe workflow YAML")
    text: str = Field("probe", description="User text payload")


class _RateLimitOnce(Exception):
    def __init__(self, message: str = "rate limited once", *, retry_after_s: float = 2.0):
        super().__init__(message)
        self.status_code = 429
        self.retry_after_s = float(retry_after_s)


class Deterministic429OnceAdapter(ProviderAdapter):
    name = "openai"

    def __init__(self):
        self._store = PostgresCheckpointStore()

    def _get_probe_flag(self, workflow_id: str) -> bool:
        connector, conn = get_db_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT state FROM workflow_runs WHERE workflow_id = %s", (workflow_id,))
            row = cur.fetchone()
            if not row or row[0] is None:
                return False
            state = row[0]
            if isinstance(state, str):
                state = __import__("json").loads(state)
            return bool((state or {}).get("probe_failed_once"))
        finally:
            try:
                conn.close()
            except Exception:
                pass
            connector.close()

    def _set_probe_flag(self, workflow_id: str) -> None:
        connector, conn = get_db_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE workflow_runs
                SET updated_at = now(), state = COALESCE(state, '{}'::jsonb) || '{"probe_failed_once": true}'::jsonb
                WHERE workflow_id = %s
                """,
                (workflow_id,),
            )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
            connector.close()

    def complete(self, call: LLMCall):
        meta = call.metadata or {}
        workflow_id = str(meta.get("workflow_id") or "")
        if not workflow_id:
            raise _RateLimitOnce("missing workflow_id metadata", retry_after_s=2.0)

        already_failed = self._get_probe_flag(workflow_id)
        if not already_failed:
            self._set_probe_flag(workflow_id)
            raise _RateLimitOnce("deterministic probe 429", retry_after_s=2.0)

        # Succeed on resume
        from staff.llm_router.types import LLMResult

        return LLMResult(text="probe-ok", raw={"ok": True}, provider="openai", model=call.model, latency_ms=1, cost_estimate=0.0)


def _require_internal_secret(x_reminders_tick_secret: str | None) -> None:
    expected = None
    try:
        expected = __import__("os").environ.get("REMINDERS_TICK_SECRET")
    except Exception:
        expected = None

    if not expected:
        raise HTTPException(status_code=500, detail="REMINDERS_TICK_SECRET not configured")
    if not x_reminders_tick_secret or x_reminders_tick_secret != expected:
        raise HTTPException(status_code=403, detail="forbidden")


@router.post("/probe-retry")
def probe_retry_chain(req: ProbeRequest, x_reminders_tick_secret: str | None = Header(default=None)) -> dict[str, Any]:
    """Deterministic production proof:

    - starts a workflow that triggers a retryable 429 once
    - executor halts with auto_resume_scheduled
    - checkpoint is written to Postgres
    - tick later resumes and completes

    Guarded by X-Reminders-Tick-Secret.
    """

    _require_internal_secret(x_reminders_tick_secret)

    wf_path = req.workflow_path
    if ".." in wf_path:
        raise HTTPException(status_code=400, detail="workflow_path must not contain ..")

    wf = load_workflow(wf_path)

    workflow_id = str(uuid.uuid4())
    st = WorkflowState(
        workflow_id=workflow_id,
        workflow_type=wf.name,
        department=wf.department or "staff",
        task_type=wf.name,
        output_class=wf.output_class,
        current_step=0,
        input_payload={"text": req.text, "scope": "staff", "privacy_class": "internal"},
        audit_context={"workflow_path": wf_path, "probe": True, "created_at": time.time()},
    )

    # Ensure generate steps can run without a real retrieval service.
    st.retrieval_bundle = RetrievalBundle()

    # Insert run record
    connector, conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO workflow_runs (workflow_id, workflow_path, status, started_at, updated_at, state)
            VALUES (%s, %s, %s, now(), now(), %s::jsonb)
            """,
            (workflow_id, wf_path, "RUNNING", __import__("json").dumps({"probe_failed_once": False}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
        connector.close()

    # Build executor but override openai adapter with deterministic 429-once adapter
    base = build_executor_from_env(live_mode=False)
    ex = WorkflowExecutor(
        router=base.router,
        retrieval=base.retrieval,
        prompt_engine=base.prompt_engine,
        adapters={**base.adapters, "openai": Deterministic429OnceAdapter()},
        reviewer=base.reviewer,
        confidence=base._conf,
        escalation=base._esc,
        audit=base.audit,
        checkpoint_store=PostgresCheckpointStore(),
        throttle=base.throttle,
        retry_policy=base.retry_policy,
        budgets=base.budgets,
    )

    ctx = TaskContext(
        request_id=f"probe:{workflow_id}",
        department=st.department,
        task_type=st.task_type,
        actor={"actor_type": "internal", "actor_id": "probe_retry_chain"},
        human_facing=False,
        privacy_class="internal",
        scope="staff",
    )

    ex.run(ctx, wf, st)

    # Update status
    connector, conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE workflow_runs SET status=%s, updated_at=now(), state = COALESCE(state, '{}'::jsonb) || %s::jsonb WHERE workflow_id=%s",
            (
                "HALTED" if st.halted else "DONE",
                __import__("json").dumps({"halt_reason": st.halt_reason, "next_resume_at": st.next_resume_at}, ensure_ascii=False),
                workflow_id,
            ),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
        connector.close()

    ck = PostgresCheckpointStore().load(workflow_id)

    return {
        "ok": True,
        "workflow_id": workflow_id,
        "status": "HALTED" if st.halted else "DONE",
        "halted": bool(st.halted),
        "halt_reason": st.halt_reason,
        "next_resume_at": st.next_resume_at,
        "checkpoint": ck,
    }
