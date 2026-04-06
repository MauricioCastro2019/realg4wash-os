from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required

from . import inventory_bp
from ..extensions import db
from ..models import Product

CATEGORIES = {
    "limpieza":    "🧴 Limpieza",
    "proteccion":  "🛡️ Protección",
    "detailing":   "✨ Detailing",
    "consumible":  "📦 Consumible",
    "herramienta": "🔧 Herramienta",
    "general":     "📋 General",
}

UNITS = ["pieza", "litro", "frasco", "kilo", "galon", "rollo", "par", "metro"]


def _safe_decimal(value, default="0"):
    try:
        v = float(str(value).replace(",", "."))
        if v < 0:
            return default
        return str(round(v, 2))
    except Exception:
        return default


# ── Lista principal ──────────────────────────────────────────────────
@inventory_bp.route("/")
@login_required
def index():
    products = (
        Product.query
        .filter_by(active=True)
        .order_by(Product.category, Product.name)
        .all()
    )

    total_value   = sum(p.total_value for p in products)
    out_count     = sum(1 for p in products if p.is_out)
    low_count     = sum(1 for p in products if p.is_low)

    # Agrupar por categoría
    from collections import defaultdict
    by_cat: dict = defaultdict(list)
    for p in products:
        by_cat[p.category].append(p)

    return render_template(
        "inventory/index.html",
        by_cat=dict(by_cat),
        categories=CATEGORIES,
        total_value=total_value,
        out_count=out_count,
        low_count=low_count,
        product_count=len(products),
    )


# ── Crear producto ───────────────────────────────────────────────────
@inventory_bp.route("/new", methods=["GET", "POST"])
@login_required
def product_new():
    if request.method == "POST":
        name     = (request.form.get("name") or "").strip()
        brand    = (request.form.get("brand") or "").strip() or None
        category = request.form.get("category") or "general"
        unit     = request.form.get("unit") or "pieza"
        stock    = _safe_decimal(request.form.get("stock", "0"))
        stock_min= _safe_decimal(request.form.get("stock_min", "1"), "1")
        cost     = max(0, int(request.form.get("cost", 0) or 0))
        notes    = (request.form.get("notes") or "").strip() or None

        if not name:
            flash("El nombre del producto es obligatorio.")
            return redirect(url_for("inventory.product_new"))

        if category not in CATEGORIES:
            category = "general"
        if unit not in UNITS:
            unit = "pieza"

        product = Product(
            name=name, brand=brand, category=category, unit=unit,
            stock=stock, stock_min=stock_min, cost=cost, notes=notes,
        )
        db.session.add(product)
        db.session.commit()
        flash(f"Producto '{name}' creado.")
        return redirect(url_for("inventory.index"))

    return render_template(
        "inventory/product_form.html",
        product=None,
        categories=CATEGORIES,
        units=UNITS,
        action_url=url_for("inventory.product_new"),
        title="Nuevo producto",
    )


# ── Editar producto ──────────────────────────────────────────────────
@inventory_bp.route("/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)

    if request.method == "POST":
        product.name     = (request.form.get("name") or "").strip() or product.name
        product.brand    = (request.form.get("brand") or "").strip() or None
        product.category = request.form.get("category") or product.category
        product.unit     = request.form.get("unit") or product.unit
        product.stock    = _safe_decimal(request.form.get("stock", product.stock))
        product.stock_min= _safe_decimal(request.form.get("stock_min", product.stock_min), "1")
        product.cost     = max(0, int(request.form.get("cost", product.cost) or 0))
        product.notes    = (request.form.get("notes") or "").strip() or None

        if product.category not in CATEGORIES:
            product.category = "general"
        if product.unit not in UNITS:
            product.unit = "pieza"

        db.session.commit()
        flash(f"Producto '{product.name}' actualizado.")
        return redirect(url_for("inventory.index"))

    return render_template(
        "inventory/product_form.html",
        product=product,
        categories=CATEGORIES,
        units=UNITS,
        action_url=url_for("inventory.product_edit", product_id=product.id),
        title="Editar producto",
    )


# ── Ajustar stock ────────────────────────────────────────────────────
@inventory_bp.route("/<int:product_id>/adjust", methods=["POST"])
@login_required
def product_adjust(product_id):
    product = Product.query.get_or_404(product_id)

    op  = request.form.get("op", "add")   # add / remove
    try:
        qty = abs(float(request.form.get("qty", 0) or 0))
    except ValueError:
        qty = 0

    if qty <= 0:
        flash("Cantidad inválida.")
        return redirect(url_for("inventory.index"))

    current = float(product.stock)
    if op == "add":
        product.stock = round(current + qty, 2)
        flash(f"✅ +{qty} {product.unit} de {product.name}. Stock: {product.stock}")
    else:
        if qty > current:
            flash(f"⚠️ No hay suficiente stock de {product.name} (actual: {current}).")
            return redirect(url_for("inventory.index"))
        product.stock = round(current - qty, 2)
        flash(f"📤 -{qty} {product.unit} de {product.name}. Stock: {product.stock}")

    db.session.commit()
    return redirect(url_for("inventory.index"))


# ── Archivar (soft delete) ───────────────────────────────────────────
@inventory_bp.route("/<int:product_id>/archive", methods=["POST"])
@login_required
def product_archive(product_id):
    product = Product.query.get_or_404(product_id)
    product.active = False
    db.session.commit()
    flash(f"Producto '{product.name}' archivado.")
    return redirect(url_for("inventory.index"))
