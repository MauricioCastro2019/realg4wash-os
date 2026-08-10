from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from flask import abort, redirect, render_template, request, url_for

from . import garage_bp
from .importer import inspect_upload
from .memory_store import (
    DEMO_VEHICLE_KEY,
    accept_invitation,
    approve_candidates,
    build_artifact_metadata,
    create_onboarding,
    ensure_demo_vehicle,
    get_invitation,
    list_events,
    list_pending_candidates,
    save_import,
)
from .vehicle_registry import get_vehicle, list_issues, restore_vehicle_identity, update_odometer


@dataclass(frozen=True)
class HealthSystem:
    name: str
    score: int
    weight: float
    status: str
    detail: str


DEMO_SYSTEMS = [
    HealthSystem("Motor", 72, 0.28, "attention", "Seguimiento a códigos P1338 / P0341"),
    HealthSystem("Enfriamiento", 68, 0.18, "attention", "Intervenciones recientes; requiere seguimiento"),
    HealthSystem("Frenos", 88, 0.18, "good", "Servicio documentado y sin alerta activa"),
    HealthSystem("Suspensión", 65, 0.14, "attention", "Ruido / desgaste reportado"),
    HealthSystem("Eléctrico", 70, 0.12, "attention", "Caja de fusibles pendiente en historial"),
    HealthSystem("Expediente", 82, 0.10, "good", "Buen historial; aún faltan algunos comprobantes"),
]


SERVICE_HISTORY = [
    {"date": "Feb 2024", "iso_date": "2024-02-01", "km": 129601, "title": "Servicio mayor + frenos traseros", "category": "Mantenimiento", "cost": 4855, "status": "done", "notes": "Primer bloque documentado del expediente. Se registran P0420 y pendientes de dirección."},
    {"date": "Sep 2024", "iso_date": "2024-09-01", "km": 134588, "title": "Suspensión y alineación", "category": "Suspensión", "cost": 7850, "status": "done", "notes": "Bases, bujes, rótulas, barra estabilizadora, terminales y alineación."},
    {"date": "Oct 2024", "iso_date": "2024-10-01", "km": 137224, "title": "Alternador y líneas de alimentación", "category": "Eléctrico", "cost": 4692, "status": "done", "notes": "Ingreso por falla de carga. Caja de fusibles queda como pendiente."},
    {"date": "Feb 2025", "iso_date": "2025-02-01", "km": 144824, "title": "Servicio, frenos delanteros y batería", "category": "Mantenimiento", "cost": 10775, "status": "done", "notes": "Aparecen como pendientes clutch y retén de cigüeñal trasero."},
    {"date": "Dic 2025", "iso_date": "2025-12-01", "km": None, "title": "Intervención mecánica documentada", "category": "Reparación", "cost": 5000, "status": "done", "notes": "Registro de conversación; expediente aún requiere comprobante detallado."},
    {"date": "Abr 2026", "iso_date": "2026-04-29", "km": 163620, "title": "Sistema de refrigeración + servicio mayor", "category": "Enfriamiento", "cost": 8162, "status": "done", "notes": "Radiador, mangueras, refrigerante, ducto de admisión y bulbo de presión de aceite."},
    {"date": "Jul 2026", "iso_date": "2026-07-29", "km": 166830, "title": "Reparación por calentamiento", "category": "Enfriamiento", "cost": 6823, "status": "followup", "notes": "Depósito, toma de termostato, resistencia de motoventilador y aceite."},
    {"date": "Ago 2026", "iso_date": "2026-08-04", "km": 166895, "title": "Potencia, encendido y fuga de aceite", "category": "Motor", "cost": 9050, "status": "followup", "notes": "Inyectores, cables, sensor de árbol de levas y trabajo en bomba/cárter."},
]


