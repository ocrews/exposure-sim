"""exposure-sim: an interview-prep game for exposure management implementation engineers."""
from __future__ import annotations

import os
import secrets

from flask import Flask, session

from exposure_sim.progress import ProgressStore, SessionStore
from exposure_sim.scenarios import ScenarioRepository


def create_app(config: dict | None = None, store: ProgressStore | None = None,
               repo: ScenarioRepository | None = None) -> Flask:
    app = Flask(__name__)
    configured_secret = os.environ.get("EXPOSURE_SIM_SECRET")
    app.config.update(
        SECRET_KEY=configured_secret or secrets.token_hex(32),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
    )
    if config:
        app.config.update(config)
    if not configured_secret and not (config and "SECRET_KEY" in config):
        # A random key per process breaks sessions across gunicorn workers and restarts.
        app.logger.warning("EXPOSURE_SIM_SECRET is not set; using a random key. "
                           "Progress will reset on restart and may not persist across workers.")

    app.extensions["scenarios"] = repo or ScenarioRepository()
    app.extensions["progress"] = store or SessionStore(lambda: session)

    from exposure_sim import stages  # noqa: F401  (importing registers every stage)
    from exposure_sim.routes import bp
    app.register_blueprint(bp)
    return app
