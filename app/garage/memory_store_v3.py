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
SCHEMA_VERSION = "0.3.2"
_BOOTSTRAPPED = False
_LAST_DIAGNOSTIC: dict = {"stage": "not_started"}


def _table(name: str) -> str:
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
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_error(exc: Exception) -> str:
    msg = str(exc).replace("\n", " ")
    msg = re.sub(r"postgres(?:ql)?://[^\s]+", "[database-url-redacted]", msg, flags=re.I)
    return msg[:320]


def _ddl() -> list[tuple[str, str]]:
    t = _table
    return [
        ("meta", f"CREATE TABLE IF NOT EXISTS {t('meta')} (key VARCHAR(80) PRIMARY KEY, value TEXT NOT NULL, updated_at VARCHAR(40) NOT NULL)"),
        ("vehicles", f"""CREATE TABLE IF NOT EXISTS {t('vehicles')} (
            id VARCHAR(36) PRIMARY KEY, external_key VARCHAR(160) UNIQUE NOT NULL,
            owner_name VARCHAR(180), make VARCHAR(80) NOT NULL, model VARCHAR(80) NOT NULL,
            model_year INTEGER, source VARCHAR(80) NOT NULL DEFAULT 'owner', odometer_km INTEGER,
            created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"""),
        ("imports", f"""CREATE TABLE IF NOT EXISTS {t('import_sessions')} (
            id VARCHAR(36) PRIMARY KEY, vehicle_id VARCHAR(36) NOT NULL, status VARCHAR(40) NOT NULL DEFAULT 'review',
            source_count INTEGER NOT NULL DEFAULT 0, candidate_count INTEGER NOT NULL DEFAULT 0,
            confirmed_count INTEGER NOT NULL DEFAULT 0, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"""),
        ("artifacts", f"""CREATE TABLE IF NOT EXISTS {t('source_artifacts')} (
            id VARCHAR(36) PRIMARY KEY, import_session_id VARCHAR(36) NOT NULL, vehicle_id VARCHAR(36) NOT NULL,
            filename TEXT NOT NULL, source_kind VARCHAR(60), sha256 VARCHAR(64), byte_size INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '', created_at VARCHAR(40) NOT NULL)"""),
        ("candidates", f"""CREATE TABLE IF NOT EXISTS {t('import_candidates')} (
            id VARCHAR(36) PRIMARY KEY, import_session_id VARCHAR(36) NOT NULL, vehicle_id VARCHAR(36) NOT NULL,
            fingerprint VARCHAR(64) NOT NULL, occurred_on VARCHAR(20), title TEXT NOT NULL, category VARCHAR(80) NOT NULL,
            total_cost INTEGER, odometer_km INTEGER, codes_json TEXT NOT NULL DEFAULT '[]', excerpt TEXT,
            confidence INTEGER NOT NULL DEFAULT 0, evidence_count INTEGER NOT NULL DEFAULT 1,
            source_type VARCHAR(80), source_actor VARCHAR(80), source_file TEXT,
            verification_status VARCHAR(40) NOT NULL DEFAULT 'ai_candidate',
            created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"""),
        ("events", f"""CREATE TABLE IF NOT EXISTS {t('vehicle_events')} (
            id VARCHAR(36) PRIMARY KEY, vehicle_id VARCHAR(36) NOT NULL, candidate_id VARCHAR(36) UNIQUE,
            occurred_on VARCHAR(20), title TEXT NOT NULL, category VARCHAR(80) NOT NULL, total_cost INTEGER,
            odometer_km INTEGER, codes_json TEXT NOT NULL DEFAULT '[]', notes TEXT, source_type VARCHAR(80),
            verification_status VARCHAR(40) NOT NULL DEFAULT 'owner_confirmed',
            created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"""),
        ("issues", f"""CREATE TABLE IF NOT EXISTS {t('vehicle_issues')} (
            id VARCHAR(36) PRIMARY KEY, vehicle_id VARCHAR(36) NOT NULL, code VARCHAR(40), title TEXT NOT NULL,
            category VARCHAR(80), status VARCHAR(30) NOT NULL DEFAULT 'open', first_seen VARCHAR(20), last_seen VARCHAR(20),
            source_event_id VARCHAR(36), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"""),
        ("onboarding", f"""CREATE TABLE IF NOT EXISTS {t('onboarding_requests')} (
            id VARCHAR(36) PRIMARY KEY, invite_token_hash VARCHAR(64) UNIQUE NOT NULL, vehicle_id VARCHAR(36) NOT NULL,
            owner_name VARCHAR(180) NOT NULL, source VARCHAR(80) NOT NULL, status VARCHAR(40) NOT NULL DEFAULT 'invited',
            consent_version VARCHAR(30) NOT NULL DEFAULT 'pilot-v1', consented_at VARCHAR(40), expires_at VARCHAR(40) NOT NULL,
            created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"""),
        ("idx_artifacts", f"CREATE INDEX IF NOT EXISTS map_artifact_vehicle_hash_idx ON {t('source_artifacts')}(vehicle_id, sha256)"),
        ("idx_candidates", f"CREATE UNIQUE INDEX IF NOT EXISTS map_candidate_vehicle_fp_uq ON {t('import_candidates')}(vehicle_id, fingerprint)"),
        ("idx_events", f"CREATE INDEX IF NOT EXISTS map_event_vehicle_date_idx ON {t('vehicle_events')}(vehicle_id, occurred_on)"),
        ("idx_issues", f"CREATE INDEX IF NOT EXISTS map_issue_vehicle_status_idx ON {t('vehicle_issues')}(vehicle_id, status)"),
        ("idx_onboarding", f"CREATE INDEX IF NOT EXISTS map_onboard_source_idx ON {t('onboarding_requests')}(source, status)"),
    ]


