from datetime import datetime
import re

from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required

from . import main_bp
from ..extensions import db
from ..models import Customer, Vehicle, Order


# ----------------------------
# Config negocio (precios)
# ----------------------------

PACKAGES = {
    "Express":  {"auto": 100, "camioneta": 120, "moto": 80},
    "Esencial": {"auto": 150, "camioneta": 170, "moto": 120},
    "Pro":      {"auto": 200, "camioneta": 230, "moto": 160},
    "Premium":  {"auto": 300, "camioneta": 350, "moto": 250},
}

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
    # Cola operativa (listas)
    abiertas = Order.query.filter_by(status="abierta").order_by(Order.id.desc()).all()
    en_proceso = Order.query.filter_by(status="en_proceso").order_by(Order.id.desc()).all()
    terminadas = Order.query.filter_by(status="terminada").order_by(Order.id.desc()).all()
    cobradas = (
        Order.query
        .filter_by(status="cobrada")
        .order_by(Order.id.desc())
        .limit(25)
        .all()
    )

    # KPIs (conteos globales)
    total_abiertas = Order.query.filter_by(status="abierta").count()
    total_en_proceso = Order.query.filter_by(status="en_proceso").count()
    total_terminadas = Order.query.filter_by(status="terminada").count()
    total_cobradas = Order.query.filter_by(status="cobrada").count()

    # Caja (solo últimas 25 cobradas, como dice la UI)
    total_caja = sum(safe_int(o.price, 0) for o in cobradas)

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
        status_labels=STATUS_LABELS,
    )


# ----------------------------
# Crear orden (captura rápida)
# ----------------------------

@main_bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def order_new():
    if request.method == "POST":
        name = (request.form.get("name", "") or "").strip()

        whatsapp_raw = request.form.get("whatsapp", "")
        whatsapp = normalize_whatsapp_10(whatsapp_raw)

        vtype = normalize_vehicle_type(request.form.get("vtype", "auto"))
        plate = (request.form.get("plate", "") or "").strip() or None
        alias = (request.form.get("alias", "") or "").strip() or None
        make = (request.form.get("make", "") or "").strip() or None
        model = (request.form.get("model", "") or "").strip() or None
        color = (request.form.get("color", "") or "").strip() or None

        package = normalize_package(request.form.get("package", "Express"))
        pay_method = normalize_pay_method(request.form.get("pay_method", "efectivo"))

        # Validación dura
        if not name:
            flash("Nombre es obligatorio.")
            return redirect(url_for("main.order_new"))

        if not whatsapp:
            flash("WhatsApp inválido: debe tener exactamente 10 dígitos.")
            return redirect(url_for("main.order_new"))

        # Cliente: por whatsapp (10 dígitos)
        customer = Customer.query.filter_by(whatsapp=whatsapp).first()
        if not customer:
            customer = Customer(name=name, whatsapp=whatsapp)
            db.session.add(customer)
            db.session.flush()
        else:
            # Si cambia el nombre, lo actualizamos
            customer.name = name

        # Vehículo: por ahora 1 por orden (rápido operativo)
        vehicle = Vehicle(
            customer_id=customer.id,
            plate=plate,
            alias=alias,
            make=make,
            model=model,
            color=color,
            vtype=vtype,
        )
        db.session.add(vehicle)
        db.session.flush()

        # Precio correcto por tipo (auto/camioneta/moto)
        price = get_price(package, vtype)

        order = Order(
            folio=generate_daily_folio(),
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            package=package,
            price=price,
            pay_method=pay_method,
            status="abierta",
            arrived_at=now_local(),  # para que todo quede en hora local
        )
        db.session.add(order)
        db.session.commit()

        flash(f"Orden creada: {order.folio}")
        return redirect(url_for("main.order_detail", order_id=order.id))

    return render_template("main/order_new.html", packages=list(PACKAGES.keys()))


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