#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 - <<'PY'
from pathlib import Path
import re

# ---------- helpers ----------
def ensure_line_after(text: str, needle: str, insert: str) -> str:
    if insert.strip() in text:
        return text
    idx = text.find(needle)
    if idx == -1:
        raise SystemExit(f"Could not find needle: {needle!r}")
    idx_end = idx + len(needle)
    return text[:idx_end] + insert + text[idx_end:]

def file_has(path: Path, pattern: str) -> bool:
    return re.search(pattern, path.read_text(encoding="utf-8"), re.M) is not None

# ---------- edit reminders.py ----------
reminders = Path("reminders.py")
if not reminders.exists():
    raise SystemExit("reminders.py not found (are you in the right repo?)")

r = reminders.read_text(encoding="utf-8")

# 1) ensure `import os`
if re.search(r'^\s*import os\s*$', r, re.M) is None:
    # Insert after __future__ import block if present, else at top
    m = re.search(r'^(from __future__ import[^\n]*\n)(\n*)', r, re.M)
    if m:
        insert_at = m.end(1)
        r = r[:insert_at] + "\nimport os\n" + r[insert_at:]
    else:
        r = "import os\n" + r

# 2) ensure Header in fastapi import
# handle: from fastapi import APIRouter, HTTPException
m = re.search(r'^from fastapi import (.+)$', r, re.M)
if not m:
    raise SystemExit("Could not find 'from fastapi import ...' in reminders.py")

imports = [s.strip() for s in m.group(1).split(",")]
need = {"APIRouter", "HTTPException", "Header"}
if not need.issubset(set(imports)):
    merged = sorted(set(imports) | need, key=lambda x: ["APIRouter","HTTPException","Header"].index(x) if x in ["APIRouter","HTTPException","Header"] else 999)
    new_line = "from fastapi import " + ", ".join(merged)
    r = re.sub(r'^from fastapi import .+$', new_line, r, flags=re.M)

# 3) ensure internal_router exists
if re.search(r'^\s*internal_router\s*=\s*APIRouter\(', r, re.M) is None:
    # Insert right after existing router definition line
    m = re.search(r'^\s*router\s*=\s*APIRouter\(.*\)\s*$', r, re.M)
    if not m:
        raise SystemExit("Could not find router = APIRouter(...) in reminders.py")
    insert_pos = m.end(0)
    r = r[:insert_pos] + "\n\ninternal_router = APIRouter(prefix=\"/internal/reminders\", tags=[\"internal\"])\n" + r[insert_pos:]

# 4) ensure tick endpoint appended
if "def reminders_tick(" not in r:
    tick = r'''

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
'''
    r = r.rstrip() + tick + "\n"

reminders.write_text(r, encoding="utf-8")

# ---------- edit main.py ----------
main = Path("main.py")
m = main.read_text(encoding="utf-8")

# Ensure main imports internal_router too
if re.search(r'^from reminders import router as reminders_router', m, re.M):
    m = re.sub(
        r'^from reminders import router as reminders_router\s*$',
        'from reminders import router as reminders_router, internal_router as reminders_internal_router',
        m,
        flags=re.M
    )
elif re.search(r'^from reminders import router as reminders_router, internal_router as reminders_internal_router', m, re.M) is None:
    # If there's no reminders import at all, add it next to other router imports
    # Insert after approvals import line if present
    if "from approvals import router as approvals_router" in m:
        m = m.replace(
            "from approvals import router as approvals_router",
            "from approvals import router as approvals_router\nfrom reminders import router as reminders_router, internal_router as reminders_internal_router"
        )
    else:
        raise SystemExit("Couldn't find where to insert reminders import in main.py")

# Ensure include_router for internal router exists (right after reminders_router include)
if "app.include_router(reminders_internal_router)" not in m:
    if "app.include_router(reminders_router)" in m:
        m = m.replace(
            "app.include_router(reminders_router)",
            "app.include_router(reminders_router)\napp.include_router(reminders_internal_router)"
        )
    else:
        # If reminders_router isn't included yet, add both after approvals include
        if "app.include_router(approvals_router)" in m:
            m = m.replace(
                "app.include_router(approvals_router)",
                "app.include_router(approvals_router)\napp.include_router(reminders_router)\napp.include_router(reminders_internal_router)"
            )
        else:
            raise SystemExit("Couldn't find app.include_router(...) block in main.py")

main.write_text(m, encoding="utf-8")
print("Updated reminders.py + main.py")
PY

echo "Running quick syntax check..."
python3 -m py_compile reminders.py main.py

echo "Git status:"
git status --porcelain

if [[ -n "$(git status --porcelain)" ]]; then
  git add -A
  git commit -m "Add internal reminders tick endpoint (stubbed)"
  git push public main
  echo "Done: committed + pushed."
else
  echo "No changes to commit (already applied)."
fi
