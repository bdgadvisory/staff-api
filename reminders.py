from __future__ import annotations

import os

from datetime import datetime
from typing import Optional, List, Any

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

from db import get_db_conn


router = APIRouter(prefix="/reminders", tags=["reminders"])



internal_router = APIRouter(prefix="/internal/reminders", tags=["internal"])

class ReminderCreate(BaseModel):
    message: str = Field(..., min_length=1)
    next_fire_at: datetime
    timezone: str = Field(..., min_length=1)
    rrule: Optional[str] = None
    target_channel: str = Field(..., description="whatsapp|email")
    target_address: str = Field(..., min_length=1)


class ReminderPatch(BaseModel):
    message: Optional[str] = Field(None, min_length=1)
    next_fire_at: Optional[datetime] = None
    timezone: Optional[str] = Field(None, min_length=1)
    rrule: Optional[str] = None
    status: Optional[str] = None  # scheduled|paused|done|error
    target_channel: Optional[str] = None
    target_address: Optional[str] = Field(None, min_length=1)


class ReminderOut(BaseModel):
    id: str
    message: str
    next_fire_at: str
    timezone: str
    rrule: Optional[str] = None
    status: str
    target_channel: str
    target_address: str
    last_fired_at: Optional[str] = None
    last_error: Optional[str] = None
    created_at: str
    updated_at: str


_ALLOWED_STATUS = {"scheduled", "paused", "done", "error"}
_ALLOWED_CHANNELS = {"whatsapp", "email"}


def _validate_enums(target_channel: Optional[str], status: Optional[str]):
    if target_channel is not None and target_channel not in _ALLOWED_CHANNELS:
        raise HTTPException(status_code=400, detail="target_channel must be one of: whatsapp, email")
    if status is not None and status not in _ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="status must be one of: scheduled, paused, done, error")


@router.post("", response_model=ReminderOut)
def create_reminder(payload: ReminderCreate):
    _validate_enums(payload.target_channel, None)

    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reminders (
              message, next_fire_at, timezone, rrule,
              status, target_channel, target_address
            )
            VALUES (%s, %s, %s, %s, 'scheduled', %s, %s)
            RETURNING
              id::text,
              message,
              next_fire_at::text,
              timezone,
              rrule,
              status,
              target_channel,
              target_address,
              last_fired_at::text,
              last_error,
              created_at::text,
              updated_at::text
            """,
            (
                payload.message,
                payload.next_fire_at,
                payload.timezone,
                payload.rrule,
                payload.target_channel,
                payload.target_address,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "id": row[0],
            "message": row[1],
            "next_fire_at": row[2],
            "timezone": row[3],
            "rrule": row[4],
            "status": row[5],
            "target_channel": row[6],
            "target_address": row[7],
            "last_fired_at": row[8],
            "last_error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
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


@router.get("", response_model=List[ReminderOut])
def list_reminders(
    status: Optional[str] = None,
    target_channel: Optional[str] = None,
    target_address: Optional[str] = None,
):
    _validate_enums(target_channel, status)

    where = []
    values = []

    if status:
        where.append("status = %s")
        values.append(status)
    if target_channel:
        where.append("target_channel = %s")
        values.append(target_channel)
    if target_address:
        where.append("target_address = %s")
        values.append(target_address)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
              id::text,
              message,
              next_fire_at::text,
              timezone,
              rrule,
              status,
              target_channel,
              target_address,
              last_fired_at::text,
              last_error,
              created_at::text,
              updated_at::text
            FROM reminders
            {where_sql}
            ORDER BY next_fire_at ASC
            LIMIT 200
            """,
            tuple(values),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "message": r[1],
                "next_fire_at": r[2],
                "timezone": r[3],
                "rrule": r[4],
                "status": r[5],
                "target_channel": r[6],
                "target_address": r[7],
                "last_fired_at": r[8],
                "last_error": r[9],
                "created_at": r[10],
                "updated_at": r[11],
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


@router.patch("/{reminder_id}", response_model=ReminderOut)
def patch_reminder(reminder_id: str, payload: ReminderPatch):
    _validate_enums(payload.target_channel, payload.status)

    fields = []
    values: List[Any] = []

    if payload.message is not None:
        fields.append("message = %s")
        values.append(payload.message)
    if payload.next_fire_at is not None:
        fields.append("next_fire_at = %s")
        values.append(payload.next_fire_at)
    if payload.timezone is not None:
        fields.append("timezone = %s")
        values.append(payload.timezone)
    # Allow clearing rrule by explicitly sending rrule: null
    if "rrule" in payload.model_fields_set:
        fields.append("rrule = %s")
        values.append(payload.rrule)
    if payload.status is not None:
        fields.append("status = %s")
        values.append(payload.status)
    if payload.target_channel is not None:
        fields.append("target_channel = %s")
        values.append(payload.target_channel)
    if payload.target_address is not None:
        fields.append("target_address = %s")
        values.append(payload.target_address)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields.append("updated_at = now()")

    connector = None
    conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        sql = f"""
        UPDATE reminders
        SET {", ".join(fields)}
        WHERE id = %s::uuid
        RETURNING
          id::text,
          message,
          next_fire_at::text,
          timezone,
          rrule,
          status,
          target_channel,
          target_address,
          last_fired_at::text,
          last_error,
          created_at::text,
          updated_at::text
        """
        values.append(reminder_id)

        cur.execute(sql, tuple(values))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Reminder not found")

        conn.commit()
        return {
            "id": row[0],
            "message": row[1],
            "next_fire_at": row[2],
            "timezone": row[3],
            "rrule": row[4],
            "status": row[5],
            "target_channel": row[6],
            "target_address": row[7],
            "last_fired_at": row[8],
            "last_error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
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

@internal_router.post("/tick")
def reminders_tick(x_reminders_tick_secret: str = Header(default="", alias="X-Reminders-Tick-Secret")):
    expected = os.environ.get("REMINDERS_TICK_SECRET", "")
    if not expected or x_reminders_tick_secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    connector = None
    conn = None
    processed = 0
    done = 0
    errored = 0

    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id::text, rrule
            FROM reminders
            WHERE status = 'scheduled'
              AND next_fire_at <= now()
            ORDER BY next_fire_at ASC
            LIMIT 50
            """
        )
        rows = cur.fetchall()

        for reminder_id, rrule in rows:
            processed += 1
            if rrule:
                cur.execute(
                    """
                    UPDATE reminders
                    SET status = 'error',
                        last_error = %s,
                        updated_at = now()
                    WHERE id = %s::uuid
                    """,
                    ("RRULE tick not implemented yet", reminder_id),
                )
                errored += 1
            else:
                cur.execute(
                    """
                    UPDATE reminders
                    SET status = 'done',
                        last_fired_at = now(),
                        updated_at = now()
                    WHERE id = %s::uuid
                    """,
                    (reminder_id,),
                )
                done += 1

        conn.commit()
        return {"ok": True, "processed": processed, "done": done, "errored": errored}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tick failed: {repr(e)}")
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