DEMO_MISSIONS = [
    {"title": "Validar reparación de fuga de aceite", "priority": "critical", "reward": "+6 Health", "detail": "Confirmar que no exista fuga residual y registrar evidencia posterior al servicio."},
    {"title": "Cerrar diagnóstico P1338 / P0341", "priority": "high", "reward": "+4 Engine", "detail": "Guardar lectura posterior a la sustitución del sensor y comparar códigos."},
    {"title": "Auditar sistema de enfriamiento", "priority": "high", "reward": "+5 Cooling", "detail": "Registrar prueba de presión, temperatura de operación y funcionamiento del ventilador."},
    {"title": "Completar expediente 2025", "priority": "medium", "reward": "+3 Garage", "detail": "Adjuntar comprobante o detalle faltante de la intervención de diciembre."},
]


DEMO_OPEN_ITEMS = [
    {"code": "P0420", "label": "Eficiencia del catalizador", "since": "2024"},
    {"code": "P1338", "label": "Seguimiento de sincronización / árbol de levas", "since": "2026"},
    {"code": "P0341", "label": "Señal / rango del sensor de árbol de levas", "since": "2026"},
]


SYSTEM_NAMES = ("Motor", "Enfriamiento", "Frenos", "Suspensión", "Eléctrico", "Expediente")


def _demo_health() -> int:
    return round(sum(system.score * system.weight for system in DEMO_SYSTEMS))


