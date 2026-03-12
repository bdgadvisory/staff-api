import os
import json
from typing import Optional, Literal, Dict, Any, Tuple, List

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
    questions: Optional[List[str]] = None
    answers: Optional[Dict[str, str]] = None


def _message_text(department: str, artifact_type: str, approval_id: str, draft_text: str) -> str:
    return (
        f"[APPROVAL REQUEST]\n"
        f"department: {department}\n"
        f"type: {artifact_type}\n"
        f"id: {approval_id}\n\n"
        f"{draft_text}\n\n"
        f"Reply with: approve | reject: <note> | interview: <question(s)>"
    )


def _interview_message(approval_id: str, questions: List[str]) -> str:
    q_lines = "\n".join([f"{i+1}) {q}" for i, q in enumerate(questions)])
    return (
        f"[INTERVIEW]\n"
        f"id: {approval_id}\n\n"
        f"Please answer:\n{q_lines}\n\n"
        f"Then submit answers as a dict like: {{\"1\":\"...\",\"2\":\"...\"}}"
    )


def opus_revise(
    draft_text: str,
    notes: str,
    interview_questions: Optional[List[str]] = None,
    interview_answers: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    client = _anthropic_client()
    model = _opus_model()

    interview_block = ""
    if interview_questions:
        interview_block += "Interview questions:\n" + "\n".join([f"- {q}" for q in interview_questions]) + "\n"
    if interview_answers:
        interview_block += "Interview answers:\n" + "\n".join([f"- {k}: {v}" for k, v in interview_answers.items()]) + "\n"

    prompt = f"""Revise the draft based on the feedback (and interview Q/A if provided).

Draft:
{draft_text}

Feedback / notes:
{notes}

{interview_block}

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
            """
            SELECT department, artifact_type, status, draft_text, notes, interview_questions, interview_answers
            FROM approvals
            WHERE id = %s::uuid;
            """,
            (approval_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")

        department, artifact_type, status, draft_text, prior_notes, iq, ia = row
        interview_questions = iq
        interview_answers = ia

        if payload.action == "approve":
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

        if payload.action == "reject":
            notes = payload.notes or ""
            revised, opus_notes = opus_revise(draft_text=draft_text, notes=notes)
            combined_notes = "\n".join([n for n in [prior_notes, f"[rejected] {notes}".strip(), opus_notes] if n])

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

        # interview
        if payload.questions and not payload.answers:
            cur.execute(
                """
                UPDATE approvals
                SET status='interview',
                    interview_questions=%s::jsonb,
                    updated_at=now()
                WHERE id=%s::uuid
                RETURNING id::text, status, updated_at::text;
                """,
                (json.dumps(payload.questions), approval_id),
            )
            out = cur.fetchone()
            conn.commit()
            return {
                "approval_id": out[0],
                "status": out[1],
                "updated_at": out[2],
                "interview_message_text": _interview_message(approval_id, payload.questions),
            }

        if payload.answers:
            notes = payload.notes or "Interview answers provided."
            revised, opus_notes = opus_revise(
                draft_text=draft_text,
                notes=notes,
                interview_questions=interview_questions,
                interview_answers=payload.answers,
            )
            combined_notes = "\n".join([n for n in [prior_notes, "[interview]", notes, opus_notes] if n])

            cur.execute(
                """
                UPDATE approvals
                SET status='pending',
                    draft_text=%s,
                    interview_answers=%s::jsonb,
                    notes=%s,
                    updated_at=now()
                WHERE id=%s::uuid
                RETURNING id::text, status, updated_at::text;
                """,
                (revised, json.dumps(payload.answers), combined_notes, approval_id),
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

        raise HTTPException(status_code=400, detail="Interview requires questions[] or answers{}")

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
