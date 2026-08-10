from __future__ import annotations

from sqlalchemy import text

from app.extensions import db
from .memory_store import _table, ensure_schema


def provider_fleet(source: str = "centerfix") -> tuple[list[dict], dict, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], {}, error

    vehicles = _table("vehicles")
    onboard = _table("onboarding_requests")
    sessions = _table("import_sessions")
    candidates = _table("import_candidates")
    events = _table("vehicle_events")
    issues = _table("vehicle_issues")

    try:
        with db.engine.begin() as conn:
            rows = conn.execute(text(f"""
                SELECT
                    o.id AS invitation_id,
                    o.status AS invitation_status,
                    o.created_at AS invited_at,
                    o.consented_at,
                    v.external_key,
                    v.owner_name,
                    v.make,
                    v.model,
                    v.model_year,
                    v.odometer_km,
                    (SELECT COUNT(*) FROM {sessions} s WHERE s.vehicle_id=v.id) AS import_sessions,
                    (SELECT COUNT(*) FROM {candidates} c WHERE c.vehicle_id=v.id AND c.verification_status='ai_candidate') AS pending_candidates,
                    (SELECT COUNT(*) FROM {events} e WHERE e.vehicle_id=v.id) AS confirmed_events,
                    (SELECT COALESCE(SUM(e.total_cost),0) FROM {events} e WHERE e.vehicle_id=v.id) AS documented_spend,
                    (SELECT COUNT(*) FROM {issues} i WHERE i.vehicle_id=v.id AND i.status='open') AS open_issues
                FROM {onboard} o
                JOIN {vehicles} v ON v.id=o.vehicle_id
                WHERE o.source=:source
                ORDER BY o.created_at DESC
            """), {"source": source}).mappings().all()

        fleet = [dict(row) for row in rows]
        stats = {
            "vehicles": len(fleet),
            "accepted": sum(1 for item in fleet if item.get("invitation_status") == "accepted"),
            "with_memory": sum(1 for item in fleet if int(item.get("confirmed_events") or 0) > 0),
            "pending_candidates": sum(int(item.get("pending_candidates") or 0) for item in fleet),
            "confirmed_events": sum(int(item.get("confirmed_events") or 0) for item in fleet),
            "open_issues": sum(int(item.get("open_issues") or 0) for item in fleet),
        }
        return fleet, stats, None
    except Exception as exc:
        return [], {}, f"{type(exc).__name__}: {exc}"
