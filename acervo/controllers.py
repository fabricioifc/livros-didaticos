import hmac
import secrets
from functools import wraps

from flask import Blueprint, Response, current_app, g, jsonify, render_template, request, session

from . import services


main = Blueprint("main", __name__)


def json_error(message, status):
    return jsonify({"error": message}), status


def csrf_error():
    token = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(token, session.get("csrf_token", "")):
        return json_error("Sessão expirada. Atualize a página e tente novamente.", 403)
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return json_error("Faça login para continuar.", 401)
        g.user_email = session["email"]
        return view(*args, **kwargs)

    return wrapped


def request_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def handle_service_error(error):
    return json_error(str(error), error.status)


@main.get("/")
def index():
    return render_template("index.html")


@main.post("/api/auth/login")
def login():
    if "csrf_token" in session:
        error = csrf_error()
        if error:
            return error
    body = request_body()
    try:
        user = services.authenticate(
            current_app.config["DATABASE_PATH"],
            body.get("email"),
            body.get("password"),
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    session.clear()
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"email": user["email"], "csrf_token": session["csrf_token"]})


@main.get("/api/auth/session")
def auth_session():
    if "user_id" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"authenticated": False, "csrf_token": session["csrf_token"]})
    return jsonify(
        {"authenticated": True, "email": session["email"], "csrf_token": session["csrf_token"]}
    )


@main.post("/api/auth/logout")
@login_required
def logout():
    error = csrf_error()
    if error:
        return error
    session.clear()
    return jsonify({"ok": True})


@main.get("/api/students")
@login_required
def list_students():
    school_year = current_app.config["SCHOOL_YEAR"]
    students = services.get_students(
        current_app.config["DATABASE_PATH"], request.args.get("q", ""), school_year
    )
    return jsonify({"students": students, "school_year": school_year})


@main.post("/api/students")
@login_required
def create_student():
    error = csrf_error()
    if error:
        return error
    try:
        student = services.create_student(
            current_app.config["DATABASE_PATH"],
            request_body(),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student), 201


@main.post("/api/students/import")
@login_required
def import_students():
    error = csrf_error()
    if error:
        return error
    uploaded_file = request.files.get("file")
    if not uploaded_file:
        return json_error("Selecione um arquivo CSV para importar.", 400)
    try:
        result = services.import_students(
            current_app.config["DATABASE_PATH"],
            uploaded_file.filename,
            uploaded_file.read(),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(result)


@main.get("/api/students/import-template")
@login_required
def download_import_template():
    template = "\ufeffmatricula;nome;turma\r\n;;\r\n;;\r\n"
    return Response(
        template,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="modelo-estudantes.csv"'},
    )


@main.put("/api/students/<enrollment>")
@login_required
def update_student(enrollment):
    error = csrf_error()
    if error:
        return error
    try:
        student = services.update_student(
            current_app.config["DATABASE_PATH"],
            enrollment,
            request_body(),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)


@main.get("/api/students/<enrollment>")
@login_required
def get_student(enrollment):
    school_year = request.args.get("year", type=int)
    student = services.get_student(
        current_app.config["DATABASE_PATH"], enrollment, school_year
    )
    if not student:
        return json_error("Estudante não encontrado.", 404)
    return jsonify(student)


@main.put("/api/students/<enrollment>/books/<book_id>/<action>")
@login_required
def record_signature(enrollment, book_id, action):
    error = csrf_error()
    if error:
        return error
    try:
        student = services.sign_book(
            current_app.config["DATABASE_PATH"],
            enrollment,
            book_id,
            action,
            request_body().get("signature"),
            g.user_email,
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)
