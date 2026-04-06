from flask import Blueprint

agenda_bp = Blueprint("agenda", __name__, url_prefix="/agenda")

from . import routes  # noqa
