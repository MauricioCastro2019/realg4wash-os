from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import text

from app.extensions import db


DEMO_VEHICLE_KEY = "demo-gol-2015"
SCHEMA_VERSION = "0.3.1"
_BOOTSTRAPPED = False
_LAST_DIAGNOSTIC: dict = {"stage": "not_started"}


def _table(name: str) -> str:
    # The Railway PR database is already isolated. Using a stable public prefix is
    # more portable than requiring CREATE SCHEMA privileges from the app role.
    return f"map_{name}"


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ")
    message = re.sub(r"postgres(?:ql)?://[^\s]+", "[database-url-redacted]", message, flags=re.I)
    message = re.sub(r"password=[^\s,)]+", "password=[redacted]", message, flags=re.I)
    return message[:320]


def _ddl_statements() -> list[tuple[str, str]]:
    meta = _table("meta")
    vehicles = _table("vehicles")
    sessions = _table("import_sessions")
    artifacts = _table("source_artifacts")
    candidates = _table("import_candidates")
    events = _table("vehicle_events")
    issues = _table("vehicle_issues")
    onboard = _table("onboarding_requests")

    return [
        ("meta", f"""
            CREATE TABLE IF NOT EXISTS {meta} (
                key VARCHAR(80) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            )
        """),
        ("vehicles", f"""
            CREATE TABLE IF NOT EXISTS {vehicles} (
                id VARCHAR(36) PRIMARY KEY,
                external_key VARCHAR(160) UNIQUE NOT NULL,
                owner_name VARCHAR(180),
                make VARCHAR(80) NOT NULL,
                model VARCHAR(80) NOT NULL,
                model_year INTEGER,
                source VARCHAR(80) NOT NULL DEFAULT 'owner',
                odometer_km INTEGER,
                created_at VARCHAR(40) NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            )
        """),
        ("import_sessions", f"""
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
        """),
        ("source_artifacts", f"""
            CREATE TABLE IF NOT EXISTS {artifacts} (
                id VARCHAR(36) PRIMARY KEY,
                import_session_id VARCHAR(36) NOT NULL,
                vehicle_id VARCHAR(36) NOT NULL,
                filename TEXT NOT NULL,
                source_kind VARCHAR(60),
                sha256 VARCHAR(64),
                byte_size INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at VARCHAR(40) NOT NULL
            )
        """),
        ("import_candidates", f"""
            CREATE TABLE IF NOT EXISTS {candidates} (
                id VARCHAR(36) PRIMARY KEY,
                import_session_id VARCHAR(36) NOT NULL,
                vehicle_id VARCHAR(36) NOT NULL,
                fingerprint VARCHAR(64) NOT NULL,
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
        """),
        ("vehicle_events", f"""
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
        """),
        ("vehicle_issues", f"""
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
        """),
        ("onboarding_requests", f"""
            CREATE TABLE IF NOT EXISTS {onboard} (
                id VARCHAR(36) PRIMARY KEY,
                invite_token_hash VARCHAR(64) UNIQUE NOT NULL,
                vehicle_id VARCHAR(36) NOT NULL,
                owner_name VARCHAR(180) NOT NULL,
                source VARCHAR(80) NOT NULL,
                status VARCHAR(40) NOT NULL DEFAULT 'invited',
                consent_version VARCHAR(30) NOT NULL DEFAULT 'pilot-v1',
                consented_at VARCHAR(40),
                expires_at VARCHAR(40) NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            )
        """),
        ("idx_artifact_hash", f"CREATE INDEX IF NOT EXISTS map_artifact_vehicle_hash_idx ON {artifacts}(vehicle_id, sha256)"),
        ("idx_candidate_fingerprint", f"CREATE UNIQUE INDEX IF NOT EXISTS map_candidate_vehicle_fp_uq ON {candidates}(vehicle_id, fingerprint)"),
        ("idx_event_vehicle", f"CREATE INDEX IF NOT EXISTS map_event_vehicle_date_idx ON {events}(vehicle_id, occurred_on)"),
        ("idx_issue_vehicle", f"CREATE INDEX IF NOT EXISTS map_issue_vehicle_status_idx ON {issues}(vehicle_id, status)"),
        ("idx_onboard_source", f"CREATE INDEX IF NOT EXISTS map_onboard_source_idx ON {onboard}(source, status)"),
    ]


