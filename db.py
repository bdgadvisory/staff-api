import os
from google.cloud.sql.connector import Connector


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
