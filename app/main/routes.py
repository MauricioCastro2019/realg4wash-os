from datetime import datetime
from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required

from . import main_bp
from ..extensions import db
from ..models import Customer, Vehicle, Order

PACKAGES = {
    "Express": {"auto": 100, "camioneta": 120, "moto": 100},
    "Esencial": {"auto": 150, "camioneta": 150, "moto": 150},
    "Pro": {"auto": 200, "camioneta": 200, "moto": 200},
    "Premium": {"auto": 300, "camioneta": 300, "moto": 300},
}

def generate_daily_folio():
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"RG4-{today}-"
    last = Order.query.filter(Order.folio.like(prefix + "%")).order_by(Order.id.desc()).first()
    seq = 1 if not last else int(last.folio.split("-")[-1]) + 1
    return f"{prefix}{seq:03d}"

@main_bp.route("/")
@login_required
def dashboard():
    orders = Order.query.order_by(Order.id.desc()).limit(25).all()
    return render_template("main/dashboard.html", orders=orders)

@main_bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def order_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        whatsapp = request.form.get("whatsapp", "").strip()
        vtype = request.form.get("vtype", "auto")
        plate = request.form.get("plate", "").strip() or None
        alias = request.form.get("alias", "").strip() or None
        make = request.form.get("make", "").strip() or None
        model = request.form.get("model", "").strip() or None
        color = request.form.get("color", "").strip() or None
        package = request.form.get("package", "Express")
        pay_method = request.form.get("pay_method", "efectivo")

        if not name or not whatsapp:
            flash("Nombre y WhatsApp son obligatorios.")
            return redirect(url_for("main.order_new"))

        customer = Customer.query.filter_by(whatsapp=whatsapp).first()
        if not customer:
            customer = Customer(name=name, whatsapp=whatsapp)
            db.session.add(customer)
            db.session.flush()
        else:
            customer.name = name

        vehicle = Vehicle(
            customer_id=customer.id,
            plate=plate,
            alias=alias,
            make=make,
            model=model,
            color=color,
            vtype=vtype
        )
        db.session.add(vehicle)
        db.session.flush()

        price = PACKAGES.get(package, PACKAGES["Express"]).get(vtype, 100)

        order = Order(
            folio=generate_daily_folio(),
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            package=package,
            price=price,
            pay_method=pay_method
        )
        db.session.add(order)
        db.session.commit()

        flash(f"Orden creada: {order.folio}")
        return redirect(url_for("main.order_detail", order_id=order.id))

    return render_template("main/order_new.html", packages=list(PACKAGES.keys()))

@main_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("main/order_detail.html", order=order)