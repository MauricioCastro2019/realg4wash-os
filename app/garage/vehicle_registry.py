from __future__ import annotations

from sqlalchemy import text

from app.extensions import db
from .memory_store import _table, ensure_schema


def get_vehicle(external_key: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    vehicles = _table("vehicles")
    try:
        with db.engine.begin() as conn:
            row = conn.execute(
                text(f"SELECT * FROM {vehicles} WHERE external_key=:key"),
                {"key": external_key},
            ).mappings().first()
        return (dict(row) if row else None), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def restore_vehicle_identity(external_key: str, vehicle: dict | None) -> None:
    if not vehicle:
        return
    ok, _ = ensure_schema()
    if not ok:
        return
    vehicles = _table("vehicles")
    try:
        with db.engine.begin() as conn:
            conn.execute(text(f"""
                UPDATE {vehicles}
                   SET owner_name=:owner_name, make=:make, model=:model,
                       model_year=:model_year, source=:source
                 WHERE external_key=:external_key
            """), {
                "owner_name": vehicle.get("owner_name"),
                "make": vehicle.get("make") or "Vehículo",
                "model": vehicle.get("model") or "Sin modelo",
                "model_year": vehicle.get("model_year"),
                "source": vehicle.get("source") or "owner",
                "external_key": external_key,
            })
    except Exception:
        pass


def list_issues(external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    vehicles = _table("vehicles")
    issues = _table("vehicle_issues")
    try:
        with db.engine.begin() as conn:
            vehicle = conn.execute(
                text(f"SELECT id FROM {vehicles} WHERE external_key=:key"),
                {"key": external_key},
            ).mappings().first()
            if not vehicle:
                return [], None
            rows = conn.execute(text(f"""
                SELECT * FROM {issues}
                 WHERE vehicle_id=:vehicle_id AND status='open'
                 ORDER BY CASE WHEN last_seen IS NULL THEN 1 ELSE 0 END, last_seen DESC
            """), {"vehicle_id": vehicle["id"]}).mappings().all()
        return [dict(row) for row in rows], None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def update_odometer(external_key: str, odometer_km: int | None) -> None:
    if not odometer_km:
        return
    ok, _ = ensure_schema()
    if not ok:
        return
    vehicles = _table("vehicles")
    try:
        with db.engine.begin() as conn:
            conn.execute(text(f"""
                UPDATE {vehicles}
                   SET odometer_km=CASE
                       WHEN odometer_km IS NULL OR :km > odometer_km THEN :km
                       ELSE odometer_km END
                 WHERE external_key=:key
            """), {"km": int(odometer_km), "key": external_key})
    except Exception:
        pass
