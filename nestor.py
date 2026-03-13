from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_db_conn

router = APIRouter(prefix="/nestor", tags=["nestor"])


class NestorIntakeRequest(BaseModel):
    channel: str  # whatsapp|email (for now)
    external_thread_id: Optional[str] = None
    external_message_id: Optional[str] = None

    sender_user_id: Optional[str] = None
    sender_display: Optional[str] = None

    text: Optional[str] = None

    # MVP voice note support: send base64 audio bytes directly
    # Later: this becomes WhatsApp media_id -> fetch -> transcribe
    audio_base64: Optional[str] = None
    audio_mime: Optional[str] = None  # e.g. audio/ogg


@router.post("/intake")
def nestor_intake(req: NestorIntakeRequest) -> Dict[str, Any]:
    if not req.text and not req.audio_base64:
        raise HTTPException(status_code=400, detail="Provide text or audio_base64")

    # Store thread/message (minimal for now)
    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        thread_id = None
        if req.external_thread_id:
            cur.execute(
                """
                INSERT INTO nestor_threads(channel, external_thread_id)
                VALUES (%s, %s)
                ON CONFLICT(channel, external_thread_id) DO UPDATE SET channel=EXCLUDED.channel
                RETURNING id::text;
                """,
                (req.channel, req.external_thread_id),
            )
            thread_id = cur.fetchone()[0]

        media_type = "audio" if req.audio_base64 else None

        cur.execute(
            """
            INSERT INTO nestor_messages(
              thread_id, channel, external_message_id,
              sender_user_id, sender_display,
              text, media_type, media_ref, transcript_status
            )
            VALUES (
              %s::uuid, %s, %s,
              %s, %s,
              %s, %s, %s,
              %s
            )
            RETURNING id::text;
            """,
            (
                thread_id,
                req.channel,
                req.external_message_id,
                req.sender_user_id,
                req.sender_display,
                req.text,
                media_type,
                None,
                "queued" if req.audio_base64 else "none",
            ),
        )
        message_id = cur.fetchone()[0]
        conn.commit()

        # User-facing response (nice)
        if req.audio_base64:
            return {
                "ok": True,
                "message_id": message_id,
                "reply_text": "Got it — I’m transcribing your voice note now. I’ll reply in a moment.",
            }
        return {
            "ok": True,
            "message_id": message_id,
            "reply_text": "Got it. Give me a moment and I’ll take care of that.",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Nestor intake failed: {repr(e)}")
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
