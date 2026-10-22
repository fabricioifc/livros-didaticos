import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import Flask

from .controllers import main
from .repository import initialize_db


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

    initialize_db(app.config["DATABASE_PATH"], app.config["SCHOOL_YEAR"])
    app.register_blueprint(main)
    return app