def ensure_schema() -> tuple[bool, str | None]:
    global _BOOTSTRAPPED, _LAST_DIAGNOSTIC
    if _BOOTSTRAPPED:
        return True, None

    try:
        with db.engine.begin() as conn:
            _LAST_DIAGNOSTIC = {"stage": "connection", "dialect": db.engine.dialect.name}
            conn.execute(text("SELECT 1"))
            for stage, statement in _ddl_statements():
                _LAST_DIAGNOSTIC = {"stage": f"ddl:{stage}", "dialect": db.engine.dialect.name}
                conn.execute(text(statement))

            meta = _table("meta")
            existing = conn.execute(text(f"SELECT value FROM {meta} WHERE key='schema_version'")).scalar()
            now = _now()
            if existing is None:
                conn.execute(text(f"INSERT INTO {meta}(key,value,updated_at) VALUES ('schema_version',:v,:now)"), {"v": SCHEMA_VERSION, "now": now})
            elif existing != SCHEMA_VERSION:
                conn.execute(text(f"UPDATE {meta} SET value=:v, updated_at=:now WHERE key='schema_version'"), {"v": SCHEMA_VERSION, "now": now})

        _BOOTSTRAPPED = True
        _LAST_DIAGNOSTIC = {"stage": "ready", "dialect": db.engine.dialect.name, "schema_version": SCHEMA_VERSION}
        return True, None
    except Exception as exc:
        _LAST_DIAGNOSTIC = {
            **_LAST_DIAGNOSTIC,
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
        }
        return False, f"{type(exc).__name__}: {_safe_error(exc)}"


def memory_diagnostics() -> dict:
    ok, error = ensure_schema()
    payload = {
        "online": ok,
        "dialect": db.engine.dialect.name,
        "storage": "isolated-pr-database" if db.engine.dialect.name == "postgresql" else "local-fallback",
        "table_prefix": "map_",
        "schema_version": SCHEMA_VERSION,
        **_LAST_DIAGNOSTIC,
    }
    if not ok:
        payload["error"] = error
        return payload

    try:
        counts = {}
        with db.engine.begin() as conn:
            for key, table_name in (
                ("vehicles", "vehicles"),
                ("imports", "import_sessions"),
                ("candidates", "import_candidates"),
                ("events", "vehicle_events"),
                ("issues", "vehicle_issues"),
                ("invitations", "onboarding_requests"),
            ):
                counts[key] = int(conn.execute(text(f"SELECT COUNT(*) FROM {_table(table_name)}")).scalar() or 0)
        payload["counts"] = counts
    except Exception as exc:
        payload["online"] = False
        payload["error_type"] = type(exc).__name__
        payload["error_message"] = _safe_error(exc)
    return payload