def ensure_schema() -> tuple[bool, str | None]:
    global _BOOTSTRAPPED, _LAST_DIAGNOSTIC
    if _BOOTSTRAPPED:
        return True, None
    try:
        with db.engine.begin() as conn:
            _LAST_DIAGNOSTIC = {"stage": "connection", "dialect": db.engine.dialect.name}
            conn.execute(text("SELECT 1"))
            for stage, sql in _ddl():
                _LAST_DIAGNOSTIC = {"stage": f"ddl:{stage}", "dialect": db.engine.dialect.name}
                conn.execute(text(sql))
            meta = _table("meta")
            now = _now()
            current = conn.execute(text(f"SELECT value FROM {meta} WHERE key='schema_version'")).scalar()
            if current is None:
                conn.execute(text(f"INSERT INTO {meta}(key,value,updated_at) VALUES ('schema_version',:v,:now)"), {"v": SCHEMA_VERSION, "now": now})
            elif current != SCHEMA_VERSION:
                conn.execute(text(f"UPDATE {meta} SET value=:v,updated_at=:now WHERE key='schema_version'"), {"v": SCHEMA_VERSION, "now": now})
        _BOOTSTRAPPED = True
        _LAST_DIAGNOSTIC = {"stage": "ready", "dialect": db.engine.dialect.name, "schema_version": SCHEMA_VERSION}
        return True, None
    except Exception as exc:
        _LAST_DIAGNOSTIC = {**_LAST_DIAGNOSTIC, "error_type": type(exc).__name__, "error_message": _safe_error(exc)}
        return False, f"{type(exc).__name__}: {_safe_error(exc)}"


def memory_diagnostics() -> dict:
    ok, error = ensure_schema()
    data = {
        "online": ok,
        "dialect": db.engine.dialect.name,
        "storage": "isolated-pr-database" if db.engine.dialect.name == "postgresql" else "local-fallback",
        "table_prefix": "map_",
        "schema_version": SCHEMA_VERSION,
        **_LAST_DIAGNOSTIC,
    }
    if error:
        data["error"] = error
        return data
    try:
        with db.engine.begin() as conn:
            data["counts"] = {
                "vehicles": int(conn.execute(text(f"SELECT COUNT(*) FROM {_table('vehicles')}")).scalar() or 0),
                "imports": int(conn.execute(text(f"SELECT COUNT(*) FROM {_table('import_sessions')}")).scalar() or 0),
                "candidates": int(conn.execute(text(f"SELECT COUNT(*) FROM {_table('import_candidates')}")).scalar() or 0),
                "events": int(conn.execute(text(f"SELECT COUNT(*) FROM {_table('vehicle_events')}")).scalar() or 0),
                "issues": int(conn.execute(text(f"SELECT COUNT(*) FROM {_table('vehicle_issues')}")).scalar() or 0),
                "invitations": int(conn.execute(text(f"SELECT COUNT(*) FROM {_table('onboarding_requests')}")).scalar() or 0),
            }
    except Exception as exc:
        data.update(online=False, error_type=type(exc).__name__, error_message=_safe_error(exc))
    return data


