from datetime import datetime
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from .extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    whatsapp = db.Column(db.String(30), nullable=False)

    vehicles = db.relationship("Vehicle", backref="customer", lazy=True)


class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)

    plate = db.Column(db.String(20), nullable=True)
    alias = db.Column(db.String(80), nullable=True)
    make = db.Column(db.String(80), nullable=True)
    model = db.Column(db.String(80), nullable=True)
    color = db.Column(db.String(40), nullable=True)
    vtype = db.Column(db.String(20), nullable=False, default="auto")  # auto/camioneta/moto


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(30), unique=True, nullable=False)

    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    package = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    pay_method = db.Column(db.String(20), nullable=False)

    arrived_at = db.Column(db.DateTime, default=datetime.now)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), default="abierta")  # abierta/en_proceso/terminada/cobrada
    package_type = db.Column(db.String(20), nullable=True)   # bundle / custom
    discount     = db.Column(db.Integer, default=0)           # descuento en pesos
    notes_internal = db.Column(db.Text, nullable=True)
    note_final = db.Column(db.Text, nullable=True)

    customer = db.relationship("Customer", lazy=True)
    vehicle = db.relationship("Vehicle", lazy=True)


class InspectionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)

    code = db.Column(db.String(50), nullable=False)
    value = db.Column(db.String(20), nullable=False, default="ok")
    note = db.Column(db.String(200), nullable=True)

    order = db.relationship("Order", backref=db.backref("inspection_items", lazy=True))


class ServiceCatalog(db.Model):
    """Catálogo maestro de servicios individuales."""
    __tablename__ = "service_catalog"

    code     = db.Column(db.String(30), primary_key=True)
    name     = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(20), nullable=False)   # ext / int / special
    tier     = db.Column(db.String(10), nullable=False)   # basic / mid / premium
    price_auto      = db.Column(db.Integer, nullable=False)
    price_camioneta = db.Column(db.Integer, nullable=False)
    price_moto      = db.Column(db.Integer, nullable=False, default=0)
    duration_min    = db.Column(db.Integer, default=10)
    active          = db.Column(db.Boolean, default=True)

    def price_for(self, vtype: str) -> int:
        if vtype == "camioneta":
            return self.price_camioneta
        if vtype == "moto":
            return self.price_moto
        return self.price_auto


class OrderService(db.Model):
    """Servicios individuales asociados a una orden."""
    __tablename__ = "order_service"

    id           = db.Column(db.Integer, primary_key=True)
    order_id     = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    service_code = db.Column(db.String(30), db.ForeignKey("service_catalog.code"), nullable=False)
    price_snap   = db.Column(db.Integer, nullable=False)  # precio al momento de la venta

    service = db.relationship("ServiceCatalog", lazy=True)
    order   = db.relationship("Order", backref=db.backref("order_services", lazy=True))


class Product(db.Model):
    """Inventario de productos del negocio."""
    __tablename__ = "product"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    brand      = db.Column(db.String(80), nullable=True)
    category   = db.Column(db.String(30), nullable=False, default="general")
    # limpieza / proteccion / detailing / consumible / herramienta
    unit       = db.Column(db.String(20), nullable=False, default="pieza")
    # litro / pieza / kilo / frasco / galon / rollo

    stock      = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    stock_min  = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    cost       = db.Column(db.Integer, nullable=False, default=0)  # costo por unidad en pesos

    notes      = db.Column(db.Text, nullable=True)
    active     = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def total_value(self) -> int:
        return int(Decimal(str(self.stock)) * self.cost)

    @property
    def is_out(self) -> bool:
        return float(self.stock) <= 0

    @property
    def is_low(self) -> bool:
        return not self.is_out and float(self.stock) <= float(self.stock_min)

    @property
    def stock_status(self) -> str:
        if self.is_out:  return "out"
        if self.is_low:  return "low"
        return "ok"