from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db import get_db_conn


def _close(connector, conn) -> None:
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


def ensure_service(
    *,
    slug: str,
    name: str,
    category: str,
    vendor: str,
    owner_department: str | None = None,
) -> str:
    """Ensure a service exists; returns service_id."""
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO external_services (name, slug, category, vendor, owner_department)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name,
              category = EXCLUDED.category,
              vendor = EXCLUDED.vendor,
              owner_department = COALESCE(EXCLUDED.owner_department, external_services.owner_department),
              updated_at = now()
            RETURNING id::text
            """,
            (name, slug, category, vendor, owner_department),
        )
        service_id = cur.fetchone()[0]
        conn.commit()
        return service_id
    finally:
        _close(connector, conn)


def ensure_endpoint(*, service_id: str, name: str, unit_type: str = "requests") -> str:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO external_service_endpoints (service_id, name, unit_type)
            VALUES (%s::uuid, %s, %s)
            ON CONFLICT (service_id, name) DO UPDATE SET
              unit_type = EXCLUDED.unit_type,
              updated_at = now()
            RETURNING id::text
            """,
            (service_id, name, unit_type),
        )
        endpoint_id = cur.fetchone()[0]
        conn.commit()
        return endpoint_id
    finally:
        _close(connector, conn)


def log_event(
    *,
    service_slug: str,
    service_name: str,
    category: str,
    vendor: str,
    endpoint_name: str,
    event_type: str,
    success: bool,
    status_code: int | None,
    latency_ms: int | None,
    department: str | None,
    agent: str | None,
    workflow_id: str | None,
    job_id: str | None,
    input_units: float | None = None,
    output_units: float | None = None,
    estimated_cost: float | None = None,
    currency: str = "USD",
    error_summary: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> None:
    """Append one event row and update last_success/last_failure on the service."""

    service_id = ensure_service(slug=service_slug, name=service_name, category=category, vendor=vendor, owner_department=department)
    endpoint_id = ensure_endpoint(service_id=service_id, name=endpoint_name)

    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO external_service_events (
              service_id, endpoint_id, department, agent, workflow_id, job_id,
              event_type, success, status_code, latency_ms,
              input_units, output_units, estimated_cost, currency,
              error_summary, raw_metadata_json
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s::jsonb
            )
            """,
            (
                service_id,
                endpoint_id,
                department,
                agent,
                workflow_id,
                job_id,
                event_type,
                bool(success),
                status_code,
                latency_ms,
                input_units,
                output_units,
                estimated_cost,
                currency,
                error_summary,
                __import__("json").dumps(raw_metadata or {}),
            ),
        )

        if success:
            cur.execute(
                """UPDATE external_services SET last_success_at=now(), updated_at=now() WHERE id=%s::uuid""",
                (service_id,),
            )
        else:
            cur.execute(
                """UPDATE external_services SET last_failure_at=now(), updated_at=now() WHERE id=%s::uuid""",
                (service_id,),
            )

        conn.commit()
    finally:
        _close(connector, conn)
