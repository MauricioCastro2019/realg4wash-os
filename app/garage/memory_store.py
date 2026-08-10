from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text

from app.extensions import db


_BOOTSTRAPPED = False
DEMO_VEHICLE_KEY = "demo-gol-2015"


def _is_postgres() -> bool:
    return db.engine.dialect.name == "postgresql"


def _table(name: str) -> str:
    return f"mi_auto_pro.{name}" if _is_postgres() else f"mi_auto_pro_{name}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _execute_ddl(conn) -> None:
    if _is_postgres():
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS mi_auto_pro"))

    vehicles = _table("vehicles")
    sessions = _table("import_sessions")
    artifacts = _table("source_artifacts")
    candidates = _table("import_candidates")
    events = _table("vehicle_events")
    issues = _table("vehicle_issues")
    onboard = _table("onboarding_requests")

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {vehicles} (
            id VARCHAR(36) PRIMARY KEY,
            external_key VARCHAR(120) UNIQUE NOT NULL,
            owner_name VARCHAR(180),
            make VARCHAR(80) NOT NULL,
            model VARCHAR(80) NOT NULL,
            model_year INTEGER,
            source VARCHAR(80) NOT NULL DEFAULT 'owner',
            odometer_km INTEGER,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        )
    """))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {sessions} (
            id VARCHAR(36) PRIMARY KEY,
            vehicle_id VARCHAR(36) NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'review',
            source_count INTEGER NOT NULL DEFAULT 0,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            confirmed_count INTEGER NOT NULL DEFAULT 0,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        )
    """))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {artifacts} (
            id VARCHAR(36) PRIMARY KEY,
            import_session_id VARCHAR(36) NOT NULL,
            vehicle_id VARCHAR(36) NOT NULL,
            filename TEXT NOT NULL,
            source_kind VARCHAR(60),
            sha256 VARCHAR(64),
            byte_size INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at VARCHAR(40) NOT NULL
        )
    """))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {candidates} (
            id VARCHAR(36) PRIMARY KEY,
            import_session_id VARCHAR(36) NOT NULL,
            vehicle_id VARCHAR(36) NOT NULL,
            occurred_on VARCHAR(20),
            title TEXT NOT NULL,
            category VARCHAR(80) NOT NULL,
            total_cost INTEGER,
            odometer_km INTEGER,
            codes_json TEXT NOT NULL DEFAULT '[]',
            excerpt TEXT,
            confidence INTEGER NOT NULL DEFAULT 0,
            evidence_count INTEGER NOT NULL DEFAULT 1,
            source_type VARCHAR(80),
            source_actor VARCHAR(80),
            source_file TEXT,
            verification_status VARCHAR(40) NOT NULL DEFAULT 'ai_candidate',
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        )
    """))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {events} (
            id VARCHAR(36) PRIMARY KEY,
            vehicle_id VARCHAR(36) NOT NULL,
            candidate_id VARCHAR(36) UNIQUE,
            occurred_on VARCHAR(20),
            title TEXT NOT NULL,
            category VARCHAR(80) NOT NULL,
            total_cost INTEGER,
            odometer_km INTEGER,
            codes_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT,
            source_type VARCHAR(80),
            verification_status VARCHAR(40) NOT NULL DEFAULT 'owner_confirmed',
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        )
    """))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {issues} (
            id VARCHAR(36) PRIMARY KEY,
            vehicle_id VARCHAR(36) NOT NULL,
            code VARCHAR(40),
            title TEXT NOT NULL,
            category VARCHAR(80),
            status VARCHAR(30) NOT NULL DEFAULT 'open',
            first_seen VARCHAR(20),
            last_seen VARCHAR(20),
            source_event_id VARCHAR(36),
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        )
    """))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {onboard} (
            id VARCHAR(36) PRIMARY KEY,
            invite_token VARCHAR(120) UNIQUE NOT NULL,
            vehicle_id VARCHAR(36) NOT NULL,
            owner_name VARCHAR(180) NOT NULL,
            source VARCHAR(80) NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'invited',
            consented_at VARCHAR(40),
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        )
    """))


def ensure_schema() -> tuple[bool, str | None]:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return True, None
    try:
        with db.engine.begin() as conn:
            _execute_ddl(conn)
        _BOOTSTRAPPED = True
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def ensure_vehicle(
    external_key: str,
    *,
    owner_name: str | None,
    make: str,
    model: str,
    model_year: int | None = None,
    source: str = "owner",
    odometer_km: int | None = None,
) -> dict | None:
    ok, _ = ensure_schema()
    if not ok:
        return None
    vehicles = _table("vehicles")
    with db.engine.begin() as conn:
        row = conn.execute(text(f"SELECT * FROM {vehicles} WHERE external_key=:k"), {"k": external_key}).mappings().first()
        now = _now()
        if row:
            conn.execute(text(f"""
                UPDATE {vehicles}
                   SET owner_name=COALESCE(:owner_name, owner_name), make=:make, model=:model,
                       model_year=COALESCE(:model_year, model_year), source=:source,
                       odometer_km=COALESCE(:odometer_km, odometer_km), updated_at=:updated_at
                 WHERE external_key=:external_key
            """), {
                "owner_name": owner_name, "make": make, "model": model, "model_year": model_year,
                "source": source, "odometer_km": odometer_km, "updated_at": now, "external_key": external_key,
            })
            return dict(conn.execute(text(f"SELECT * FROM {vehicles} WHERE external_key=:k"), {"k": external_key}).mappings().first())

        vehicle_id = _id()
        conn.execute(text(f"""
            INSERT INTO {vehicles}
                (id, external_key, owner_name, make, model, model_year, source, odometer_km, created_at, updated_at)
            VALUES
                (:id, :external_key, :owner_name, :make, :model, :model_year, :source, :odometer_km, :created_at, :updated_at)
        """), {
            "id": vehicle_id, "external_key": external_key, "owner_name": owner_name,
            "make": make, "model": model, "model_year": model_year, "source": source,
            "odometer_km": odometer_km, "created_at": now, "updated_at": now,
        })
        return dict(conn.execute(text(f"SELECT * FROM {vehicles} WHERE id=:id"), {"id": vehicle_id}).mappings().first())


def ensure_demo_vehicle(history: Iterable[dict]) -> dict | None:
    vehicle = ensure_vehicle(
        DEMO_VEHICLE_KEY,
        owner_name=None,
        make="Volkswagen",
        model="Gol",
        model_year=2015,
        source="reconstructed",
        odometer_km=166895,
    )
    if not vehicle:
        return None

    events = _table("vehicle_events")
    with db.engine.begin() as conn:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {events} WHERE vehicle_id=:v AND source_type='reconstructed_seed'"), {"v": vehicle["id"]}).scalar() or 0
        if count == 0:
            now = _now()
            for item in history:
                conn.execute(text(f"""
                    INSERT INTO {events}
                        (id, vehicle_id, candidate_id, occurred_on, title, category, total_cost, odometer_km,
                         codes_json, notes, source_type, verification_status, created_at, updated_at)
                    VALUES
                        (:id, :vehicle_id, NULL, :occurred_on, :title, :category, :total_cost, :odometer_km,
                         '[]', :notes, 'reconstructed_seed', 'evidence_verified', :created_at, :updated_at)
                """), {
                    "id": _id(), "vehicle_id": vehicle["id"], "occurred_on": item.get("iso_date") or item.get("date"),
                    "title": item.get("title") or "Evento", "category": item.get("category") or "Reparación",
                    "total_cost": item.get("cost"), "odometer_km": item.get("km"), "notes": item.get("notes") or "",
                    "created_at": now, "updated_at": now,
                })
    return vehicle


def save_import(vehicle_external_key: str, uploads: list[dict], candidates_payload: list[dict]) -> tuple[str | None, list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, candidates_payload, error

    vehicle = ensure_vehicle(
        vehicle_external_key,
        owner_name=None,
        make="Volkswagen" if vehicle_external_key == DEMO_VEHICLE_KEY else "Pendiente",
        model="Gol" if vehicle_external_key == DEMO_VEHICLE_KEY else "Vehículo",
        model_year=2015 if vehicle_external_key == DEMO_VEHICLE_KEY else None,
        source="memory_import",
        odometer_km=166895 if vehicle_external_key == DEMO_VEHICLE_KEY else None,
    )
    if not vehicle:
        return None, candidates_payload, "No se pudo preparar el vehículo en la base."

    session_id = _id()
    now = _now()
    sessions = _table("import_sessions")
    artifacts = _table("source_artifacts")
    candidates = _table("import_candidates")

    enriched: list[dict] = []
    with db.engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO {sessions}
                (id, vehicle_id, status, source_count, candidate_count, confirmed_count, created_at, updated_at)
            VALUES (:id, :vehicle_id, 'review', :source_count, :candidate_count, 0, :created_at, :updated_at)
        """), {
            "id": session_id, "vehicle_id": vehicle["id"], "source_count": len(uploads),
            "candidate_count": len(candidates_payload), "created_at": now, "updated_at": now,
        })

        for source in uploads:
            conn.execute(text(f"""
                INSERT INTO {artifacts}
                    (id, import_session_id, vehicle_id, filename, source_kind, sha256, byte_size, metadata_json, created_at)
                VALUES (:id, :session_id, :vehicle_id, :filename, :source_kind, :sha256, :byte_size, :metadata_json, :created_at)
            """), {
                "id": _id(), "session_id": session_id, "vehicle_id": vehicle["id"],
                "filename": source.get("filename") or "source", "source_kind": source.get("kind") or "unknown",
                "sha256": source.get("sha256"), "byte_size": source.get("byte_size") or 0,
                "metadata_json": _json(source.get("metadata") or {}), "created_at": now,
            })

        for item in candidates_payload:
            candidate_id = _id()
            conn.execute(text(f"""
                INSERT INTO {candidates}
                    (id, import_session_id, vehicle_id, occurred_on, title, category, total_cost, odometer_km,
                     codes_json, excerpt, confidence, evidence_count, source_type, source_actor, source_file,
                     verification_status, created_at, updated_at)
                VALUES
                    (:id, :session_id, :vehicle_id, :occurred_on, :title, :category, :total_cost, :odometer_km,
                     :codes_json, :excerpt, :confidence, :evidence_count, :source_type, :source_actor, :source_file,
                     'ai_candidate', :created_at, :updated_at)
            """), {
                "id": candidate_id, "session_id": session_id, "vehicle_id": vehicle["id"],
                "occurred_on": item.get("date"), "title": item.get("title") or "Evento candidato",
                "category": item.get("category") or "Reparación", "total_cost": item.get("cost"),
                "odometer_km": item.get("odometer_km"), "codes_json": _json(item.get("codes") or []),
                "excerpt": item.get("excerpt") or "", "confidence": int(item.get("confidence") or 0),
                "evidence_count": int(item.get("evidence_count") or 1), "source_type": item.get("source_type"),
                "source_actor": item.get("source_actor"), "source_file": item.get("source_file"),
                "created_at": now, "updated_at": now,
            })
            enriched_item = dict(item)
            enriched_item["id"] = candidate_id
            enriched_item["verification_status"] = "ai_candidate"
            enriched.append(enriched_item)

    return session_id, enriched, None


