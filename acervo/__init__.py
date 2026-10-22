import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import Flask

from .controllers import main
from .repository import get_school_year, initialize_db


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", str(PROJECT_ROOT / "livros.db")),
        SCHOOL_YEAR=int(os.environ.get("SCHOOL_YEAR") or datetime.now().year),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower() == "true",
        MAX_CONTENT_LENGTH=1_500_000,
    )
    if test_config:
        app.config.update(test_config)

    def static_asset_version(filename):
        asset_path = Path(app.static_folder) / filename
        return str(asset_path.stat().st_mtime_ns)

    app.jinja_env.globals["static_asset_version"] = static_asset_version
    app.config["SCHOOL_YEAR"] = initialize_db(
        app.config["DATABASE_PATH"], app.config["SCHOOL_YEAR"]
    )

    @app.before_request
    def refresh_school_year():
        app.config["SCHOOL_YEAR"] = get_school_year(
            app.config["DATABASE_PATH"], app.config["SCHOOL_YEAR"]
        )

    app.register_blueprint(main)
    return app
