from __future__ import annotations

import os
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_db_conn
from staff.llm_router.types import TaskContext
from staff.workflows.loader import load_workflow
from staff.workflows.runtime import build_executor_from_env
from staff.workflows.types import WorkflowState

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowRunIn(BaseModel):
    workflow_path: str = Field(..., description="Filesystem path to a workflow YAML on the server")
    input_payload: dict[str, Any] = Field(default_factory=dict)
    live_mode: Optional[bool] = Field(default=None, description="Override STAFF_LIVE_MODE for this run")


class WorkflowRunOut(BaseModel):
    ok: bool
    workflow_id: str
    status: str
    halted: bool = False
    halt_reason: Optional[str] = None
    next_resume_at: Optional[float] = None


def _db_upsert_run(workflow_id: str, *, workflow_path: str, status: str, state: dict[str, Any] | None = None) -> None:
    connector, conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO workflow_runs (workflow_id, workflow_path, status, started_at, updated_at, state)
            VALUES (%s, %s, %s, now(), now(), %s::jsonb)
            ON CONFLICT (workflow_id)
            DO UPDATE SET status = EXCLUDED.status, updated_at = now(), state = EXCLUDED.state
            """,
            (workflow_id, workflow_path, status, __import__("json").dumps(state or {}, ensure_ascii=False, default=str)),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
        connector.close()


def _db_get_run(workflow_id: str) -> dict[str, Any] | None:
    connector, conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT workflow_id, workflow_path, status, started_at, updated_at, state FROM workflow_runs WHERE workflow_id = %s", (workflow_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "workflow_id": row[0],
            "workflow_path": row[1],
            "status": row[2],
            "started_at": str(row[3]),
            "updated_at": str(row[4]),
            "state": row[5] if not isinstance(row[5], str) else __import__("json").loads(row[5]),
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass
        connector.close()


@router.post("/run", response_model=WorkflowRunOut)
def workflow_run(req: WorkflowRunIn) -> WorkflowRunOut:
    # NOTE: workflow_path is server-side; do not accept arbitrary remote URLs.
    wf_path = req.workflow_path
    if not wf_path or not isinstance(wf_path, str):
        raise HTTPException(status_code=400, detail="workflow_path required")
    if ".." in wf_path:
        raise HTTPException(status_code=400, detail="workflow_path must not contain ..")

    wf = load_workflow(wf_path)

    workflow_id = str(uuid.uuid4())
    department = wf.department or str(req.input_payload.get("department") or "staff")

    st = WorkflowState(
        workflow_id=workflow_id,
        workflow_type=wf.name,
        department=department,
        task_type=wf.name,
        output_class=wf.output_class,
        current_step=0,
        input_payload=req.input_payload or {},
        audit_context={"workflow_path": wf_path, "created_at": time.time()},
    )

    _db_upsert_run(workflow_id, workflow_path=wf_path, status="RUNNING", state={"workflow_id": workflow_id})

    ctx = TaskContext(
        request_id=f"api:{workflow_id}",
        department=department,
        task_type=wf.name,
        actor={"actor_type": "api", "actor_id": "workflow_run"},
        human_facing=True,
        privacy_class=str(req.input_payload.get("privacy_class") or "internal"),
        scope=str(req.input_payload.get("scope") or department),
    )

    ex = build_executor_from_env(live_mode=req.live_mode)

    try:
        ex.run(ctx, wf, st)
    finally:
        # persist status after attempt
        status = "HALTED" if st.halted else "DONE"
        _db_upsert_run(
            workflow_id,
            workflow_path=wf_path,
            status=status,
            state={
                "workflow_id": st.workflow_id,
                "halted": st.halted,
                "halt_reason": st.halt_reason,
                "next_resume_at": st.next_resume_at,
                "current_step": st.current_step,
            },
        )

    return WorkflowRunOut(
        ok=True,
        workflow_id=workflow_id,
        status="HALTED" if st.halted else "DONE",
        halted=bool(st.halted),
        halt_reason=st.halt_reason,
        next_resume_at=st.next_resume_at,
    )


@router.get("/{workflow_id}")
def workflow_get(workflow_id: str) -> dict[str, Any]:
    row = _db_get_run(workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")

    # attach latest checkpoint if present
    try:
        from staff.workflows.checkpoints import PostgresCheckpointStore

        ck = PostgresCheckpointStore().load(workflow_id)
    except Exception:
        ck = None

    return {"ok": True, **row, "checkpoint": ck}


@router.post("/{workflow_id}/cancel")
def workflow_cancel(workflow_id: str) -> dict[str, Any]:
    row = _db_get_run(workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")

    _db_upsert_run(workflow_id, workflow_path=row.get("workflow_path") or "", status="CANCELLED", state=row.get("state") or {})
    return {"ok": True, "workflow_id": workflow_id, "status": "CANCELLED"}
