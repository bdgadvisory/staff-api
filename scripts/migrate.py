import os
from pathlib import Path
from google.cloud.sql.connector import Connector

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v

def connect():
    instance_conn = env("INSTANCE_CONNECTION_NAME")
    db = env("DB_NAME")
    user = env("DB_USER")
    password = env("DB_PASSWORD")

    connector = Connector()
    conn = connector.connect(
        instance_conn,
        "pg8000",
        user=user,
        password=password,
        db=db,
    )
    return connector, conn

def ensure_schema_migrations(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)

def applied_versions(cur):
    cur.execute("SELECT version FROM schema_migrations;")
    return {r[0] for r in cur.fetchall()}

def apply_migration(cur, version: str, sql: str):
    cur.execute(sql)
    cur.execute("INSERT INTO schema_migrations(version) VALUES (%s);", (version,))

def main():
    connector = None
    conn = None
    try:
        connector, conn = connect()
        cur = conn.cursor()
        ensure_schema_migrations(cur)
        conn.commit()

        applied = applied_versions(cur)
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        pending = []
        for p in files:
            version = p.name.split("_", 1)[0]
            if version not in applied:
                pending.append((version, p))

        if not pending:
            print("No pending migrations.")
            return

        for version, path in pending:
            sql = path.read_text(encoding="utf-8")
            print(f"Applying {path.name} ...")
            apply_migration(cur, version, sql)

        conn.commit()
        print("Migrations applied:", ", ".join([p.name for _, p in pending]))

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

if __name__ == "__main__":
    main()
