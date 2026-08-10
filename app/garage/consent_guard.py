from __future__ import annotations

from flask import abort, render_template, request
from sqlalchemy import text

from app.extensions import db
from . import garage_bp
from .memory_store import DEMO_VEHICLE_KEY, _table, ensure_schema


def _consent_status(vehicle_key: str) -> tuple[str | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    vehicles = _table("vehicles")
    onboard = _table("onboarding_requests")
    try:
        with db.engine.begin() as conn:
            row = conn.execute(text(f"""
                SELECT o.status
                  FROM {onboard} o
                  JOIN {vehicles} v ON v.id=o.vehicle_id
                 WHERE v.external_key=:vehicle_key
                 ORDER BY o.created_at DESC
                 LIMIT 1
            """), {"vehicle_key": vehicle_key}).mappings().first()
        return (row["status"] if row else None), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _vehicle_key_for_request() -> str | None:
    if request.endpoint == "garage.vehicle_garage":
        return (request.view_args or {}).get("vehicle_key")
    if request.endpoint in ("garage.import_lab", "garage.confirm_candidates"):
        return (request.args.get("vehicle") or request.form.get("vehicle_key") or "").strip() or None
    return None


@garage_bp.before_request
def enforce_vehicle_consent():
    if request.endpoint not in ("garage.vehicle_garage", "garage.import_lab", "garage.confirm_candidates"):
        return None

    vehicle_key = _vehicle_key_for_request()
    if not vehicle_key or vehicle_key == DEMO_VEHICLE_KEY:
        return None

    status, error = _consent_status(vehicle_key)
    if error:
        return render_template("garage/unavailable.html", error=error), 503
    if status is None:
        abort(404)
    if status != "accepted":
        return render_template(
            "garage/consent_required.html",
            vehicle_key=vehicle_key,
            status=status,
        ), 403
    return None
