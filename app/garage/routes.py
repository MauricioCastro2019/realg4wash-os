from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from flask import render_template
from flask_login import login_required

from . import garage_bp


@dataclass(frozen=True)
class HealthSystem:
    name: str
    score: int
    weight: float
    status: str
    detail: str


SYSTEMS = [
    HealthSystem("Motor", 72, 0.28, "attention", "Seguimiento a códigos P1338 / P0341"),
    HealthSystem("Enfriamiento", 68, 0.18, "attention", "Intervenciones recientes; requiere seguimiento"),
    HealthSystem("Frenos", 88, 0.18, "good", "Servicio documentado y sin alerta activa"),
    HealthSystem("Suspensión", 65, 0.14, "attention", "Ruido / desgaste reportado"),
    HealthSystem("Eléctrico", 70, 0.12, "attention", "Caja de fusibles pendiente en historial"),
    HealthSystem("Expediente", 82, 0.10, "good", "Buen historial; aún faltan algunos comprobantes"),
]


SERVICE_HISTORY = [
    {
        "date": "Feb 2024",
        "km": 129601,
        "title": "Servicio mayor + frenos traseros",
        "category": "Mantenimiento",
        "cost": 4855,
        "status": "done",
        "notes": "Primer bloque documentado del expediente. Se registran P0420 y pendientes de dirección.",
    },
    {
        "date": "Sep 2024",
        "km": 134588,
        "title": "Suspensión y alineación",
        "category": "Suspensión",
        "cost": 7850,
        "status": "done",
        "notes": "Bases, bujes, rótulas, barra estabilizadora, terminales y alineación.",
    },
    {
        "date": "Oct 2024",
        "km": 137224,
        "title": "Alternador y líneas de alimentación",
        "category": "Eléctrico",
        "cost": 4692,
        "status": "done",
        "notes": "Ingreso por falla de carga. Caja de fusibles queda como pendiente.",
    },
    {
        "date": "Feb 2025",
        "km": 144824,
        "title": "Servicio, frenos delanteros y batería",
        "category": "Mantenimiento",
        "cost": 10775,
        "status": "done",
        "notes": "Aparecen como pendientes clutch y retén de cigüeñal trasero.",
    },
    {
        "date": "Dic 2025",
        "km": None,
        "title": "Intervención mecánica documentada",
        "category": "Reparación",
        "cost": 5000,
        "status": "done",
        "notes": "Registro de conversación; expediente aún requiere comprobante detallado.",
    },
    {
        "date": "Abr 2026",
        "km": 163620,
        "title": "Sistema de refrigeración + servicio mayor",
        "category": "Enfriamiento",
        "cost": 8162,
        "status": "done",
        "notes": "Radiador, mangueras, refrigerante, ducto de admisión y bulbo de presión de aceite.",
    },
    {
        "date": "Jul 2026",
        "km": 166830,
        "title": "Reparación por calentamiento",
        "category": "Enfriamiento",
        "cost": 6823,
        "status": "followup",
        "notes": "Depósito, toma de termostato, resistencia de motoventilador y aceite.",
    },
    {
        "date": "Ago 2026",
        "km": 166895,
        "title": "Potencia, encendido y fuga de aceite",
        "category": "Motor",
        "cost": 9050,
        "status": "followup",
        "notes": "Inyectores, cables, sensor de árbol de levas y trabajo en bomba/cárter.",
    },
]


MISSIONS = [
    {
        "title": "Validar reparación de fuga de aceite",
        "priority": "critical",
        "reward": "+6 Health",
        "detail": "Confirmar que no exista fuga residual y registrar evidencia posterior al servicio.",
    },
    {
        "title": "Cerrar diagnóstico P1338 / P0341",
        "priority": "high",
        "reward": "+4 Engine",
        "detail": "Guardar lectura posterior a la sustitución del sensor y comparar códigos.",
    },
    {
        "title": "Auditar sistema de enfriamiento",
        "priority": "high",
        "reward": "+5 Cooling",
        "detail": "Registrar prueba de presión, temperatura de operación y funcionamiento del ventilador.",
    },
    {
        "title": "Completar expediente 2025",
        "priority": "medium",
        "reward": "+3 Garage",
        "detail": "Adjuntar comprobante o detalle faltante de la intervención de diciembre.",
    },
]


OPEN_ITEMS = [
    {"code": "P0420", "label": "Eficiencia del catalizador", "since": "2024"},
    {"code": "P1338", "label": "Seguimiento de sincronización / árbol de levas", "since": "2026"},
    {"code": "P0341", "label": "Señal / rango del sensor de árbol de levas", "since": "2026"},
]


def _health_score() -> int:
    return round(sum(system.score * system.weight for system in SYSTEMS))


def _documented_spend() -> int:
    return sum(item["cost"] for item in SERVICE_HISTORY if item.get("cost"))


@garage_bp.route("/")
@login_required
def index():
    vehicle = {
        "make": "Volkswagen",
        "model": "Gol",
        "year": 2015,
        "alias": "Gol",
        "odometer": 166895,
        "start_odometer": 129601,
        "health": _health_score(),
        "level": 27,
        "last_update": date(2026, 8, 10),
    }

    documented_spend = _documented_spend()
    tracked_km = vehicle["odometer"] - vehicle["start_odometer"]
    cost_per_km = documented_spend / tracked_km if tracked_km else 0

    category_totals: dict[str, int] = {}
    for event in SERVICE_HISTORY:
        category = event["category"]
        category_totals[category] = category_totals.get(category, 0) + event["cost"]

    max_category_total = max(category_totals.values(), default=1)
    cost_breakdown = [
        {
            "name": name,
            "amount": amount,
            "percent": round((amount / max_category_total) * 100),
        }
        for name, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    return render_template(
        "garage/index.html",
        vehicle=vehicle,
        systems=SYSTEMS,
        history=list(reversed(SERVICE_HISTORY)),
        missions=MISSIONS,
        open_items=OPEN_ITEMS,
        documented_spend=documented_spend,
        tracked_km=tracked_km,
        cost_per_km=cost_per_km,
        cost_breakdown=cost_breakdown,
    )