def _vehicle_row(conn, external_key: str):
    return conn.execute(text(f"SELECT * FROM {_table('vehicles')} WHERE external_key=:k"), {"k": external_key}).mappings().first()


def ensure_vehicle(external_key: str, *, owner_name: str | None, make: str, model: str,
                   model_year: int | None = None, source: str = "owner", odometer_km: int | None = None) -> dict | None:
    ok, _ = ensure_schema()
    if not ok:
        return None
    now = _now()
    vehicles = _table("vehicles")
    with db.engine.begin() as conn:
        row = _vehicle_row(conn, external_key)
        if row:
            conn.execute(text(f"""UPDATE {vehicles} SET
                owner_name=COALESCE(:owner_name,owner_name), make=COALESCE(:make,make), model=COALESCE(:model,model),
                model_year=COALESCE(:year,model_year), source=COALESCE(:source,source),
                odometer_km=CASE WHEN :km IS NULL THEN odometer_km WHEN odometer_km IS NULL OR :km>odometer_km THEN :km ELSE odometer_km END,
                updated_at=:now WHERE external_key=:key"""),
                {"owner_name": owner_name, "make": make, "model": model, "year": model_year, "source": source, "km": odometer_km, "now": now, "key": external_key})
            return dict(_vehicle_row(conn, external_key))
        vehicle_id = _id()
        conn.execute(text(f"""INSERT INTO {vehicles}
            (id,external_key,owner_name,make,model,model_year,source,odometer_km,created_at,updated_at)
            VALUES (:id,:key,:owner,:make,:model,:year,:source,:km,:now,:now)"""),
            {"id": vehicle_id, "key": external_key, "owner": owner_name, "make": make, "model": model, "year": model_year, "source": source, "km": odometer_km, "now": now})
        return dict(conn.execute(text(f"SELECT * FROM {vehicles} WHERE id=:id"), {"id": vehicle_id}).mappings().first())


def ensure_demo_vehicle(history: Iterable[dict]) -> dict | None:
    vehicle = ensure_vehicle(DEMO_VEHICLE_KEY, owner_name=None, make="Volkswagen", model="Gol", model_year=2015, source="reconstructed", odometer_km=166895)
    if not vehicle:
        return None
    events = _table("vehicle_events")
    with db.engine.begin() as conn:
        count = int(conn.execute(text(f"SELECT COUNT(*) FROM {events} WHERE vehicle_id=:v AND source_type='reconstructed_seed'"), {"v": vehicle["id"]}).scalar() or 0)
        if count == 0:
            now = _now()
            for item in history:
                conn.execute(text(f"""INSERT INTO {events}
                    (id,vehicle_id,candidate_id,occurred_on,title,category,total_cost,odometer_km,codes_json,notes,source_type,verification_status,created_at,updated_at)
                    VALUES (:id,:v,NULL,:date,:title,:category,:cost,:km,'[]',:notes,'reconstructed_seed','evidence_verified',:now,:now)"""),
                    {"id": _id(), "v": vehicle["id"], "date": item.get("iso_date") or item.get("date"), "title": item.get("title") or "Evento", "category": item.get("category") or "Reparación", "cost": item.get("cost"), "km": item.get("km"), "notes": item.get("notes") or "", "now": now})
    return vehicle


def _fingerprint(item: dict) -> str:
    core = [item.get("date"), (item.get("title") or "").lower(), (item.get("category") or "").lower(), item.get("cost"), item.get("odometer_km"), sorted(item.get("codes") or []), re.sub(r"\s+", " ", item.get("excerpt") or "").lower()[:180]]
    return hashlib.sha256(_json(core).encode()).hexdigest()