def approve_candidates(candidate_ids: list[str]) -> tuple[int, str | None]:
    ids = [value for value in candidate_ids if value]
    if not ids:
        return 0, None
    ok, error = ensure_schema()
    if not ok:
        return 0, error

    candidates = _table("import_candidates")
    events = _table("vehicle_events")
    issues = _table("vehicle_issues")
    sessions = _table("import_sessions")
    approved = 0
    touched_sessions: set[str] = set()
    now = _now()

    with db.engine.begin() as conn:
        for candidate_id in ids:
            row = conn.execute(text(f"SELECT * FROM {candidates} WHERE id=:id"), {"id": candidate_id}).mappings().first()
            if not row or row["verification_status"] != "ai_candidate":
                continue
            existing = conn.execute(text(f"SELECT id FROM {events} WHERE candidate_id=:id"), {"id": candidate_id}).first()
            if existing:
                continue

            event_id = _id()
            conn.execute(text(f"""
                INSERT INTO {events}
                    (id, vehicle_id, candidate_id, occurred_on, title, category, total_cost, odometer_km,
                     codes_json, notes, source_type, verification_status, created_at, updated_at)
                VALUES
                    (:id, :vehicle_id, :candidate_id, :occurred_on, :title, :category, :total_cost, :odometer_km,
                     :codes_json, :notes, :source_type, 'owner_confirmed', :created_at, :updated_at)
            """), {
                "id": event_id, "vehicle_id": row["vehicle_id"], "candidate_id": candidate_id,
                "occurred_on": row["occurred_on"], "title": row["title"], "category": row["category"],
                "total_cost": row["total_cost"], "odometer_km": row["odometer_km"],
                "codes_json": row["codes_json"], "notes": row["excerpt"], "source_type": row["source_type"],
                "created_at": now, "updated_at": now,
            })
            conn.execute(text(f"UPDATE {candidates} SET verification_status='owner_confirmed', updated_at=:now WHERE id=:id"), {"now": now, "id": candidate_id})

            codes = _load_json(row["codes_json"], [])
            for code in codes:
                open_issue = conn.execute(text(f"SELECT id FROM {issues} WHERE vehicle_id=:vehicle_id AND code=:code AND status='open'"), {"vehicle_id": row["vehicle_id"], "code": code}).mappings().first()
                if open_issue:
                    conn.execute(text(f"UPDATE {issues} SET last_seen=:last_seen, source_event_id=:event_id, updated_at=:now WHERE id=:id"), {
                        "last_seen": row["occurred_on"], "event_id": event_id, "now": now, "id": open_issue["id"],
                    })
                else:
                    conn.execute(text(f"""
                        INSERT INTO {issues}
                            (id, vehicle_id, code, title, category, status, first_seen, last_seen, source_event_id, created_at, updated_at)
                        VALUES (:id, :vehicle_id, :code, :title, :category, 'open', :first_seen, :last_seen, :event_id, :created_at, :updated_at)
                    """), {
                        "id": _id(), "vehicle_id": row["vehicle_id"], "code": code,
                        "title": f"Código {code}", "category": row["category"], "first_seen": row["occurred_on"],
                        "last_seen": row["occurred_on"], "event_id": event_id, "created_at": now, "updated_at": now,
                    })

            touched_sessions.add(row["import_session_id"])
            approved += 1

        for session_id in touched_sessions:
            confirmed = conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:s AND verification_status='owner_confirmed'"), {"s": session_id}).scalar() or 0
            total = conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:s"), {"s": session_id}).scalar() or 0
            status = "confirmed" if total and confirmed >= total else "review"
            conn.execute(text(f"UPDATE {sessions} SET confirmed_count=:confirmed, status=:status, updated_at=:now WHERE id=:id"), {
                "confirmed": confirmed, "status": status, "now": now, "id": session_id,
            })

    return approved, None


