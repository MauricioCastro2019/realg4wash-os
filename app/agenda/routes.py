import re
from datetime import date, datetime, time as dtime, timedelta

from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required
from sqlalchemy.orm import joinedload

from . import agenda_bp
from ..extensions import db
from ..models import Appointment, Customer, Vehicle

PACKAGES = ["Express", "Esencial", "Pro", "Premium"]

STATUS_LABELS = {
    "pendiente":  "Pendiente",
    "confirmado": "Confirmado",
    "llegó":      "Llegó",
    "cancelado":  "Cancelado",
}


def _parse_date(date_str):
    try:
        return date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        return date.today()


def _parse_time(time_str):
    if not time_str:
        return None
    try:
        h, m = time_str.split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


def _normalize_wa(value):
    digits = re.sub(r"\D+", "", (value or "").strip())
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else None


# ─────────────────────────────────────────────
# Index: vista de día
# ─────────────────────────────────────────────

@agenda_bp.route("/")
@login_required
def index():
    selected_date = _parse_date(request.args.get("date"))
    prev_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)

    appointments = (
        Appointment.query
        .options(joinedload(Appointment.customer), joinedload(Appointment.vehicle))
        .filter_by(scheduled_date=selected_date)
        .order_by(Appointment.scheduled_time.asc().nullslast(), Appointment.id.asc())
        .all()
    )

    counts = {
        "total":      len(appointments),
        "confirmado": sum(1 for a in appointments if a.status == "confirmado"),
        "llego":      sum(1 for a in appointments if a.status == "llegó"),
        "cancelado":  sum(1 for a in appointments if a.status == "cancelado"),
    }

    return render_template(
        "agenda/index.html",
        appointments=appointments,
        selected_date=selected_date,
        today=date.today(),
        prev_date=prev_date,
        next_date=next_date,
        counts=counts,
        status_labels=STATUS_LABELS,
    )


# ─────────────────────────────────────────────
# Nueva cita
# ─────────────────────────────────────────────

@agenda_bp.route("/new", methods=["GET", "POST"])
@login_required
def appointment_new():
    if request.method == "POST":
        name    = (request.form.get("name") or "").strip()
        wa_raw  = request.form.get("whatsapp", "")
        date_str = request.form.get("scheduled_date", "")
        time_str = (request.form.get("scheduled_time") or "").strip()
        package  = request.form.get("package") or None
        vtype    = request.form.get("vtype") or "auto"
        plate    = (request.form.get("plate") or "").strip().upper() or None
        make     = (request.form.get("make") or "").strip() or None
        model_v  = (request.form.get("model") or "").strip() or None
        color    = (request.form.get("color") or "").strip() or None
        notes    = (request.form.get("notes") or "").strip() or None

        if not name:
            flash("El nombre del cliente es obligatorio.")
            return redirect(url_for("agenda.appointment_new"))

        sched_date = _parse_date(date_str)
        if not date_str:
            flash("La fecha es obligatoria.")
            return redirect(url_for("agenda.appointment_new"))

        sched_time = _parse_time(time_str)
        wa = _normalize_wa(wa_raw)

        # Buscar o crear cliente
        customer = None
        if wa:
            customer = Customer.query.filter_by(whatsapp=wa).first()
        if not customer:
            customer = Customer(name=name, whatsapp=wa or "0000000000")
            db.session.add(customer)
            db.session.flush()
        else:
            customer.name = name

        # Buscar o crear vehículo
        vehicle = None
        if plate:
            vehicle = Vehicle.query.filter_by(
                customer_id=customer.id, plate=plate
            ).first()
        if not vehicle:
            vehicle = Vehicle(
                customer_id=customer.id,
                plate=plate,
                vtype=vtype,
                make=make,
                model=model_v,
                color=color,
            )
            db.session.add(vehicle)
            db.session.flush()
        else:
            if vtype:
                vehicle.vtype = vtype

        appt = Appointment(
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            scheduled_date=sched_date,
            scheduled_time=sched_time,
            package=package,
            notes=notes,
            status="pendiente",
        )
        db.session.add(appt)
        db.session.commit()
        flash(f"Cita agendada para {sched_date.strftime('%d/%m/%Y')}.")
        return redirect(url_for("agenda.index", date=sched_date.isoformat()))

    pre_date = request.args.get("date", date.today().isoformat())
    return render_template(
        "agenda/appointment_form.html",
        packages=PACKAGES,
        pre_date=pre_date,
        appt=None,
    )


# ─────────────────────────────────────────────
# Acciones de estado
# ─────────────────────────────────────────────

@agenda_bp.route("/<int:appt_id>/action", methods=["POST"])
@login_required
def appointment_action(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    action = request.form.get("action")

    if action == "confirm" and appt.status == "pendiente":
        appt.status = "confirmado"
        flash("Cita confirmada.")
    elif action == "arrive" and appt.status in ("pendiente", "confirmado"):
        appt.status = "llegó"
        flash("Cliente marcado como llegó.")
    elif action == "cancel" and appt.status not in ("cancelado", "llegó"):
        appt.status = "cancelado"
        flash("Cita cancelada.")
    elif action == "reopen" and appt.status == "cancelado":
        appt.status = "pendiente"
        flash("Cita reabierta.")

    db.session.commit()
    return redirect(url_for("agenda.index", date=appt.scheduled_date.isoformat()))


# ─────────────────────────────────────────────
# Eliminar cita
# ─────────────────────────────────────────────

@agenda_bp.route("/<int:appt_id>/delete", methods=["POST"])
@login_required
def appointment_delete(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    appt_date = appt.scheduled_date
    db.session.delete(appt)
    db.session.commit()
    flash("Cita eliminada.")
    return redirect(url_for("agenda.index", date=appt_date.isoformat()))
