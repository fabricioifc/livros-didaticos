import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import Flask, url_for

from .controllers import main
from .repository import get_school_year, initialize_db


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(test_config=None, allow_ephemeral_secret=False):
    """Cria a aplicação.

    Sem SECRET_KEY, a aplicação só inicia com allow_ephemeral_secret=True
    (execução local por server.py): uma chave aleatória por processo
    invalidaria sessões entre workers e a cada reinício.
    """
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", str(PROJECT_ROOT / "livros.db")),
        SCHOOL_YEAR=int(os.environ.get("SCHOOL_YEAR") or datetime.now().year),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower() == "true",
        MAX_CONTENT_LENGTH=1_500_000,
        # Duração máxima desde o login e tempo máximo sem uso, em segundos.
        SESSION_MAX_AGE=int(os.environ.get("SESSION_MAX_AGE") or 12 * 60 * 60),
        SESSION_IDLE_TIMEOUT=int(os.environ.get("SESSION_IDLE_TIMEOUT") or 30 * 60),
    )
    if test_config:
        app.config.update(test_config)
    app.config["BACKUP_PATH"] = (
        app.config.get("BACKUP_PATH")
        or os.environ.get("BACKUP_PATH")
        or str(Path(app.config["DATABASE_PATH"]).parent / "backups")
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = app.config["SESSION_MAX_AGE"]
    if not app.config["SECRET_KEY"]:
        if not allow_ephemeral_secret:
            raise RuntimeError(
                "Defina a variável de ambiente SECRET_KEY com um valor aleatório persistente."
            )
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    def static_asset_version(filename):
        asset_path = Path(app.static_folder) / filename
        return str(asset_path.stat().st_mtime_ns)

    def static_import_map():
        # Módulos importados não passam pelo template; o import map
        # aplica a eles o mesmo parâmetro de versão usado no main.js.
        modules = sorted((Path(app.static_folder) / "js").glob("*.js"))
        return {
            "imports": {
                url_for("static", filename=f"js/{module.name}"): url_for(
                    "static",
                    filename=f"js/{module.name}",
                    v=static_asset_version(f"js/{module.name}"),
                )
                for module in modules
            }
        }

    app.jinja_env.globals["static_asset_version"] = static_asset_version
    app.jinja_env.globals["static_import_map"] = static_import_map
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