def _vehicle_by_key(conn, external_key: str):
    return conn.execute(text(f"SELECT * FROM {_table('vehicles')} WHERE external_key=:key"), {"key": external_key}).mappings().first()


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
    now = _now()
    with db.engine.begin() as conn:
        row = _vehicle_by_key(conn, external_key)
        if row:
            conn.execute(text(f"""
                UPDATE {vehicles}
                   SET owner_name=COALESCE(:owner_name, owner_name),
                       make=COALESCE(:make, make), model=COALESCE(:model, model),
                       model_year=COALESCE(:model_year, model_year),
                       source=COALESCE(:source, source),
                       odometer_km=CASE
                           WHEN :odometer_km IS NULL THEN odometer_km
                           WHEN odometer_km IS NULL OR :odometer_km > odometer_km THEN :odometer_km
                           ELSE odometer_km END,
                       updated_at=:updated_at
                 WHERE external_key=:external_key
            """), {
                "owner_name": owner_name, "make": make, "model": model, "model_year": model_year,
                "source": source, "odometer_km": odometer_km, "updated_at": now, "external_key": external_key,
            })
            return dict(_vehicle_by_key(conn, external_key))

        vehicle_id = _id()
        conn.execute(text(f"""
            INSERT INTO {vehicles}
                (id, external_key, owner_name, make, model, model_year, source, odometer_km, created_at, updated_at)
            VALUES (:id,:external_key,:owner_name,:make,:model,:model_year,:source,:odometer_km,:created_at,:updated_at)
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
        count = int(conn.execute(text(f"SELECT COUNT(*) FROM {events} WHERE vehicle_id=:v AND source_type='reconstructed_seed'"), {"v": vehicle["id"]}).scalar() or 0)
        if count == 0:
            now = _now()
            for item in history:
                conn.execute(text(f"""
                    INSERT INTO {events}
                        (id,vehicle_id,candidate_id,occurred_on,title,category,total_cost,odometer_km,codes_json,notes,source_type,verification_status,created_at,updated_at)
                    VALUES (:id,:vehicle_id,NULL,:occurred_on,:title,:category,:total_cost,:odometer_km,'[]',:notes,'reconstructed_seed','evidence_verified',:created_at,:updated_at)
                """), {
                    "id": _id(), "vehicle_id": vehicle["id"], "occurred_on": item.get("iso_date") or item.get("date"),
                    "title": item.get("title") or "Evento", "category": item.get("category") or "Reparación",
                    "total_cost": item.get("cost"), "odometer_km": item.get("km"), "notes": item.get("notes") or "",
                    "created_at": now, "updated_at": now,
                })
    return vehicle


def _candidate_fingerprint(item: dict) -> str:
    core = {
        "date": item.get("date"), "title": (item.get("title") or "").strip().lower(),
        "category": (item.get("category") or "").strip().lower(), "cost": item.get("cost"),
        "odometer_km": item.get("odometer_km"), "codes": sorted(item.get("codes") or []),
        "excerpt": re.sub(r"\s+", " ", item.get("excerpt") or "").strip().lower()[:180],
    }
    return hashlib.sha256(_json(core).encode("utf-8")).hexdigest()


def save_import(vehicle_external_key: str, uploads: list[dict], candidates_payload: list[dict]) -> tuple[str | None, list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, candidates_payload, error

    if vehicle_external_key == DEMO_VEHICLE_KEY:
        vehicle = ensure_vehicle(DEMO_VEHICLE_KEY, owner_name=None, make="Volkswagen", model="Gol", model_year=2015, source="reconstructed", odometer_km=166895)
    else:
        with db.engine.begin() as conn:
            row = _vehicle_by_key(conn, vehicle_external_key)
            vehicle = dict(row) if row else None
    if not vehicle:
        return None, candidates_payload, "VehicleNotFound: el vehículo no existe; inicia el flujo desde Onboarding."

    session_id = _id()
    now = _now()
    sessions = _table("import_sessions")
    artifacts = _table("source_artifacts")
    candidates = _table("import_candidates")
    vehicles = _table("vehicles")
    enriched: list[dict] = []

    with db.engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO {sessions}(id,vehicle_id,status,source_count,candidate_count,confirmed_count,created_at,updated_at)
            VALUES (:id,:vehicle_id,'review',:source_count,:candidate_count,0,:created_at,:updated_at)
        """), {"id": session_id, "vehicle_id": vehicle["id"], "source_count": len(uploads), "candidate_count": len(candidates_payload), "created_at": now, "updated_at": now})

        for source in uploads:
            sha = source.get("sha256")
            duplicate = None
            if sha:
                duplicate = conn.execute(text(f"SELECT id FROM {artifacts} WHERE vehicle_id=:v AND sha256=:sha LIMIT 1"), {"v": vehicle["id"], "sha": sha}).first()
            if not duplicate:
                conn.execute(text(f"""
                    INSERT INTO {artifacts}(id,import_session_id,vehicle_id,filename,source_kind,sha256,byte_size,metadata_json,created_at)
                    VALUES (:id,:session_id,:vehicle_id,:filename,:source_kind,:sha256,:byte_size,:metadata_json,:created_at)
                """), {
                    "id": _id(), "session_id": session_id, "vehicle_id": vehicle["id"], "filename": source.get("filename") or "source",
                    "source_kind": source.get("kind") or "unknown", "sha256": sha, "byte_size": source.get("byte_size") or 0,
                    "metadata_json": _json(source.get("metadata") or {}), "created_at": now,
                })

        max_km = int(vehicle.get("odometer_km") or 0)
        for item in candidates_payload:
            fp = _candidate_fingerprint(item)
            existing = conn.execute(text(f"SELECT * FROM {candidates} WHERE vehicle_id=:v AND fingerprint=:fp"), {"v": vehicle["id"], "fp": fp}).mappings().first()
            if existing:
                enriched_item = dict(item)
                enriched_item["id"] = existing["id"]
                enriched_item["verification_status"] = existing["verification_status"]
                enriched_item["duplicate"] = True
                enriched.append(enriched_item)
                continue

            candidate_id = _id()
            conn.execute(text(f"""
                INSERT INTO {candidates}
                    (id,import_session_id,vehicle_id,fingerprint,occurred_on,title,category,total_cost,odometer_km,codes_json,excerpt,confidence,evidence_count,source_type,source_actor,source_file,verification_status,created_at,updated_at)
                VALUES (:id,:session_id,:vehicle_id,:fingerprint,:occurred_on,:title,:category,:total_cost,:odometer_km,:codes_json,:excerpt,:confidence,:evidence_count,:source_type,:source_actor,:source_file,'ai_candidate',:created_at,:updated_at)
            """), {
                "id": candidate_id, "session_id": session_id, "vehicle_id": vehicle["id"], "fingerprint": fp,
                "occurred_on": item.get("date"), "title": item.get("title") or "Evento candidato", "category": item.get("category") or "Reparación",
                "total_cost": item.get("cost"), "odometer_km": item.get("odometer_km"), "codes_json": _json(item.get("codes") or []),
                "excerpt": item.get("excerpt") or "", "confidence": int(item.get("confidence") or 0), "evidence_count": int(item.get("evidence_count") or 1),
                "source_type": item.get("source_type"), "source_actor": item.get("source_actor"), "source_file": item.get("source_file"),
                "created_at": now, "updated_at": now,
            })
            km = int(item.get("odometer_km") or 0)
            max_km = max(max_km, km)
            enriched_item = dict(item)
            enriched_item["id"] = candidate_id
            enriched_item["verification_status"] = "ai_candidate"
            enriched.append(enriched_item)

        if max_km:
            conn.execute(text(f"UPDATE {vehicles} SET odometer_km=CASE WHEN odometer_km IS NULL OR :km>odometer_km THEN :km ELSE odometer_km END, updated_at=:now WHERE id=:id"), {"km": max_km, "now": now, "id": vehicle["id"]})

        actual_count = int(conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:s"), {"s": session_id}).scalar() or 0)
        conn.execute(text(f"UPDATE {sessions} SET candidate_count=:n, updated_at=:now WHERE id=:id"), {"n": actual_count, "now": now, "id": session_id})

    return session_id, enriched, None


def approve_candidates(candidate_ids: list[str]) -> tuple[int, str | None]:
    ids = list(dict.fromkeys(value for value in candidate_ids if value))
    if not ids:
        return 0, None
    ok, error = ensure_schema()
    if not ok:
        return 0, error

    candidates = _table("import_candidates")
    events = _table("vehicle_events")
    issues = _table("vehicle_issues")
    sessions = _table("import_sessions")
    vehicles = _table("vehicles")
    approved = 0
    touched_sessions: set[str] = set()
    now = _now()

    with db.engine.begin() as conn:
        for candidate_id in ids:
            row = conn.execute(text(f"SELECT * FROM {candidates} WHERE id=:id"), {"id": candidate_id}).mappings().first()
            if not row or row["verification_status"] != "ai_candidate":
                continue
            if conn.execute(text(f"SELECT id FROM {events} WHERE candidate_id=:id"), {"id": candidate_id}).first():
                continue

            event_id = _id()
            conn.execute(text(f"""
                INSERT INTO {events}(id,vehicle_id,candidate_id,occurred_on,title,category,total_cost,odometer_km,codes_json,notes,source_type,verification_status,created_at,updated_at)
                VALUES (:id,:vehicle_id,:candidate_id,:occurred_on,:title,:category,:total_cost,:odometer_km,:codes_json,:notes,:source_type,'owner_confirmed',:created_at,:updated_at)
            """), {
                "id": event_id, "vehicle_id": row["vehicle_id"], "candidate_id": candidate_id, "occurred_on": row["occurred_on"],
                "title": row["title"], "category": row["category"], "total_cost": row["total_cost"], "odometer_km": row["odometer_km"],
                "codes_json": row["codes_json"], "notes": row["excerpt"], "source_type": row["source_type"], "created_at": now, "updated_at": now,
            })
            conn.execute(text(f"UPDATE {candidates} SET verification_status='owner_confirmed', updated_at=:now WHERE id=:id"), {"now": now, "id": candidate_id})

            if row["odometer_km"]:
                conn.execute(text(f"UPDATE {vehicles} SET odometer_km=CASE WHEN odometer_km IS NULL OR :km>odometer_km THEN :km ELSE odometer_km END, updated_at=:now WHERE id=:id"), {"km": row["odometer_km"], "now": now, "id": row["vehicle_id"]})

            for code in _load_json(row["codes_json"], []):
                open_issue = conn.execute(text(f"SELECT id FROM {issues} WHERE vehicle_id=:v AND code=:code AND status='open' LIMIT 1"), {"v": row["vehicle_id"], "code": code}).mappings().first()
                if open_issue:
                    conn.execute(text(f"UPDATE {issues} SET last_seen=:last_seen, source_event_id=:event_id, updated_at=:now WHERE id=:id"), {"last_seen": row["occurred_on"], "event_id": event_id, "now": now, "id": open_issue["id"]})
                else:
                    conn.execute(text(f"""
                        INSERT INTO {issues}(id,vehicle_id,code,title,category,status,first_seen,last_seen,source_event_id,created_at,updated_at)
                        VALUES (:id,:vehicle_id,:code,:title,:category,'open',:first_seen,:last_seen,:event_id,:created_at,:updated_at)
                    """), {"id": _id(), "vehicle_id": row["vehicle_id"], "code": code, "title": f"Código {code}", "category": row["category"], "first_seen": row["occurred_on"], "last_seen": row["occurred_on"], "event_id": event_id, "created_at": now, "updated_at": now})

            touched_sessions.add(row["import_session_id"])
            approved += 1

        for session_id in touched_sessions:
            confirmed = int(conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:s AND verification_status='owner_confirmed'"), {"s": session_id}).scalar() or 0)
            total = int(conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:s"), {"s": session_id}).scalar() or 0)
            status = "confirmed" if total and confirmed >= total else "review"
            conn.execute(text(f"UPDATE {sessions} SET confirmed_count=:confirmed,status=:status,updated_at=:now WHERE id=:id"), {"confirmed": confirmed, "status": status, "now": now, "id": session_id})

    return approved, None


def list_events(vehicle_external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    with db.engine.begin() as conn:
        vehicle = _vehicle_by_key(conn, vehicle_external_key)
        if not vehicle:
            return [], None
        rows = conn.execute(text(f"SELECT * FROM {_table('vehicle_events')} WHERE vehicle_id=:v ORDER BY CASE WHEN occurred_on IS NULL THEN 1 ELSE 0 END, occurred_on DESC, created_at DESC"), {"v": vehicle["id"]}).mappings().all()
    return [{
        "id": row["id"], "date": row["occurred_on"], "km": row["odometer_km"], "title": row["title"],
        "category": row["category"], "cost": row["total_cost"] or 0,
        "status": "done" if row["verification_status"] in ("owner_confirmed", "evidence_verified") else "followup",
        "notes": row["notes"] or "", "codes": _load_json(row["codes_json"], []),
        "verification_status": row["verification_status"], "source_type": row["source_type"],
    } for row in rows], None


def list_pending_candidates(vehicle_external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    with db.engine.begin() as conn:
        vehicle = _vehicle_by_key(conn, vehicle_external_key)
        if not vehicle:
            return [], None
        rows = conn.execute(text(f"SELECT * FROM {_table('import_candidates')} WHERE vehicle_id=:v AND verification_status='ai_candidate' ORDER BY created_at DESC LIMIT 100"), {"v": vehicle["id"]}).mappings().all()
    return [{
        "id": row["id"], "date": row["occurred_on"], "title": row["title"], "category": row["category"], "cost": row["total_cost"],
        "odometer_km": row["odometer_km"], "codes": _load_json(row["codes_json"], []), "excerpt": row["excerpt"] or "",
        "confidence": row["confidence"], "evidence_count": row["evidence_count"], "source_type": row["source_type"],
        "source_actor": row["source_actor"], "source_file": row["source_file"], "verification_status": row["verification_status"],
    } for row in rows], None


def create_onboarding(owner_name: str, make: str, model: str, year: int | None, source: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    owner_name, make, model = owner_name.strip(), make.strip(), model.strip()
    if not owner_name or not make or not model:
        return None, "ValidationError: dueño, marca y modelo son obligatorios."
    if year is not None and not 1950 <= int(year) <= _now_dt().year + 1:
        return None, "ValidationError: año fuera de rango."

    request_id = _id()
    vehicle_key = "vehicle-" + secrets.token_urlsafe(12)
    vehicle = ensure_vehicle(vehicle_key, owner_name=owner_name, make=make, model=model, model_year=year, source=source)
    if not vehicle:
        return None, "StorageError: no se pudo crear el vehículo."

    token = secrets.token_urlsafe(32)
    now_dt = _now_dt()
    now = now_dt.isoformat()
    expires = (now_dt + timedelta(days=14)).isoformat()
    with db.engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO {_table('onboarding_requests')}(id,invite_token_hash,vehicle_id,owner_name,source,status,consent_version,consented_at,expires_at,created_at,updated_at)
            VALUES (:id,:token_hash,:vehicle_id,:owner_name,:source,'invited','pilot-v1',NULL,:expires_at,:created_at,:updated_at)
        """), {"id": request_id, "token_hash": _token_hash(token), "vehicle_id": vehicle["id"], "owner_name": owner_name, "source": source, "expires_at": expires, "created_at": now, "updated_at": now})
    return {"request_id": request_id, "invite_token": token, "vehicle_key": vehicle_key, "vehicle": vehicle, "expires_at": expires}, None


def get_invitation(token: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    with db.engine.begin() as conn:
        row = conn.execute(text(f"""
            SELECT o.*,v.external_key,v.make,v.model,v.model_year
              FROM {_table('onboarding_requests')} o
              JOIN {_table('vehicles')} v ON v.id=o.vehicle_id
             WHERE o.invite_token_hash=:token_hash
        """), {"token_hash": _token_hash(token)}).mappings().first()
    if not row:
        return None, None
    result = dict(row)
    try:
        if datetime.fromisoformat(result["expires_at"]) < _now_dt() and result["status"] == "invited":
            result["status"] = "expired"
    except Exception:
        pass
    return result, None


def accept_invitation(token: str) -> tuple[dict | None, str | None]:
    invitation, error = get_invitation(token)
    if error or not invitation:
        return invitation, error
    if invitation.get("status") == "expired":
        return invitation, "InvitationExpired: la invitación venció."
    if invitation.get("status") == "accepted":
        return invitation, None
    now = _now()
    with db.engine.begin() as conn:
        conn.execute(text(f"UPDATE {_table('onboarding_requests')} SET status='accepted',consented_at=:now,updated_at=:now WHERE id=:id"), {"now": now, "id": invitation["id"]})
    invitation["status"] = "accepted"
    invitation["consented_at"] = now
    return invitation, None


def build_artifact_metadata(data: bytes, filename: str, result: dict) -> dict:
    metadata = {k: v for k, v in result.items() if k not in ("candidates", "warnings")}
    return {"filename": filename, "kind": result.get("kind") or "unknown", "sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data), "metadata": metadata}
