import os
from typing import Optional, Literal, Dict, Any, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from anthropic import Anthropic

from db import get_db_conn

router = APIRouter(prefix="/approvals", tags=["approvals"])

DEFAULT_OPUS = "claude-opus-4-6"
VOICE_RULES = """You are Staff:Scribe Voice/Critic.

- Controlled but human; reflective, not performative.
- Calm, precise, measured. Executive tone.
- No hype, no clichés, no LinkedIn theater.
- Do not add new factual claims. Improve clarity, structure, and tone.
"""


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise HTTPException(status_code=500, detail=f"Missing env var: {name}")
    return v


def _anthropic_client() -> Anthropic:
    return Anthropic(api_key=_get_env("ANTHROPIC_API_KEY"))


def _opus_model() -> str:
    return os.getenv("OPUS_MODEL", DEFAULT_OPUS)


class ApprovalRequest(BaseModel):
    department: str = Field(..., examples=["scribe"])
    artifact_type: str = Field(..., examples=["linkedin_post"])
    draft_text: str
    summary: Optional[str] = None


class ApprovalAction(BaseModel):
    action: Literal["approve", "reject", "interview"]
    notes: Optional[str] = None


def _message_text(department: str, artifact_type: str, approval_id: str, draft_text: str) -> str:
    return (
        f"[APPROVAL REQUEST]\n"
        f"department: {department}\n"
        f"type: {artifact_type}\n"
        f"id: {approval_id}\n\n"
        f"{draft_text}\n\n"
        f"Reply with: approve | reject: <note> | interview: <question>"
    )


def opus_revise(draft_text: str, notes: str) -> Tuple[str, str]:
    client = _anthropic_client()
    model = _opus_model()

    prompt = f"""Revise the draft based on the feedback.

Draft:
{draft_text}

Feedback / notes:
{notes}

Return TWO sections exactly:

[POST]
<revised post text>

[NOTES]
<brief bullet notes of what you changed and why>
"""
    msg = client.messages.create(
        model=model,
        max_tokens=900,
        temperature=0.2,
        system=VOICE_RULES,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"]).strip()

    def extract(tag: str) -> str:
        start = text.find(f"[{tag}]")
        if start == -1:
            return ""
        start += len(tag) + 2
        next_tags = []
        for t in ("POST", "NOTES"):
            if t == tag:
                continue
            idx = text.find(f"[{t}]", start)
            if idx != -1:
                next_tags.append(idx)
        end = min(next_tags) if next_tags else len(text)
        return text[start:end].strip()

    post = extract("POST") or draft_text
    why = extract("NOTES") or ""
    return post, why


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
        return {
            "approval_id": approval_id,
            "status": status,
            "created_at": created_at,
            "message_text": _message_text(payload.department, payload.artifact_type, approval_id, payload.draft_text),
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

        cur.execute(
            "SELECT department, artifact_type, status, draft_text, notes FROM approvals WHERE id = %s::uuid;",
            (approval_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")

        department, artifact_type, status, draft_text, prior_notes = row

        if payload.action == "approve":
            new_status = "approved"
            cur.execute(
                """
                UPDATE approvals
                SET status='approved', final_text=draft_text, notes=COALESCE(%s, notes), updated_at=now()
                WHERE id=%s::uuid
                RETURNING id::text, status, updated_at::text;
                """,
                (payload.notes, approval_id),
            )
            out = cur.fetchone()
            conn.commit()
            return {"approval_id": out[0], "status": out[1], "updated_at": out[2]}

        # reject/interview => Opus revise + re-queue as pending
        if payload.action == "reject":
            action_status = "rejected"
        else:
            action_status = "interview"

        notes = payload.notes or ""
        revised, opus_notes = opus_revise(draft_text=draft_text, notes=notes)

        combined_notes = "\n".join([n for n in [prior_notes, f"[{action_status}] {notes}".strip(), opus_notes] if n])

        cur.execute(
            """
            UPDATE approvals
            SET status='pending',
                draft_text=%s,
                notes=%s,
                updated_at=now()
            WHERE id=%s::uuid
            RETURNING id::text, status, updated_at::text;
            """,
            (revised, combined_notes, approval_id),
        )
        out = cur.fetchone()
        conn.commit()

        return {
            "approval_id": out[0],
            "status": out[1],
            "updated_at": out[2],
            "message_text": _message_text(department, artifact_type, approval_id, revised),
            "escalated_model": _opus_model(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval action failed: {repr(e)}")
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