def save_import(vehicle_external_key: str, uploads: list[dict], candidates_payload: list[dict]) -> tuple[str | None, list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, candidates_payload, error
    if vehicle_external_key == DEMO_VEHICLE_KEY:
        vehicle = ensure_vehicle(DEMO_VEHICLE_KEY, owner_name=None, make="Volkswagen", model="Gol", model_year=2015, source="reconstructed", odometer_km=166895)
    else:
        with db.engine.begin() as conn:
            row = _vehicle_row(conn, vehicle_external_key)
            vehicle = dict(row) if row else None
    if not vehicle:
        return None, candidates_payload, "VehicleNotFound: inicia desde Onboarding."

    sessions, artifacts, candidates, vehicles = map(_table, ["import_sessions", "source_artifacts", "import_candidates", "vehicles"])
    session_id, now, enriched = _id(), _now(), []
    with db.engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {sessions}(id,vehicle_id,status,source_count,candidate_count,confirmed_count,created_at,updated_at) VALUES (:id,:v,'review',:s,0,0,:now,:now)"), {"id": session_id, "v": vehicle["id"], "s": len(uploads), "now": now})
        for source in uploads:
            sha = source.get("sha256")
            exists = sha and conn.execute(text(f"SELECT id FROM {artifacts} WHERE vehicle_id=:v AND sha256=:sha LIMIT 1"), {"v": vehicle["id"], "sha": sha}).first()
            if not exists:
                conn.execute(text(f"""INSERT INTO {artifacts}(id,import_session_id,vehicle_id,filename,source_kind,sha256,byte_size,metadata_json,created_at)
                    VALUES (:id,:sid,:v,:filename,:kind,:sha,:bytes,:meta,:now)"""),
                    {"id": _id(), "sid": session_id, "v": vehicle["id"], "filename": source.get("filename") or "source", "kind": source.get("kind") or "unknown", "sha": sha, "bytes": source.get("byte_size") or 0, "meta": _json(source.get("metadata") or {}), "now": now})
        max_km = int(vehicle.get("odometer_km") or 0)
        for item in candidates_payload:
            fp = _fingerprint(item)
            existing = conn.execute(text(f"SELECT * FROM {candidates} WHERE vehicle_id=:v AND fingerprint=:fp"), {"v": vehicle["id"], "fp": fp}).mappings().first()
            if existing:
                copy = dict(item); copy.update(id=existing["id"], verification_status=existing["verification_status"], duplicate=True); enriched.append(copy); continue
            cid = _id()
            conn.execute(text(f"""INSERT INTO {candidates}
                (id,import_session_id,vehicle_id,fingerprint,occurred_on,title,category,total_cost,odometer_km,codes_json,excerpt,confidence,evidence_count,source_type,source_actor,source_file,verification_status,created_at,updated_at)
                VALUES (:id,:sid,:v,:fp,:date,:title,:cat,:cost,:km,:codes,:excerpt,:conf,:evidence,:stype,:actor,:sfile,'ai_candidate',:now,:now)"""),
                {"id": cid, "sid": session_id, "v": vehicle["id"], "fp": fp, "date": item.get("date"), "title": item.get("title") or "Evento candidato", "cat": item.get("category") or "Reparación", "cost": item.get("cost"), "km": item.get("odometer_km"), "codes": _json(item.get("codes") or []), "excerpt": item.get("excerpt") or "", "conf": int(item.get("confidence") or 0), "evidence": int(item.get("evidence_count") or 1), "stype": item.get("source_type"), "actor": item.get("source_actor"), "sfile": item.get("source_file"), "now": now})
            km = int(item.get("odometer_km") or 0); max_km = max(max_km, km)
            copy = dict(item); copy.update(id=cid, verification_status="ai_candidate"); enriched.append(copy)
        if max_km:
            conn.execute(text(f"UPDATE {vehicles} SET odometer_km=CASE WHEN odometer_km IS NULL OR :km>odometer_km THEN :km ELSE odometer_km END,updated_at=:now WHERE id=:id"), {"km": max_km, "now": now, "id": vehicle["id"]})
        count = int(conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:sid"), {"sid": session_id}).scalar() or 0)
        conn.execute(text(f"UPDATE {sessions} SET candidate_count=:n,updated_at=:now WHERE id=:sid"), {"n": count, "now": now, "sid": session_id})
    return session_id, enriched, None


def approve_candidates(candidate_ids: list[str]) -> tuple[int, str | None]:
    ids = list(dict.fromkeys(x for x in candidate_ids if x))
    if not ids:
        return 0, None
    ok, error = ensure_schema()
    if not ok:
        return 0, error
    candidates, events, issues, sessions, vehicles = map(_table, ["import_candidates", "vehicle_events", "vehicle_issues", "import_sessions", "vehicles"])
    approved, touched, now = 0, set(), _now()
    with db.engine.begin() as conn:
        for cid in ids:
            row = conn.execute(text(f"SELECT * FROM {candidates} WHERE id=:id"), {"id": cid}).mappings().first()
            if not row or row["verification_status"] != "ai_candidate" or conn.execute(text(f"SELECT id FROM {events} WHERE candidate_id=:id"), {"id": cid}).first():
                continue
            eid = _id()
            conn.execute(text(f"""INSERT INTO {events}(id,vehicle_id,candidate_id,occurred_on,title,category,total_cost,odometer_km,codes_json,notes,source_type,verification_status,created_at,updated_at)
                VALUES (:id,:v,:cid,:date,:title,:cat,:cost,:km,:codes,:notes,:stype,'owner_confirmed',:now,:now)"""),
                {"id": eid, "v": row["vehicle_id"], "cid": cid, "date": row["occurred_on"], "title": row["title"], "cat": row["category"], "cost": row["total_cost"], "km": row["odometer_km"], "codes": row["codes_json"], "notes": row["excerpt"], "stype": row["source_type"], "now": now})
            conn.execute(text(f"UPDATE {candidates} SET verification_status='owner_confirmed',updated_at=:now WHERE id=:id"), {"now": now, "id": cid})
            if row["odometer_km"]:
                conn.execute(text(f"UPDATE {vehicles} SET odometer_km=CASE WHEN odometer_km IS NULL OR :km>odometer_km THEN :km ELSE odometer_km END,updated_at=:now WHERE id=:id"), {"km": row["odometer_km"], "now": now, "id": row["vehicle_id"]})
            for code in _load_json(row["codes_json"], []):
                issue = conn.execute(text(f"SELECT id FROM {issues} WHERE vehicle_id=:v AND code=:code AND status='open' LIMIT 1"), {"v": row["vehicle_id"], "code": code}).mappings().first()
                if issue:
                    conn.execute(text(f"UPDATE {issues} SET last_seen=:date,source_event_id=:eid,updated_at=:now WHERE id=:id"), {"date": row["occurred_on"], "eid": eid, "now": now, "id": issue["id"]})
                else:
                    conn.execute(text(f"""INSERT INTO {issues}(id,vehicle_id,code,title,category,status,first_seen,last_seen,source_event_id,created_at,updated_at)
                        VALUES (:id,:v,:code,:title,:cat,'open',:date,:date,:eid,:now,:now)"""), {"id": _id(), "v": row["vehicle_id"], "code": code, "title": f"Código {code}", "cat": row["category"], "date": row["occurred_on"], "eid": eid, "now": now})
            touched.add(row["import_session_id"]); approved += 1
        for sid in touched:
            confirmed = int(conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:sid AND verification_status='owner_confirmed'"), {"sid": sid}).scalar() or 0)
            total = int(conn.execute(text(f"SELECT COUNT(*) FROM {candidates} WHERE import_session_id=:sid"), {"sid": sid}).scalar() or 0)
            conn.execute(text(f"UPDATE {sessions} SET confirmed_count=:c,status=:status,updated_at=:now WHERE id=:sid"), {"c": confirmed, "status": "confirmed" if total and confirmed >= total else "review", "now": now, "sid": sid})
    return approved, None


def list_events(vehicle_external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    with db.engine.begin() as conn:
        vehicle = _vehicle_row(conn, vehicle_external_key)
        if not vehicle:
            return [], None
        rows = conn.execute(text(f"SELECT * FROM {_table('vehicle_events')} WHERE vehicle_id=:v ORDER BY CASE WHEN occurred_on IS NULL THEN 1 ELSE 0 END,occurred_on DESC,created_at DESC"), {"v": vehicle["id"]}).mappings().all()
    return [{"id": r["id"], "date": r["occurred_on"], "km": r["odometer_km"], "title": r["title"], "category": r["category"], "cost": r["total_cost"] or 0, "status": "done" if r["verification_status"] in ("owner_confirmed", "evidence_verified") else "followup", "notes": r["notes"] or "", "codes": _load_json(r["codes_json"], []), "verification_status": r["verification_status"], "source_type": r["source_type"]} for r in rows], None


def list_pending_candidates(vehicle_external_key: str) -> tuple[list[dict], str | None]:
    ok, error = ensure_schema()
    if not ok:
        return [], error
    with db.engine.begin() as conn:
        vehicle = _vehicle_row(conn, vehicle_external_key)
        if not vehicle:
            return [], None
        rows = conn.execute(text(f"SELECT * FROM {_table('import_candidates')} WHERE vehicle_id=:v AND verification_status='ai_candidate' ORDER BY created_at DESC LIMIT 100"), {"v": vehicle["id"]}).mappings().all()
    return [{"id": r["id"], "date": r["occurred_on"], "title": r["title"], "category": r["category"], "cost": r["total_cost"], "odometer_km": r["odometer_km"], "codes": _load_json(r["codes_json"], []), "excerpt": r["excerpt"] or "", "confidence": r["confidence"], "evidence_count": r["evidence_count"], "source_type": r["source_type"], "source_actor": r["source_actor"], "source_file": r["source_file"], "verification_status": r["verification_status"]} for r in rows], None


def create_onboarding(owner_name: str, make: str, model: str, year: int | None, source: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    owner_name, make, model = owner_name.strip(), make.strip(), model.strip()
    if not owner_name or not make or not model:
        return None, "ValidationError: dueño, marca y modelo son obligatorios."
    if year is not None and not 1950 <= int(year) <= _now_dt().year + 1:
        return None, "ValidationError: año fuera de rango."
    request_id, vehicle_key = _id(), "vehicle-" + secrets.token_urlsafe(12)
    vehicle = ensure_vehicle(vehicle_key, owner_name=owner_name, make=make, model=model, model_year=year, source=source)
    if not vehicle:
        return None, "StorageError: no se pudo crear el vehículo."
    token, now_dt = secrets.token_urlsafe(32), _now_dt()
    now, expires = now_dt.isoformat(), (now_dt + timedelta(days=14)).isoformat()
    with db.engine.begin() as conn:
        conn.execute(text(f"""INSERT INTO {_table('onboarding_requests')}
            (id,invite_token_hash,vehicle_id,owner_name,source,status,consent_version,consented_at,expires_at,created_at,updated_at)
            VALUES (:id,:hash,:v,:owner,:source,'invited','pilot-v1',NULL,:expires,:now,:now)"""),
            {"id": request_id, "hash": _hash_token(token), "v": vehicle["id"], "owner": owner_name, "source": source, "expires": expires, "now": now})
    return {"request_id": request_id, "invite_token": token, "vehicle_key": vehicle_key, "vehicle": vehicle, "expires_at": expires}, None


def get_invitation(token: str) -> tuple[dict | None, str | None]:
    ok, error = ensure_schema()
    if not ok:
        return None, error
    with db.engine.begin() as conn:
        row = conn.execute(text(f"""SELECT o.*,v.external_key,v.make,v.model,v.model_year FROM {_table('onboarding_requests')} o
            JOIN {_table('vehicles')} v ON v.id=o.vehicle_id WHERE o.invite_token_hash=:hash"""), {"hash": _hash_token(token)}).mappings().first()
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
    invitation["status"], invitation["consented_at"] = "accepted", now
    return invitation, None


def build_artifact_metadata(data: bytes, filename: str, result: dict) -> dict:
    metadata = {k: v for k, v in result.items() if k not in ("candidates", "warnings")}
    return {"filename": filename, "kind": result.get("kind") or "unknown", "sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data), "metadata": metadata}
