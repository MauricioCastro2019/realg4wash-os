from datetime import datetime, date, timedelta
import re

from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required
from sqlalchemy.orm import joinedload

from flask import jsonify

from . import main_bp
from ..extensions import db
from ..models import Customer, Vehicle, Order, ServiceCatalog, OrderService


# ----------------------------
# Config negocio (precios)
# ----------------------------

PACKAGES = {
    "Express":  {"auto": 110, "camioneta": 130, "moto": 90},
    "Esencial": {"auto": 165, "camioneta": 190, "moto": 130},
    "Pro":      {"auto": 220, "camioneta": 255, "moto": 175},
    "Premium":  {"auto": 330, "camioneta": 385, "moto": 275},
}

PACKAGE_DETAILS = {
    "Express": "Lavado exterior, aspirado y vidrios",
    "Esencial": "Express + llantas y aromatizante",
    "Pro": "Esencial + abrillantador de llantas y cera en cristales",
    "Premium": "Pro + detalle más completo",
}

# Servicios que pre-selecciona cada paquete en el configurador
PACKAGE_SERVICES = {
    "Express": [
        "EXT-BASE", "EXT-SECADO-MF", "EXT-RINES-BASE",
    ],
    "Esencial": [
        "EXT-BASE", "EXT-SHAMPOO", "EXT-SECADO-MF",
        "EXT-LLANTAS", "EXT-VINIL",
        "INT-ASPIRADO", "INT-TAPETES", "INT-AROMATIZANTE",
    ],
    "Pro": [
        "EXT-BASE", "EXT-SHAMPOO", "EXT-PRELAVADO", "EXT-SECADO-MF",
        "EXT-LLANTAS", "EXT-VINIL", "EXT-ACOND-EXT",
        "INT-ASPIRADO", "INT-TAPETES", "INT-TABLERO", "INT-CONSOLA",
        "INT-PLASTICOS", "INT-CRISTALES-INT", "INT-AROMATIZANTE",
    ],
    "Premium": [
        "EXT-BASE", "EXT-SHAMPOO", "EXT-PRELAVADO", "EXT-SECADO-MF",
        "EXT-LLANTAS", "EXT-VINIL", "EXT-ACOND-EXT", "EXT-CRISTALES-EXT",
        "INT-ASPIRADO", "INT-TAPETES", "INT-TABLERO", "INT-CONSOLA",
        "INT-PLASTICOS", "INT-ACOND-PLAST", "INT-PROTECCION-UV",
        "INT-CRISTALES-INT", "INT-AROMATIZANTE-P", "EVAL-ESTETICA",
    ],
}
BRANDS = [
    "Acura", "Audi", "BMW", "Buick", "Cadillac", "Chevrolet",
    "Chrysler", "Dodge", "Fiat", "Ford", "GMC", "Honda",
    "Hyundai", "Infiniti", "Jeep", "Kia", "Lincoln", "Mazda",
    "Mercedes-Benz", "Mini", "Mitsubishi", "Nissan", "Peugeot",
    "RAM", "Renault", "Seat", "Subaru", "Suzuki", "Tesla",
    "Toyota", "Volkswagen", "Volvo", "MG", "BYD", "Chirey",
    "Omoda", "JAC", "Cupra",
]
STATUS_LABELS = {
    "abierta": "Abierta",
    "en_proceso": "En proceso",
    "terminada": "Terminada",
    "cobrada": "Cobrada",
}

STATUS_FLOW = ("abierta", "en_proceso", "terminada", "cobrada")


# ----------------------------
# Helpers (pro)
# ----------------------------

def now_local() -> datetime:
    """Hora local (coherente con tu operación y folio)."""
    return datetime.now()


