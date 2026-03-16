import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_db_conn

router = APIRouter(prefix="/api/external-services", tags=["external-services"])


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


def _period_start_sql() -> str:
    # MVP: current month
    return "date_trunc('month', now())"


@router.get("/summary")
def summary() -> Dict[str, Any]:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM external_services")
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT
              count(*) FILTER (WHERE enabled) AS enabled,
              count(*) FILTER (WHERE health_status IN ('warning','degraded','rate_limited','auth_failed','billing_problem','budget_limited')) AS warnings,
              count(*) FILTER (WHERE billing_status IN ('paid_past_due','payment_failed')) AS billing_issues
            FROM external_services
            """
        )
        enabled, warnings, billing_issues = cur.fetchone()

        cur.execute(
            f"""
            SELECT COALESCE(sum(estimated_cost),0)
            FROM external_service_events
            WHERE timestamp >= {_period_start_sql()}
            """
        )
        spend = float(cur.fetchone()[0] or 0)

        return {
            "ok": True,
            "period": "month",
            "total_services": int(total),
            "enabled": int(enabled or 0),
            "warnings": int(warnings or 0),
            "billing_issues": int(billing_issues or 0),
            "estimated_spend": spend,
            "currency": "USD",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"summary failed: {repr(e)}")
    finally:
        _close(connector, conn)


@router.get("")
def list_services() -> Dict[str, Any]:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT
              s.slug,
              s.name,
              s.vendor,
              s.category,
              s.enabled,
              s.criticality,
              s.payment_model,
              s.billing_status,
              s.auth_status,
              s.health_status,
              s.routing_role,
              s.owner_department,
              s.budget_amount,
              s.budget_currency,
              s.last_success_at::text,
              s.last_failure_at::text,
              COALESCE(ev.used,0) as used
            FROM external_services s
            LEFT JOIN (
              SELECT service_id, COALESCE(sum(estimated_cost),0) as used
              FROM external_service_events
              WHERE timestamp >= {_period_start_sql()}
              GROUP BY service_id
            ) ev ON ev.service_id = s.id
            ORDER BY s.category, s.slug
            """
        )

        rows = cur.fetchall()
        items: List[Dict[str, Any]] = []
        for r in rows:
            budget = float(r[12]) if r[12] is not None else None
            used = float(r[16] or 0)
            remaining = None
            if budget is not None:
                remaining = max(budget - used, 0.0)
            items.append(
                {
                    "slug": r[0],
                    "name": r[1],
                    "vendor": r[2],
                    "category": r[3],
                    "enabled": bool(r[4]),
                    "criticality": r[5],
                    "payment_model": r[6],
                    "billing_status": r[7],
                    "auth_status": r[8],
                    "health_status": r[9],
                    "routing_role": r[10],
                    "owner_department": r[11],
                    "budget_amount": budget,
                    "budget_currency": r[13] or "USD",
                    "used": used,
                    "remaining": remaining,
                    "usage_unit": "USD",
                    "last_success_at": r[14],
                    "last_failure_at": r[15],
                }
            )

        return {"ok": True, "period": "month", "items": items}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list failed: {repr(e)}")
    finally:
        _close(connector, conn)


