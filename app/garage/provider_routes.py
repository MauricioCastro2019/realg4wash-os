from __future__ import annotations

from flask import jsonify, render_template

from app.extensions import db
from . import garage_bp
from .memory_store import ensure_schema
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


@garage_bp.route("/memory-status")
def memory_status():
    ok, error = ensure_schema()
    payload = {
        "service": "mi-auto-pro-memory-engine",
        "online": ok,
        "dialect": db.engine.dialect.name,
        "storage": "isolated-pr-database" if db.engine.dialect.name == "postgresql" else "local-fallback",
        "schema": "mi_auto_pro" if db.engine.dialect.name == "postgresql" else "mi_auto_pro_*",
    }
    if error:
        payload["error_type"] = error.split(":", 1)[0]
    return jsonify(payload), (200 if ok else 503)