def safe_int(value, default=0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def generate_daily_folio() -> str:
    """RG4-YYYYMMDD-###"""
    today = now_local().strftime("%Y%m%d")
    prefix = f"RG4-{today}-"

    last = (
        Order.query
        .filter(Order.folio.like(prefix + "%"))
        .order_by(Order.id.desc())
        .first()
    )

    # Si algo raro se guardó, no queremos que truene
    seq = 1
    if last and last.folio:
        try:
            seq = safe_int(last.folio.split("-")[-1], 0) + 1
            if seq <= 0:
                seq = 1
        except Exception:
            seq = 1

    return f"{prefix}{seq:03d}"


def normalize_pay_method(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in ("efectivo", "transferencia", "tarjeta") else "efectivo"


def normalize_vehicle_type(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in ("auto", "camioneta", "moto") else "auto"


def normalize_whatsapp_10(value: str) -> str:
    """
    Reglas duras:
    - Solo dígitos
    - Deben quedar EXACTAMENTE 10 (México sin +52)
    - Si viene con 52 / 521 / etc, tomamos los ÚLTIMOS 10
    Ej:
    "+52 1 479-230-8662" -> "4792308662"
    "5214792308662"      -> "4792308662"
    "479 230 8662"       -> "4792308662"
    """
    digits = re.sub(r"\D+", "", (value or "").strip())
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else ""


def normalize_package(value: str) -> str:
    v = (value or "").strip()
    return v if v in PACKAGES else "Express"


def get_price(package: str, vtype: str) -> int:
    pkg = normalize_package(package)
    vt = normalize_vehicle_type(vtype)
    return int(PACKAGES.get(pkg, PACKAGES["Express"]).get(vt, 100))


# ----------------------------
# Dashboard (cola operativa)
# ----------------------------

@main_bp.route("/")
@login_required
def dashboard():
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    # Período seleccionado (hoy / semana / mes)
    period = request.args.get("period", "today")
    if period == "week":
        period_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
        period_label = "Esta semana"
    elif period == "month":
        period_start = datetime.combine(today.replace(day=1), datetime.min.time())
        period_label = "Este mes"
    else:
        period = "today"
        period_start = today_start
        period_label = "Hoy"

    eager = [joinedload(Order.customer), joinedload(Order.vehicle)]

    # Cola operativa: SIEMPRE solo hoy (kanban operativo)
    abiertas = (
        Order.query.options(*eager)
        .filter_by(status="abierta")
        .filter(Order.arrived_at >= today_start)
        .order_by(Order.id.desc()).all()
    )
    en_proceso = (
        Order.query.options(*eager)
        .filter_by(status="en_proceso")
        .filter(Order.arrived_at >= today_start)
        .order_by(Order.id.desc()).all()
    )
    terminadas = (
        Order.query.options(*eager)
        .filter_by(status="terminada")
        .filter(Order.arrived_at >= today_start)
        .order_by(Order.id.desc()).all()
    )

    # Cobradas del período seleccionado
    cobradas = (
        Order.query.options(*eager)
        .filter_by(status="cobrada")
        .filter(Order.arrived_at >= period_start)
        .order_by(Order.id.desc()).all()
    )

    # KPIs operativos (siempre hoy)
    total_abiertas   = len(abiertas)
    total_en_proceso = len(en_proceso)
    total_terminadas = len(terminadas)

    # KPIs del período
    total_cobradas = len(cobradas)
    total_caja     = sum(safe_int(o.price, 0) for o in cobradas)
    ticket_prom    = (total_caja // total_cobradas) if total_cobradas else 0

    # Top 5 servicios del período (de OrderService)
    from collections import Counter
    svc_counter: Counter = Counter()
    for o in cobradas:
        for os in o.order_services:
            if os.price_snap > 0:
                svc_counter[os.service.name] += 1
    top_services = svc_counter.most_common(5)

    # Desglose por método de pago del período
    pay_totals: dict = {}
    for o in cobradas:
        pm = o.pay_method
        pay_totals[pm] = pay_totals.get(pm, 0) + safe_int(o.price, 0)

    return render_template(
        "main/dashboard.html",
        abiertas=abiertas,
        en_proceso=en_proceso,
        terminadas=terminadas,
        cobradas=cobradas,
        total_abiertas=total_abiertas,
        total_en_proceso=total_en_proceso,
        total_terminadas=total_terminadas,
        total_cobradas=total_cobradas,
        total_caja=total_caja,
        ticket_prom=ticket_prom,
        top_services=top_services,
        pay_totals=pay_totals,
        period=period,
        period_label=period_label,
        status_labels=STATUS_LABELS,
    )


# ----------------------------
# Crear orden (captura rápida)
# ----------------------------

@main_bp.route("/api/price-preview", methods=["POST"])
@login_required
def price_preview():
    """Calcula el total en tiempo real desde el configurador (AJAX)."""
    data = request.get_json(silent=True) or {}
    vtype = normalize_vehicle_type(data.get("vtype", "auto"))
    codes = [str(c) for c in (data.get("services") or []) if c]

    services = (
        ServiceCatalog.query
        .filter(ServiceCatalog.code.in_(codes), ServiceCatalog.active == True)
        .all()
    ) if codes else []

    items = [{"code": s.code, "name": s.name, "price": s.price_for(vtype)} for s in services]
    total = sum(i["price"] for i in items)
    return jsonify({"items": items, "total": total})


@main_bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def order_new():
    if request.method == "POST":
        name        = (request.form.get("name", "") or "").strip()
        whatsapp    = normalize_whatsapp_10(request.form.get("whatsapp", ""))
        vtype       = normalize_vehicle_type(request.form.get("vtype", "auto"))
        plate       = (request.form.get("plate", "") or "").strip() or None
        alias       = (request.form.get("alias", "") or "").strip() or None
        make        = (request.form.get("make", "") or "").strip() or None
        model       = (request.form.get("model", "") or "").strip() or None
        color       = (request.form.get("color", "") or "").strip() or None
        pay_method  = normalize_pay_method(request.form.get("pay_method", "efectivo"))
        service_codes = request.form.getlist("services")  # nuevo configurador

        # Validación
        if not name:
            flash("Nombre es obligatorio.")
            return redirect(url_for("main.order_new"))
        if not whatsapp:
            flash("WhatsApp inválido: debe tener exactamente 10 dígitos.")
            return redirect(url_for("main.order_new"))
        if make and make not in BRANDS:
            make = None

        # ── Cliente ────────────────────────────────────────────────────
        customer = Customer.query.filter_by(whatsapp=whatsapp).first()
        if not customer:
            customer = Customer(name=name, whatsapp=whatsapp)
            db.session.add(customer)
            db.session.flush()
        else:
            customer.name = name

        # ── Vehículo (dedup por placa) ─────────────────────────────────
        vehicle = None
        if plate:
            vehicle = Vehicle.query.filter_by(customer_id=customer.id, plate=plate).first()
        if vehicle:
            vehicle.alias = alias or vehicle.alias
            vehicle.make  = make  or vehicle.make
            vehicle.model = model or vehicle.model
            vehicle.color = color or vehicle.color
            vehicle.vtype = vtype
        else:
            vehicle = Vehicle(customer_id=customer.id, plate=plate,
                              alias=alias, make=make, model=model,
                              color=color, vtype=vtype)
            db.session.add(vehicle)
        db.session.flush()

        # ── Precio y servicios ──────────────────────────────────────────
        if service_codes:
            # Configurador: calcula desde catálogo
            catalog_items = (
                ServiceCatalog.query
                .filter(ServiceCatalog.code.in_(service_codes),
                        ServiceCatalog.active == True)
                .all()
            )
            price        = sum(s.price_for(vtype) for s in catalog_items)
            discount     = safe_int(request.form.get("discount", 0))
            price        = max(0, price - discount)
            package      = request.form.get("package") or "custom"
            package_type = "custom" if package == "custom" else "bundle"
        else:
            # Fallback: paquete clásico
            package      = normalize_package(request.form.get("package", "Express"))
            price        = get_price(package, vtype)
            catalog_items = []
            discount     = 0
            package_type = "bundle"

        # ── Orden ───────────────────────────────────────────────────────
        order = Order(
            folio=generate_daily_folio(),
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            package=package,
            package_type=package_type,
            price=price,
            discount=discount,
            pay_method=pay_method,
            status="abierta",
            arrived_at=now_local(),
        )
        db.session.add(order)
        db.session.flush()

        # ── OrderService (detalle de servicios) ─────────────────────────
        for svc in catalog_items:
            db.session.add(OrderService(
                order_id=order.id,
                service_code=svc.code,
                price_snap=svc.price_for(vtype),
            ))

        db.session.commit()
        flash(f"Orden creada: {order.folio}")
        return redirect(url_for("main.order_detail", order_id=order.id))

    # ── GET: cargar catálogo para el configurador ──────────────────────
    all_svcs = (
        ServiceCatalog.query
        .filter_by(active=True)
        .order_by(ServiceCatalog.tier, ServiceCatalog.name)
        .all()
    )
    ext_svcs     = [s for s in all_svcs if s.category == "ext"]
    int_svcs     = [s for s in all_svcs if s.category == "int"]
    special_svcs = [s for s in all_svcs if s.category == "special"]

    return render_template(
        "main/order_new.html",
        packages=list(PACKAGES.keys()),
        package_services=PACKAGE_SERVICES,
        package_details=PACKAGE_DETAILS,
        brands=BRANDS,
        ext_svcs=ext_svcs,
        int_svcs=int_svcs,
        special_svcs=special_svcs,
    )
# ----------------------------
# Detalle de orden
# ----------------------------

@main_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template(
        "main/order_detail.html",
        order=order,
        status_labels=STATUS_LABELS,
        status_flow=STATUS_FLOW,
    )


# ----------------------------
# Acciones operativas (OS real)
# ----------------------------

@main_bp.route("/orders/<int:order_id>/start", methods=["POST"])
@login_required
def order_start(order_id):
    order = Order.query.get_or_404(order_id)

    if order.status != "abierta":
        flash("Esta orden ya no está en estado 'abierta'.")
        return redirect(url_for("main.order_detail", order_id=order.id))

    order.status = "en_proceso"
    order.started_at = order.started_at or now_local()
    db.session.commit()

    flash("Orden iniciada.")
    return redirect(url_for("main.order_detail", order_id=order.id))


@main_bp.route("/orders/<int:order_id>/finish", methods=["POST"])
@login_required
def order_finish(order_id):
    order = Order.query.get_or_404(order_id)

    if order.status not in ("abierta", "en_proceso"):
        flash("Solo puedes terminar órdenes 'abierta' o 'en proceso'.")
        return redirect(url_for("main.order_detail", order_id=order.id))

    # Si brincan directo a terminar, ponemos started_at también
    order.started_at = order.started_at or now_local()
    order.status = "terminada"
    order.finished_at = order.finished_at or now_local()
    db.session.commit()

    flash("Orden terminada.")
    return redirect(url_for("main.order_detail", order_id=order.id))


@main_bp.route("/orders/<int:order_id>/pay", methods=["POST"])
@login_required
def order_pay(order_id):
    order = Order.query.get_or_404(order_id)

    if order.status != "terminada":
        flash("Solo puedes cobrar órdenes 'terminadas'.")
        return redirect(url_for("main.order_detail", order_id=order.id))

    order.status = "cobrada"
    db.session.commit()

    flash("Orden cobrada.")
    return redirect(url_for("main.order_detail", order_id=order.id))


@main_bp.route("/orders/<int:order_id>/reopen", methods=["POST"])
@login_required
def order_reopen(order_id):
    """Botón de emergencia: regresarla a abierta (por si se equivocan)."""
    order = Order.query.get_or_404(order_id)

    if order.status == "cobrada":
        flash("No se puede reabrir una orden ya cobrada.")
        return redirect(url_for("main.order_detail", order_id=order.id))

    order.status = "abierta"
    # Si la reabres, ya no está terminada
    order.finished_at = None
    db.session.commit()

    flash("Orden reabierta.")
    return redirect(url_for("main.order_detail", order_id=order.id))