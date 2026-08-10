from __future__ import annotations

from flask import render_template

from . import garage_bp
from .provider_store import provider_fleet


@garage_bp.route("/provider")
def provider_console():
    fleet, stats, db_error = provider_fleet("centerfix")
    return render_template(
        "garage/provider.html",
        fleet=fleet,
        stats=stats,
        db_error=db_error,
    )
