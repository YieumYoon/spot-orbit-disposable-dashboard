from __future__ import annotations

from app import create_app


app = create_app()


if __name__ == "__main__":
    config = app.config["DASHBOARD_SETTINGS"]
    try:
        from waitress import serve

        serve(app, host=config.dashboard_bind_host, port=config.dashboard_port)
    except ModuleNotFoundError:
        app.run(host=config.dashboard_bind_host, port=config.dashboard_port, debug=True)