@router.get("/{slug}")
def get_service(slug: str) -> Dict[str, Any]:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id::text, slug, name, vendor, category, enabled, criticality,
                   payment_model, billing_status, auth_status, health_status,
                   routing_role, owner_department, budget_amount, budget_currency,
                   notes, last_success_at::text, last_failure_at::text
            FROM external_services
            WHERE slug = %s
            """,
            (slug,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="service not found")

        service_id = row[0]

        cur.execute(
            """SELECT id::text, name, service_type, unit_type, input_unit_price, output_unit_price, flat_price, pricing_version, active
               FROM external_service_endpoints WHERE service_id=%s::uuid ORDER BY name""",
            (service_id,),
        )
        eps = []
        for e in cur.fetchall():
            eps.append(
                {
                    "id": e[0],
                    "name": e[1],
                    "service_type": e[2],
                    "unit_type": e[3],
                    "input_unit_price": float(e[4]) if e[4] is not None else None,
                    "output_unit_price": float(e[5]) if e[5] is not None else None,
                    "flat_price": float(e[6]) if e[6] is not None else None,
                    "pricing_version": e[7],
                    "active": bool(e[8]),
                }
            )

        return {
            "ok": True,
            "service": {
                "id": row[0],
                "slug": row[1],
                "name": row[2],
                "vendor": row[3],
                "category": row[4],
                "enabled": bool(row[5]),
                "criticality": row[6],
                "payment_model": row[7],
                "billing_status": row[8],
                "auth_status": row[9],
                "health_status": row[10],
                "routing_role": row[11],
                "owner_department": row[12],
                "budget_amount": float(row[13]) if row[13] is not None else None,
                "budget_currency": row[14] or "USD",
                "notes": row[15],
                "last_success_at": row[16],
                "last_failure_at": row[17],
            },
            "endpoints": eps,
        }

    finally:
        _close(connector, conn)


@router.get("/{slug}/events")
def events(slug: str, limit: int = 100) -> Dict[str, Any]:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM external_services WHERE slug=%s", (slug,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="service not found")

        service_id = r[0]
        cur.execute(
            """
            SELECT timestamp::text, event_type, success, status_code, latency_ms,
                   input_units, output_units, estimated_cost, currency,
                   department, agent, workflow_id, job_id, error_summary
            FROM external_service_events
            WHERE service_id=%s::uuid
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (service_id, min(int(limit), 500)),
        )
        items = []
        for e in cur.fetchall():
            items.append(
                {
                    "timestamp": e[0],
                    "event_type": e[1],
                    "success": bool(e[2]),
                    "status_code": e[3],
                    "latency_ms": e[4],
                    "input_units": float(e[5]) if e[5] is not None else None,
                    "output_units": float(e[6]) if e[6] is not None else None,
                    "estimated_cost": float(e[7]) if e[7] is not None else None,
                    "currency": e[8],
                    "department": e[9],
                    "agent": e[10],
                    "workflow_id": e[11],
                    "job_id": e[12],
                    "error_summary": e[13],
                }
            )

        return {"ok": True, "items": items}

    finally:
        _close(connector, conn)


class BudgetPatch(BaseModel):
    budget_amount: Optional[float] = None
    budget_currency: Optional[str] = None
    soft_limit_pct: Optional[float] = None
    hard_limit_pct: Optional[float] = None


@router.post("/{slug}/enable")
def enable(slug: str) -> Dict[str, Any]:
    return _set_enabled(slug, True)


@router.post("/{slug}/disable")
def disable(slug: str) -> Dict[str, Any]:
    return _set_enabled(slug, False)


def _set_enabled(slug: str, enabled: bool) -> Dict[str, Any]:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """UPDATE external_services SET enabled=%s, updated_at=now() WHERE slug=%s RETURNING slug""",
            (enabled, slug),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="service not found")
        conn.commit()
        return {"ok": True, "slug": slug, "enabled": enabled}
    finally:
        _close(connector, conn)


@router.post("/{slug}/budget")
def set_budget(slug: str, patch: BudgetPatch) -> Dict[str, Any]:
    connector = conn = None
    try:
        connector, conn = get_db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE external_services
            SET budget_amount = COALESCE(%s, budget_amount),
                budget_currency = COALESCE(%s, budget_currency),
                soft_limit_pct = COALESCE(%s, soft_limit_pct),
                hard_limit_pct = COALESCE(%s, hard_limit_pct),
                updated_at = now()
            WHERE slug=%s
            RETURNING slug
            """,
            (patch.budget_amount, patch.budget_currency, patch.soft_limit_pct, patch.hard_limit_pct, slug),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="service not found")
        conn.commit()
        return {"ok": True, "slug": slug}
    finally:
        _close(connector, conn)