def _display_date(raw: str | None) -> str:
    if not raw:
        return "Fecha pendiente"
    try:
        year, month, day = raw.split("-")
        months = ("", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
        return f"{int(day)} {months[int(month)]} {year}"
    except Exception:
        return raw


def _dynamic_systems(events: list[dict], issues: list[dict]) -> list[HealthSystem]:
    issue_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    for issue in issues:
        category = (issue.get("category") or "Motor").lower()
        issue_counts[category] = issue_counts.get(category, 0) + 1
    for event in events:
        category = (event.get("category") or "").lower()
        event_counts[category] = event_counts.get(category, 0) + 1

    aliases = {
        "Motor": ("motor", "reparación", "mantenimiento", "transmisión"),
        "Enfriamiento": ("enfriamiento",),
        "Frenos": ("frenos",),
        "Suspensión": ("suspensión", "dirección"),
        "Eléctrico": ("eléctrico",),
    }
    systems: list[HealthSystem] = []
    for name in SYSTEM_NAMES[:-1]:
        keys = aliases.get(name, (name.lower(),))
        active_issues = sum(issue_counts.get(key, 0) for key in keys)
        interventions = sum(event_counts.get(key, 0) for key in keys)
        score = max(55, min(96, 92 - active_issues * 11 - min(interventions, 5) * 2))
        status = "good" if score >= 80 else "attention"
        if active_issues:
            detail = f"{active_issues} pendiente{'s' if active_issues != 1 else ''} abierto{'s' if active_issues != 1 else ''} · {interventions} eventos"
        elif interventions:
            detail = f"{interventions} eventos documentados · sin issue abierto"
        else:
            detail = "Sin historial suficiente; completar expediente"
        systems.append(HealthSystem(name, score, 0.18, status, detail))

    completeness = min(96, 52 + min(len(events), 12) * 4)
    systems.append(HealthSystem("Expediente", completeness, 0.10, "good" if completeness >= 80 else "attention", f"{len(events)} eventos confirmados en Vehicle Passport"))
    return systems


def _dynamic_missions(issues: list[dict], events: list[dict], vehicle_record: dict) -> list[dict]:
    missions: list[dict] = []
    for issue in issues[:3]:
        code = issue.get("code") or "pendiente"
        missions.append({"title": f"Revisar {code}", "priority": "high", "reward": "+4 Health", "detail": f"Issue abierto en {issue.get('category') or 'sistema por clasificar'}. Registrar diagnóstico o cierre con evidencia."})
    if not vehicle_record.get("odometer_km"):
        missions.append({"title": "Registrar kilometraje actual", "priority": "medium", "reward": "+2 Garage", "detail": "El odómetro mejora intervalos, costo por km y consistencia del historial."})
    if len(events) < 3:
        missions.append({"title": "Recuperar historial anterior", "priority": "medium", "reward": "+5 Garage", "detail": "Importa WhatsApp o notas del taller para que el Garage tenga contexto suficiente."})
    if not missions:
        missions.append({"title": "Mantener memoria al día", "priority": "medium", "reward": "+2 Garage", "detail": "Agrega el próximo servicio y su kilometraje para conservar continuidad."})
    return missions[:4]


def _garage_payload(vehicle_key: str) -> tuple[dict | None, str | None]:
    if vehicle_key == DEMO_VEHICLE_KEY:
        ensure_demo_vehicle(SERVICE_HISTORY)
        record = {"external_key": DEMO_VEHICLE_KEY, "owner_name": None, "make": "Volkswagen", "model": "Gol", "model_year": 2015, "odometer_km": 166895}
        events, db_error = list_events(DEMO_VEHICLE_KEY)
        if not events:
            events = list(reversed(SERVICE_HISTORY))
        else:
            for event in events:
                event["date"] = _display_date(event.get("date"))
        systems = DEMO_SYSTEMS
        missions = DEMO_MISSIONS
        open_items = DEMO_OPEN_ITEMS
        health = _demo_health()
    else:
        record, db_error = get_vehicle(vehicle_key)
        if not record:
            return None, db_error
        events, event_error = list_events(vehicle_key)
        issues, issue_error = list_issues(vehicle_key)
        db_error = db_error or event_error or issue_error
        for event in events:
            event["date"] = _display_date(event.get("date"))
        systems = _dynamic_systems(events, issues)
        missions = _dynamic_missions(issues, events, record)
        open_items = [
            {"code": item.get("code") or "ISSUE", "label": item.get("title") or "Pendiente", "since": (item.get("first_seen") or "por confirmar")[:4]}
            for item in issues[:8]
        ]
        health = round(sum(s.score * s.weight for s in systems) / max(sum(s.weight for s in systems), 0.01))

    odometers = [int(item.get("km")) for item in events if item.get("km")]
    odometer = int(record.get("odometer_km") or (max(odometers) if odometers else 0))
    start_odometer = min(odometers) if odometers else odometer
    vehicle = {
        "make": record.get("make") or "Vehículo",
        "model": record.get("model") or "Sin modelo",
        "year": record.get("model_year") or "Año pendiente",
        "alias": record.get("model") or "Mi Auto",
        "owner_name": record.get("owner_name"),
        "odometer": odometer,
        "start_odometer": start_odometer,
        "health": health,
        "level": max(1, min(99, 3 + len(events) * 3)),
        "last_update": date.today(),
    }
    documented_spend = sum(int(item.get("cost") or 0) for item in events)
    tracked_km = max(0, odometer - start_odometer)
    cost_per_km = documented_spend / tracked_km if tracked_km else 0
    category_totals: dict[str, int] = {}
    for event in events:
        category = event.get("category") or "Otros"
        category_totals[category] = category_totals.get(category, 0) + int(event.get("cost") or 0)
    max_category_total = max(category_totals.values(), default=1)
    cost_breakdown = [
        {"name": name, "amount": amount, "percent": round((amount / max_category_total) * 100)}
        for name, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "vehicle": vehicle,
        "vehicle_key": vehicle_key,
        "systems": systems,
        "history": events,
        "missions": missions,
        "open_items": open_items,
        "documented_spend": documented_spend,
        "tracked_km": tracked_km,
        "cost_per_km": cost_per_km,
        "cost_breakdown": cost_breakdown,
        "memory_online": not bool(db_error),
        "memory_error": db_error,
        "passport_score": min(98, 45 + len(events) * 5),
    }, db_error


def _render_vehicle_garage(vehicle_key: str):
    payload, error = _garage_payload(vehicle_key)
    if payload is None:
        if error:
            return render_template("garage/unavailable.html", error=error), 503
        abort(404)
    return render_template("garage/index.html", **payload)


@garage_bp.route("/")
def index():
    return _render_vehicle_garage(DEMO_VEHICLE_KEY)


@garage_bp.route("/v/<vehicle_key>")
def vehicle_garage(vehicle_key: str):
    return _render_vehicle_garage(vehicle_key)


@garage_bp.route("/onboard", methods=["GET", "POST"])
def onboard():
    profile = None
    db_error = None
    invite_url = None
    if request.method == "POST":
        year_raw = (request.form.get("year") or "").strip()
        try:
            year = int(year_raw) if year_raw else None
        except ValueError:
            year = None
        profile = {"owner": (request.form.get("owner") or "").strip(), "make": (request.form.get("make") or "").strip(), "model": (request.form.get("model") or "").strip(), "year": year, "source": (request.form.get("source") or "owner").strip()}
        created, db_error = create_onboarding(profile["owner"], profile["make"], profile["model"], profile["year"], profile["source"])
        if created:
            profile.update(created)
            invite_url = url_for("garage.accept_invite", token=created["invite_token"], _external=True)
    return render_template("garage/onboard.html", profile=profile, invite_url=invite_url, db_error=db_error)


@garage_bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token: str):
    invitation, db_error = get_invitation(token)
    accepted = False
    if invitation and request.method == "POST" and request.form.get("consent") == "yes":
        invitation, db_error = accept_invitation(token)
        accepted = bool(invitation and not db_error)
    return render_template("garage/invite.html", invitation=invitation, db_error=db_error, accepted=accepted)


