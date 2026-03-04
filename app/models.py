from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from .extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)

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

    arrived_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), default="abierta")  # abierta/en_proceso/terminada/cobrada
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