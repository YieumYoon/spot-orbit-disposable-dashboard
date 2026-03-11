from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request

from .config import RANGE_OPTIONS


dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    static_folder="static",
    template_folder="templates",
)


@dashboard_bp.get("/")
def index():
    config = current_app.config["DASHBOARD_SETTINGS"]
    return render_template("index.html", config=config, range_options=RANGE_OPTIONS)


@dashboard_bp.get("/api/dashboard")
def dashboard_data():
    range_key = request.args.get("range", current_app.config["DASHBOARD_SETTINGS"].default_range)
    if range_key not in RANGE_OPTIONS:
        return jsonify({"error": f"Unsupported range '{range_key}'."}), 400

    service = current_app.extensions["dashboard_service"]
    return jsonify(service.get_dashboard(range_key))


@dashboard_bp.get("/healthz")
def health():
    service = current_app.extensions["dashboard_service"]
    return jsonify(service.health())
