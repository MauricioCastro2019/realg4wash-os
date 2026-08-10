from flask import Blueprint


garage_bp = Blueprint("garage", __name__, url_prefix="/garage")

from . import routes  # noqa: E402,F401
