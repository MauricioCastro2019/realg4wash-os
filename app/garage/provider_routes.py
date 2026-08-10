from __future__ import annotations

import os

from flask import jsonify, render_template

from . import garage_bp
from .memory_store import memory_diagnostics
from .provider_store import provider_fleet


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@garage_bp.route("/provider")
def provider_console():
    fleet, stats, db_error = provider_fleet("centerfix")
    return render_template(
        "garage/provider.html",
        fleet=fleet,
        stats=stats,
        db_error=db_error,
        show_pii=_truthy(os.environ.get("CENTERFIX_PILOT_SHOW_PII")),
    )


@garage_bp.route("/memory-status")
def memory_status():
    diagnostics = memory_diagnostics()
    payload = {
        "service": "mi-auto-pro-memory-engine",
        **diagnostics,
        "vision_ai": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "provider_pii_visible": _truthy(os.environ.get("CENTERFIX_PILOT_SHOW_PII")),
    }
    return jsonify(payload), (200 if payload.get("online") else 503)
