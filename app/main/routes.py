from datetime import datetime, date, timedelta
from functools import wraps
import re
import os
import uuid

from flask import render_template, redirect, url_for, request, flash, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from flask import jsonify

from . import main_bp
from ..extensions import db
from ..models import Customer, Vehicle, Order, ServiceCatalog, OrderService, OrderPhoto, User


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
def admin_required(f):
    """Decorator: requiere is_admin=True. Combinar con @login_required."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("Necesitas permisos de administrador.")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated_function


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
        .with_for_update()
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

    # KPIs del período (siempre sobre todas las cobradas, sin filtro de búsqueda)
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

    # Búsqueda en tabla de cobradas
    q = (request.args.get("q") or "").strip()
    if q:
        ql = q.lower()
        cobradas_display = [
            o for o in cobradas
            if ql in o.folio.lower()
            or ql in o.customer.name.lower()
            or (o.vehicle and o.vehicle.plate and ql in o.vehicle.plate.lower())
        ]
    else:
        cobradas_display = cobradas

    return render_template(
        "main/dashboard.html",
        abiertas=abiertas,
        en_proceso=en_proceso,
        terminadas=terminadas,
        cobradas=cobradas,
        cobradas_display=cobradas_display,
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
        q=q,
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
    return jsonify({"services": items, "total": total})


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


# ----------------------------
# Menú público (sin login)
# ----------------------------

MENU_PACKAGES = [
    {
        "key":   "express",
        "name":  "Express",
        "emoji": "⚡",
        "price_auto": 80,
        "price_camioneta": 100,
        "tag":   None,
        "desc":  "Lavado exterior rápido y funcional.",
        "services": [
            "Lavado exterior",
            "Enjuague a presión",
            "Secado con microfibra",
        ],
    },
    {
        "key":   "esencial",
        "name":  "Esencial",
        "emoji": "✨",
        "price_auto": 130,
        "price_camioneta": 160,
        "tag":   "Más popular",
        "desc":  "Exterior + interior básico. El equilibrio perfecto.",
        "services": [
            "Lavado exterior + shampoo",
            "Secado profesional",
            "Aspirado interior",
            "Limpieza de tapetes",
            "Rines + vinil de llantas",
            "Aromatizante",
        ],
    },
    {
        "key":   "pro",
        "name":  "Pro",
        "emoji": "💎",
        "price_auto": 180,
        "price_camioneta": 220,
        "tag":   "Recomendado",
        "desc":  "Todo Esencial + protección y brillo duradero.",
        "services": [
            "Todo lo Esencial +",
            "Prelavado con espuma activa",
            "Acondicionador de plásticos ext.",
            "Limpieza de plásticos int.",
            "Cristales antiempañante",
            "Tablero + consola + puertas",
        ],
    },
    {
        "key":   "premium",
        "name":  "Premium",
        "emoji": "👑",
        "price_auto": 230,
        "price_camioneta": 280,
        "tag":   "Detailing pro",
        "desc":  "El servicio más completo. Nivel showroom.",
        "services": [
            "Todo lo Pro +",
            "Cristales exteriores antigragotas",
            "Acondicionador UV interiores",
            "Protección de llantas duradera",
            "Aromatizante a tu elección",
            "Control de calidad incluido",
        ],
    },
]

MENU_EXTRAS = [
    ("🔦", "Pulido de faros",         "$130"),
    ("💧", "Acrílico en faros",       "$90"),
    ("🌊", "Vapor interior completo", "$275"),
    ("🦠", "Ozono (elimina olores)",  "$130"),
    ("🔧", "Lavado de motor",         "$165"),
    ("🪑", "Vapor en asientos",       "$175"),
    ("🧴", "Limpieza asientos piel",  "$145"),
    ("✨", "Detallado showroom",      "$550"),
]


@main_bp.route("/menu")
def public_menu():
    """Página pública de servicios — sin login."""
    return render_template(
        "main/menu.html",
        packages=MENU_PACKAGES,
        extras=MENU_EXTRAS,
        wa_number="5214792308662",
    )


# ----------------------------
# Fotos de órdenes
# ----------------------------

ALLOWED_PHOTO_EXT = {"jpg", "jpeg", "png", "webp", "heic"}


@main_bp.route("/orders/<int:order_id>/photos", methods=["POST"])
@login_required
def order_photo_upload(order_id):
    order = Order.query.get_or_404(order_id)
    files = request.files.getlist("photos")

    if not files or all(f.filename == "" for f in files):
        flash("No se seleccionó ninguna foto.")
        return redirect(url_for("main.order_detail", order_id=order_id) + "#fotos")

    saved = 0
    for f in files:
        if not f or f.filename == "":
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "jpg"
        if ext not in ALLOWED_PHOTO_EXT:
            continue

        filename = f"{uuid.uuid4().hex}.{ext}"
        upload_dir = os.path.join(
            current_app.root_path, "static", "uploads", "orders", str(order_id)
        )
        os.makedirs(upload_dir, exist_ok=True)
        f.save(os.path.join(upload_dir, filename))

        db.session.add(OrderPhoto(order_id=order_id, filename=filename))
        saved += 1

    if saved:
        db.session.commit()
        flash(f"{saved} foto{'s' if saved > 1 else ''} agregada{'s' if saved > 1 else ''}.")
    else:
        flash("Formato no soportado. Usa JPG, PNG o WEBP.")

    return redirect(url_for("main.order_detail", order_id=order_id) + "#fotos")


@main_bp.route("/orders/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def order_photo_delete(photo_id):
    photo = OrderPhoto.query.get_or_404(photo_id)
    order_id = photo.order_id

    file_path = os.path.join(
        current_app.root_path, "static", "uploads", "orders",
        str(order_id), photo.filename
    )
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(photo)
    db.session.commit()
    return redirect(url_for("main.order_detail", order_id=order_id) + "#fotos")


# ----------------------------
# Notas de orden
# ----------------------------

@main_bp.route("/orders/<int:order_id>/notes", methods=["POST"])
@login_required
def order_notes(order_id):
    order = Order.query.get_or_404(order_id)
    order.notes_internal = (request.form.get("notes_internal") or "").strip() or None
    order.note_final = (request.form.get("note_final") or "").strip() or None
    db.session.commit()
    flash("Notas guardadas.")
    return redirect(url_for("main.order_detail", order_id=order.id) + "#notas")


# ----------------------------
# Estadísticas
# ----------------------------

@main_bp.route("/estadisticas")
@login_required
def estadisticas():
    from collections import Counter

    all_cobradas = (
        Order.query
        .filter_by(status="cobrada")
        .options(
            joinedload(Order.customer),
            joinedload(Order.vehicle),
            joinedload(Order.order_services),
        )
        .order_by(Order.arrived_at.desc())
        .all()
    )

    total_ordenes  = len(all_cobradas)
    total_ingresos = sum(safe_int(o.price) for o in all_cobradas)
    ticket_promedio = (total_ingresos // total_ordenes) if total_ordenes else 0

    # Datos por día (últimos 30 días)
    today = date.today()
    daily_data: dict = {}
    for i in range(30):
        d = today - timedelta(days=i)
        daily_data[d.isoformat()] = {"date": d, "total": 0, "count": 0}

    for o in all_cobradas:
        if o.arrived_at:
            key = o.arrived_at.date().isoformat()
            if key in daily_data:
                daily_data[key]["total"] += safe_int(o.price)
                daily_data[key]["count"] += 1

    daily_list = sorted(daily_data.values(), key=lambda x: x["date"])

    # Top 10 servicios
    svc_counter: Counter = Counter()
    for o in all_cobradas:
        for os_item in o.order_services:
            if os_item.price_snap > 0:
                svc_counter[os_item.service.name] += 1
    top_services = svc_counter.most_common(10)

    # Por método de pago
    pay_totals: dict = {}
    for o in all_cobradas:
        pm = o.pay_method
        pay_totals[pm] = pay_totals.get(pm, 0) + safe_int(o.price)

    # Por tipo de vehículo
    vtype_counts: dict = {}
    for o in all_cobradas:
        if o.vehicle:
            vt = o.vehicle.vtype
            vtype_counts[vt] = vtype_counts.get(vt, 0) + 1

    return render_template(
        "main/estadisticas.html",
        total_ordenes=total_ordenes,
        total_ingresos=total_ingresos,
        ticket_promedio=ticket_promedio,
        daily_list=daily_list,
        top_services=top_services,
        pay_totals=pay_totals,
        vtype_counts=vtype_counts,
    )


# ----------------------------
# Gestión de clientes
# ----------------------------

@main_bp.route("/clientes")
@login_required
def clientes():
    q = (request.args.get("q") or "").strip()
    query = Customer.query
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            db.or_(Customer.name.ilike(pattern), Customer.whatsapp.ilike(pattern))
        )
    customers = query.order_by(Customer.name).all()
    return render_template("main/clientes.html", customers=customers, q=q)


@main_bp.route("/clientes/<int:customer_id>")
@login_required
def cliente_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    orders = (
        Order.query
        .filter_by(customer_id=customer_id)
        .order_by(Order.arrived_at.desc())
        .all()
    )
    return render_template("main/cliente_detail.html", customer=customer, orders=orders)


@main_bp.route("/clientes/<int:customer_id>/edit", methods=["POST"])
@login_required
def cliente_edit(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    name = (request.form.get("name") or "").strip()
    whatsapp = normalize_whatsapp_10(request.form.get("whatsapp", ""))
    if not name:
        flash("El nombre es obligatorio.")
        return redirect(url_for("main.cliente_detail", customer_id=customer_id))
    customer.name = name
    if whatsapp:
        customer.whatsapp = whatsapp
    db.session.commit()
    flash("Cliente actualizado.")
    return redirect(url_for("main.cliente_detail", customer_id=customer_id))


# ----------------------------
# Admin — Usuarios
# ----------------------------

@main_bp.route("/admin/usuarios")
@login_required
@admin_required
def admin_usuarios():
    users = User.query.order_by(User.username).all()
    return render_template("main/usuarios.html", users=users)


@main_bp.route("/admin/usuarios/new", methods=["POST"])
@login_required
@admin_required
def admin_usuario_new():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    is_admin = bool(request.form.get("is_admin"))

    if not username or len(password) < 4:
        flash("Usuario y contraseña (mín. 4 caracteres) son requeridos.")
        return redirect(url_for("main.admin_usuarios"))

    if User.query.filter_by(username=username).first():
        flash(f"Ya existe un usuario con el nombre '{username}'.")
        return redirect(url_for("main.admin_usuarios"))

    user = User(username=username, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"Usuario '{username}' creado.")
    return redirect(url_for("main.admin_usuarios"))


@main_bp.route("/admin/usuarios/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def admin_usuario_toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("No puedes modificar tu propio rol de administrador.")
        return redirect(url_for("main.admin_usuarios"))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{'Admin activado' if user.is_admin else 'Admin removido'} para '{user.username}'.")
    return redirect(url_for("main.admin_usuarios"))


@main_bp.route("/admin/usuarios/<int:user_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def admin_usuario_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("new_password") or ""
    if len(new_password) < 4:
        flash("Contraseña muy corta (mín. 4 caracteres).")
        return redirect(url_for("main.admin_usuarios"))
    user.set_password(new_password)
    db.session.commit()
    flash(f"Contraseña actualizada para '{user.username}'.")
    return redirect(url_for("main.admin_usuarios"))


# ----------------------------
# Admin — Catálogo de servicios
# ----------------------------

@main_bp.route("/admin/servicios")
@login_required
@admin_required
def admin_servicios():
    services = (
        ServiceCatalog.query
        .order_by(ServiceCatalog.category, ServiceCatalog.tier, ServiceCatalog.name)
        .all()
    )
    return render_template("main/servicios_admin.html", services=services)


@main_bp.route("/admin/servicios/<code>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_servicio_toggle(code):
    svc = ServiceCatalog.query.get_or_404(code)
    svc.active = not svc.active
    db.session.commit()
    flash(f"Servicio '{svc.name}' {'activado' if svc.active else 'desactivado'}.")
    return redirect(url_for("main.admin_servicios"))


# ----------------------------
# API — Leer placa con IA
# ----------------------------

@main_bp.route("/api/read-plate", methods=["POST"])
@login_required
def api_read_plate():
    """Recibe una foto, extrae la placa con Claude Vision y busca el cliente en DB."""
    import base64

    if "photo" not in request.files:
        return jsonify({"error": "No se recibió imagen"}), 400

    photo = request.files["photo"]
    if not photo or not photo.filename:
        return jsonify({"error": "Archivo vacío"}), 400

    image_bytes = photo.read()
    mime = photo.content_type or "image/jpeg"
    # Normalizar MIME — Claude acepta jpeg, png, gif, webp
    if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        mime = "image/jpeg"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY no configurada en el servidor"}), 503

    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=api_key)

        image_b64 = base64.standard_b64encode(image_bytes).decode()

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Lee la placa vehicular en esta foto. "
                            "Responde ÚNICAMENTE con el número de placa "
                            "(ej: ABC-1234 o ABC-123 o 12A-BC3). "
                            "Sin explicaciones, sin puntos, solo la placa. "
                            "Si no hay placa visible o no puedes leerla claramente, "
                            "responde exactamente: NO_PLATE"
                        ),
                    },
                ],
            }],
        )

        raw = msg.content[0].text.strip().upper()

        if not raw or raw == "NO_PLATE" or "NO_PLATE" in raw:
            return jsonify({
                "found": False,
                "plate": None,
                "message": "No se detectó placa. Intenta con mejor ángulo o iluminación.",
            })

        # Limpiar: solo letras, números y guión
        plate_clean = re.sub(r"[^A-Z0-9\-]", "", raw).strip("-")

        if len(plate_clean) < 4:
            return jsonify({
                "found": False,
                "plate": None,
                "message": f"Resultado dudoso: '{raw}'. Intenta de nuevo.",
            })

        # Buscar en DB ignorando guiones y mayúsculas/minúsculas
        from sqlalchemy import func
        normalized = plate_clean.replace("-", "")
        vehicle = Vehicle.query.filter(
            func.upper(func.replace(Vehicle.plate, "-", "")) == normalized
        ).first()

        if vehicle:
            c = vehicle.customer
            return jsonify({
                "found": True,
                "plate": vehicle.plate,
                "plate_detected": plate_clean,
                "customer": {
                    "name": c.name,
                    "whatsapp": c.whatsapp or "",
                },
                "vehicle": {
                    "plate": vehicle.plate,
                    "make":  vehicle.make  or "",
                    "model": vehicle.model or "",
                    "vtype": vehicle.vtype or "auto",
                    "color": vehicle.color or "",
                    "alias": vehicle.alias or "",
                },
            })
        else:
            return jsonify({
                "found": False,
                "plate": plate_clean,
                "message": f"Placa {plate_clean} no encontrada — cliente nuevo.",
            })

    except Exception as exc:
        current_app.logger.error(f"api_read_plate error: {exc}")
        return jsonify({"error": "Error procesando la imagen"}), 500