import os
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from google.cloud.sql.connector import Connector
from anthropic import Anthropic

app = FastAPI()

from scribe import router as scribe_router
app.include_router(scribe_router)



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


# -------------------------
# Scribe (LinkedIn) MVP
# -------------------------
class ScribeLinkedInRequest(BaseModel):
    topic: str = Field(..., description="What the post is about")
    angle: Optional[str] = Field(None, description="Optional framing/angle")
    audience: Optional[str] = Field(None, description="Optional audience hint")
    num_sources: int = Field(5, ge=3, le=10, description="How many web sources to use")


class ScribeSource(BaseModel):
    title: str
    link: str
    snippet: Optional[str] = None


class ScribeLinkedInResponse(BaseModel):
    post: str
    citations: List[ScribeSource]
    research_packet: Dict[str, Any]


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise HTTPException(status_code=500, detail=f"Missing env var: {name}")
    return v


def serper_search(query: str, num: int = 5) -> List[ScribeSource]:
    api_key = _get_env("SERPER_API_KEY")
    payload = {"q": query, "num": num}

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Serper search failed: {repr(e)}")

    organic = data.get("organic", []) or []
    sources: List[ScribeSource] = []
    for item in organic[:num]:
        title = item.get("title") or ""
        link = item.get("link") or ""
        snippet = item.get("snippet")
        if title and link:
            sources.append(ScribeSource(title=title, link=link, snippet=snippet))
    return sources


def quill_linkedin_post(topic: str, angle: Optional[str], audience: Optional[str], sources: List[ScribeSource]) -> str:
    anthropic_key = _get_env("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=anthropic_key)

    # Very compact “voice” instruction from your LinkedIn master canvas + BdGAdvisory framing.
    voice_rules = """You are Quill writing a LinkedIn post in Bart de Graaff / BdGAdvisory voice.

Tone:
- Controlled but human; reflective, not performative.
- Calm, precise, measured. Executive tone.
- No hype, no clichés, no LinkedIn theater.

Frame:
- Structural lens: incentives, governance, capital pressure, commercial sequencing shape execution.
- Authority through pattern recognition and lived experience (operator–builder), not assertion.

Format:
- Mobile-friendly line breaks.
- Short paragraphs.
- End with a crisp takeaway or a thoughtful question.
- Do not fabricate facts; cite only what is supported by provided sources.
"""

    source_block = "\n".join([f"- {s.title}\n  {s.link}\n  {s.snippet or ''}".strip() for s in sources])

    user_prompt = f"""Write a LinkedIn post.

Topic: {topic}
Angle (optional): {angle or 'none'}
Audience (optional): {audience or 'none'}

Use these sources as your factual substrate (you may generalize, but do not invent specifics):
{source_block}

Output ONLY the post text.
"""

    try:
        msg = client.messages.create(
            # We'll start with a stable “latest Sonnet” alias; we can pin later.
            model=os.getenv("ANTHROPIC_MODEL","claude-3-5-sonnet-20241022"),
            max_tokens=700,
            temperature=0.5,
            system=voice_rules,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # anthropic SDK returns a list of content blocks; join text blocks.
        parts = []
        for b in msg.content:
            if getattr(b, "type", None) == "text":
                parts.append(b.text)
        return "\n".join(parts).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Anthropic Quill failed: {repr(e)}")


@app.post("/scribe/linkedin", response_model=ScribeLinkedInResponse)
def scribe_linkedin(payload: ScribeLinkedInRequest):
    # Scout query formulation (cheap logic, no model yet)
    q = payload.topic.strip()
    if payload.angle:
        q = f"{q} {payload.angle.strip()}"
    # Bias toward your canonical themes
    q = f"{q} incentives governance capital execution"

    sources = serper_search(q, num=payload.num_sources)

    post = quill_linkedin_post(
        topic=payload.topic,
        angle=payload.angle,
        audience=payload.audience,
        sources=sources,
    )

    research_packet = {
        "query": q,
        "sources": [s.model_dump() for s in sources],
    }

    return ScribeLinkedInResponse(
        post=post,
        citations=sources,
        research_packet=research_packet,
    )