def list_events(vehicle_external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    vehicles = _table("vehicles")
    events = _table("vehicle_events")
    with db.engine.begin() as conn:
        vehicle = conn.execute(text(f"SELECT id FROM {vehicles} WHERE external_key=:k"), {"k": vehicle_external_key}).mappings().first()
        if not vehicle:
            return [], None
        rows = conn.execute(text(f"""
            SELECT * FROM {events}
             WHERE vehicle_id=:v
             ORDER BY CASE WHEN occurred_on IS NULL THEN 1 ELSE 0 END, occurred_on DESC, created_at DESC
        """), {"v": vehicle["id"]}).mappings().all()
    return [
        {
            "id": row["id"], "date": row["occurred_on"], "km": row["odometer_km"],
            "title": row["title"], "category": row["category"], "cost": row["total_cost"] or 0,
            "status": "done" if row["verification_status"] in ("owner_confirmed", "evidence_verified") else "followup",
            "notes": row["notes"] or "", "codes": _load_json(row["codes_json"], []),
            "verification_status": row["verification_status"], "source_type": row["source_type"],
        }
        for row in rows
    ], None


def list_pending_candidates(vehicle_external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    vehicles = _table("vehicles")
    candidates = _table("import_candidates")
    with db.engine.begin() as conn:
        vehicle = conn.execute(text(f"SELECT id FROM {vehicles} WHERE external_key=:k"), {"k": vehicle_external_key}).mappings().first()
        if not vehicle:
            return [], None
        rows = conn.execute(text(f"""
            SELECT * FROM {candidates}
             WHERE vehicle_id=:v AND verification_status='ai_candidate'
             ORDER BY created_at DESC
             LIMIT 80
        """), {"v": vehicle["id"]}).mappings().all()
    return [
        {
            "id": row["id"], "date": row["occurred_on"], "title": row["title"], "category": row["category"],
            "cost": row["total_cost"], "odometer_km": row["odometer_km"], "codes": _load_json(row["codes_json"], []),
            "excerpt": row["excerpt"] or "", "confidence": row["confidence"], "evidence_count": row["evidence_count"],
            "source_type": row["source_type"], "source_actor": row["source_actor"], "source_file": row["source_file"],
            "verification_status": row["verification_status"],
        }
        for row in rows
    ], None


def create_onboarding(owner_name: str, make: str, model: str, year: int | None, source: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    request_id = _id()
    vehicle_key = f"vehicle-{request_id[:8]}"
    vehicle = ensure_vehicle(vehicle_key, owner_name=owner_name, make=make, model=model, model_year=year, source=source)
    if not vehicle:
        return None, "No se pudo crear el vehículo."
    token = secrets.token_urlsafe(24)
    now = _now()
    onboard = _table("onboarding_requests")
    with db.engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO {onboard}
                (id, invite_token, vehicle_id, owner_name, source, status, consented_at, created_at, updated_at)
            VALUES (:id, :token, :vehicle_id, :owner_name, :source, 'invited', NULL, :created_at, :updated_at)
        """), {
            "id": request_id, "token": token, "vehicle_id": vehicle["id"], "owner_name": owner_name,
            "source": source, "created_at": now, "updated_at": now,
        })
    return {"request_id": request_id, "invite_token": token, "vehicle_key": vehicle_key, "vehicle": vehicle}, None


def get_invitation(token: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    onboard = _table("onboarding_requests")
    vehicles = _table("vehicles")
    with db.engine.begin() as conn:
        row = conn.execute(text(f"""
            SELECT o.*, v.external_key, v.make, v.model, v.model_year
              FROM {onboard} o JOIN {vehicles} v ON v.id=o.vehicle_id
             WHERE o.invite_token=:token
        """), {"token": token}).mappings().first()
    return (dict(row) if row else None), None


def accept_invitation(token: str) -> tuple[dict | None, str | None]:
    invitation, error = get_invitation(token)
    if error or not invitation:
        return invitation, error
    onboard = _table("onboarding_requests")
    now = _now()
    with db.engine.begin() as conn:
        conn.execute(text(f"UPDATE {onboard} SET status='accepted', consented_at=:now, updated_at=:now WHERE invite_token=:token"), {"now": now, "token": token})
    invitation["status"] = "accepted"
    invitation["consented_at"] = now
    return invitation, None


def build_artifact_metadata(data: bytes, filename: str, result: dict) -> dict:
    metadata = {k: v for k, v in result.items() if k not in ("candidates", "warnings")}
    return {
        "filename": filename,
        "kind": result.get("kind") or "unknown",
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "metadata": metadata,
    }
