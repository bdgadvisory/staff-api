from typing import Optional, Literal, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_db_conn

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalRequest(BaseModel):
    department: str = Field(..., examples=["scribe"])
    artifact_type: str = Field(..., examples=["linkedin_post"])
    draft_text: str
    summary: Optional[str] = None


class ApprovalAction(BaseModel):
    action: Literal["approve", "reject", "interview"]
    notes: Optional[str] = None


@router.post("/request")
def request_approval(payload: ApprovalRequest) -> Dict[str, Any]:
    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO approvals (department, artifact_type, status, draft_text, notes)
            VALUES (%s, %s, 'pending', %s, %s)
            RETURNING id::text, status, created_at::text;
            """,
            (payload.department, payload.artifact_type, payload.draft_text, payload.summary),
        )
        row = cur.fetchone()
        conn.commit()

        approval_id, status, created_at = row

        # Provider-agnostic message payload (WhatsApp later)
        message_text = (
            f"[APPROVAL REQUEST]\n"
            f"department: {payload.department}\n"
            f"type: {payload.artifact_type}\n"
            f"id: {approval_id}\n\n"
            f"{payload.draft_text}\n\n"
            f"Reply with: approve | reject: <note> | interview: <question>"
        )

        return {
            "approval_id": approval_id,
            "status": status,
            "created_at": created_at,
            "message_text": message_text,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval insert failed: {repr(e)}")
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


@router.post("/{approval_id}/action")
def approval_action(approval_id: str, payload: ApprovalAction) -> Dict[str, Any]:
    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        if payload.action == "approve":
            new_status = "approved"
        elif payload.action == "reject":
            new_status = "rejected"
        else:
            new_status = "interview"

        cur.execute(
            """
            UPDATE approvals
            SET status = %s,
                notes = COALESCE(%s, notes),
                updated_at = now(),
                final_text = CASE
                  WHEN %s = 'approved' THEN draft_text
                  ELSE final_text
                END
            WHERE id = %s::uuid
            RETURNING id::text, status, updated_at::text;
            """,
            (new_status, payload.notes, new_status, approval_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Approval not found")

        conn.commit()

        # Next-step hint: reject/interview should escalate to Opus revision of this artifact
        next_step = None
        if new_status in ("rejected", "interview"):
            next_step = {
                "action": "revise",
                "escalate": True,
                "model": "claude-opus-4-6",
                "note": "Hook this to /scribe/linkedin/revise next."
            }

        return {
            "approval_id": row[0],
            "status": row[1],
            "updated_at": row[2],
            "next_step": next_step,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval update failed: {repr(e)}")
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
