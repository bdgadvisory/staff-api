import os
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from google.cloud.sql.connector import Connector
from db import get_db_conn
from anthropic import Anthropic

app = FastAPI()

from scribe import router as scribe_router
from approvals import router as approvals_router
from reminders import router as reminders_router, internal_router as reminders_internal_router
app.include_router(scribe_router)
app.include_router(approvals_router)
app.include_router(reminders_router)
app.include_router(reminders_internal_router)



# -------------------------
# DB helpers (unchanged)
# -------------------------
def get_db_conn():
    instance_conn = os.environ.get("INSTANCE_CONNECTION_NAME")
    db = os.environ.get("DB_NAME")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")

    missing = [k for k, v in {
        "INSTANCE_CONNECTION_NAME": instance_conn,
        "DB_NAME": db,
        "DB_USER": user,
        "DB_PASSWORD": password,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    connector = Connector()
    conn = connector.connect(
        instance_conn,
        "pg8000",
        user=user,
        password=password,
        db=db,
    )
    return connector, conn


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/db-check")
def db_check():
    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        value = cur.fetchone()[0]
        conn.close()
        return {"db_ok": True, "select_1": value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {repr(e)}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        try:
            if connector:
                connector.close()
        except Exception:
            pass


@app.get("/ui/status")
def ui_status():
    """Aggregated status endpoint for the UI.

    Must be resilient: never crash because of one bad checkpoint file.
    """
    import time

    out: Dict[str, Any] = {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Back-compat for existing frontend probes
        "components": {},
        # New shape
        "services": {},
        "workflow_resume": {
            "halted_count": 0,
            "due_now_count": 0,
            "auto_resume_scheduled_count": 0,
            "manual_intervention_required_count": 0,
            "items": [],
        },
    }

    # staff-api health (in-process)
    out["components"]["staff-api"] = {"status": "ok"}
    out["services"]["staff_api"] = {"status": "ok"}

    # db-check (real DB connectivity)
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        out["components"]["db"] = {"status": "ok"}
        out["services"]["database"] = {"status": "ok"}
    except Exception as e:
        out["components"]["db"] = {"status": "degraded", "error": repr(e)}
        out["services"]["database"] = {"status": "degraded", "error": repr(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            connector.close()
        except Exception:
            pass

    # reminders endpoint (DB access + table exists)
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM reminders LIMIT 1;")
        out["components"]["reminders"] = {"status": "ok"}
        out["services"]["reminders_tick"] = {"status": "ok"}
    except Exception as e:
        out["components"]["reminders"] = {"status": "degraded", "error": repr(e)}
        out["services"]["reminders_tick"] = {"status": "degraded", "error": repr(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            connector.close()
        except Exception:
            pass

    # workflow resume status derived from checkpoint store
    try:
        from staff.workflows.status import load_halted_workflows_from_checkpoints

        wr = load_halted_workflows_from_checkpoints()
        out["workflow_resume"] = {
            "halted_count": wr.get("halted_count", 0),
            "due_now_count": wr.get("due_now_count", 0),
            "auto_resume_scheduled_count": wr.get("auto_resume_scheduled_count", 0),
            "manual_intervention_required_count": wr.get("manual_intervention_required_count", 0),
            "items": wr.get("items", []),
            "invalid_checkpoint_count": wr.get("invalid_checkpoint_count", 0),
        }
        out["services"]["workflow_resume_tick"] = {"status": wr.get("_status", "unknown")}
        # Back-compat for architecture graph nodes
        out["components"]["workflow-resume"] = {"status": wr.get("_status", "unknown")}
    except Exception as e:
        out["services"]["workflow_resume_tick"] = {"status": "down", "error": repr(e)}

    # policy gate is config-side; treat as ok (UI uses this as static component)
    out["components"]["skills-gate"] = {"status": "ok"}

    # planned components
    out["components"]["agent-inbox"] = {"status": "planned"}
    out["components"]["home-ops"] = {"status": "planned"}

    return out


class TaskCreate(BaseModel):
    title: str
    notes: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None  # todo|doing|done


class TaskOut(BaseModel):
    id: str
    title: str
    notes: Optional[str] = None
    status: str
    created_at: str
    updated_at: str


@app.post("/tasks", response_model=TaskOut)
def create_task(payload: TaskCreate):
    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (title, notes)
            VALUES (%s, %s)
            RETURNING id::text, title, notes, status,
                    created_at::text, updated_at::text
            """,
            (payload.title, payload.notes),
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        return {
            "id": row[0],
            "title": row[1],
            "notes": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB insert failed: {repr(e)}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        try:
            if connector:
                connector.close()
        except Exception:
            pass


@app.get("/tasks", response_model=List[TaskOut])
def list_tasks(status: Optional[str] = None):
    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        if status:
            cur.execute(
                """
                SELECT id::text, title, notes, status,
                       created_at::text, updated_at::text
                FROM tasks
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (status,),
            )
        else:
            cur.execute(
                """
                SELECT id::text, title, notes, status,
                       created_at::text, updated_at::text
                FROM tasks
                ORDER BY created_at DESC
                LIMIT 100
                """
            )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "title": r[1],
                "notes": r[2],
                "status": r[3],
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {repr(e)}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        try:
            if connector:
                connector.close()
        except Exception:
            pass


@app.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdate):
    if payload.status is not None and payload.status not in ("todo", "doing", "done"):
        raise HTTPException(status_code=400, detail="status must be one of: todo, doing, done")

    fields = []
    values = []

    if payload.title is not None:
        fields.append("title = %s")
        values.append(payload.title)
    if payload.notes is not None:
        fields.append("notes = %s")
        values.append(payload.notes)
    if payload.status is not None:
        fields.append("status = %s")
        values.append(payload.status)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields.append("updated_at = now()")

    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        sql = f"""
        UPDATE tasks
        SET {", ".join(fields)}
        WHERE id = %s::uuid
        RETURNING id::text, title, notes, status,
                  created_at::text, updated_at::text
        """
        values.append(task_id)

        cur.execute(sql, tuple(values))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Task not found")

        conn.commit()
        conn.close()
        return {
            "id": row[0],
            "title": row[1],
            "notes": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB update failed: {repr(e)}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        try:
            if connector:
                connector.close()
        except Exception:
            pass
