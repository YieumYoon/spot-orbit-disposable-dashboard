from __future__ import annotations

from flask import Flask

from .config import load_config
from .orbit_client import DashboardService
from .routes import dashboard_bp


def create_app() -> Flask:
    app = Flask(__name__)

    config = load_config()
    app.config["DASHBOARD_SETTINGS"] = config
    app.extensions["dashboard_service"] = DashboardService(config)
    app.register_blueprint(dashboard_bp)

    return app
