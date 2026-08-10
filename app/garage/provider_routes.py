from __future__ import annotations

import os

from flask import jsonify, render_template

from . import garage_bp
from .memory_store import memory_diagnostics
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
    diagnostics = memory_diagnostics()
    payload = {
        "service": "mi-auto-pro-memory-engine",
        **diagnostics,
        "vision_ai": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }
    return jsonify(payload), (200 if payload.get("online") else 503)