@garage_bp.route("/import", methods=["GET", "POST"])
def import_lab():
    results: list[dict] = []
    candidates: list[dict] = []
    warnings: list[str] = []
    error = None
    db_error = None
    session_id = None
    vehicle_key = (request.args.get("vehicle") or request.form.get("vehicle_key") or DEMO_VEHICLE_KEY).strip()

    if vehicle_key == DEMO_VEHICLE_KEY:
        ensure_demo_vehicle(SERVICE_HISTORY)

    if request.method == "POST":
        if request.form.get("consent") != "yes":
            error = "Necesitamos confirmar que el dueño autorizó analizar estas fuentes para construir el expediente del vehículo."
        else:
            uploads = [item for item in request.files.getlist("files") if item and item.filename]
            if not uploads:
                error = "Selecciona al menos un archivo."
            elif len(uploads) > 8:
                error = "Para esta Alpha procesa máximo 8 archivos por lote."
            else:
                artifact_payloads: list[dict] = []
                original_vehicle, _ = get_vehicle(vehicle_key)
                for upload in uploads:
                    data = upload.read()
                    if not data:
                        continue
                    result = inspect_upload(data, upload.filename, upload.content_type or "")
                    results.append(result)
                    candidates.extend(result.get("candidates") or [])
                    warnings.extend(result.get("warnings") or [])
                    artifact_payloads.append(build_artifact_metadata(data, upload.filename, result))

                if candidates or results:
                    session_id, persisted_candidates, db_error = save_import(vehicle_key, artifact_payloads, candidates)
                    if original_vehicle:
                        restore_vehicle_identity(vehicle_key, original_vehicle)
                    if session_id and not db_error:
                        candidates = persisted_candidates
                        km_values = [item.get("odometer_km") for item in candidates if item.get("odometer_km")]
                        if km_values:
                            update_odometer(vehicle_key, max(km_values))
                        warnings.append("Memoria guardada: sesión, fuentes y candidatos ya persisten en la base aislada de la preview.")
                    elif db_error:
                        warnings.append("El análisis funcionó, pero la base persistente aún no está disponible. Despliega Postgres en este PR Environment.")
    else:
        pending, db_error = list_pending_candidates(vehicle_key)
        if pending:
            candidates = pending

    saved = request.args.get("saved")
    return render_template("garage/import.html", vehicle_key=vehicle_key, results=results, candidates=candidates, warnings=warnings, error=error, db_error=db_error, session_id=session_id, saved=saved)


@garage_bp.route("/candidates/confirm", methods=["POST"])
def confirm_candidates():
    vehicle_key = (request.form.get("vehicle_key") or DEMO_VEHICLE_KEY).strip()
    candidate_ids = request.form.getlist("candidate_ids")
    approved, error = approve_candidates(candidate_ids)
    if error:
        return redirect(url_for("garage.import_lab", vehicle=vehicle_key, saved="0", db_error="1"))
    return redirect(url_for("garage.import_lab", vehicle=vehicle_key, saved=str(approved)))
