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
        user = services.repository.find_user_by_id(
            current_app.config["DATABASE_PATH"], session["user_id"]
        )
        if not user or not user["is_active"]:
            session.clear()
            return json_error("Sua conta está desativada. Fale com um administrador.", 401)
        g.user_id = user["id"]
        g.user_email = user["email"]
        g.user_is_admin = bool(user["is_admin"])
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @login_required
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user_is_admin:
            return json_error("Acesso restrito a administradores.", 403)
        return view(*args, **kwargs)

    return wrapped


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        enrollment = session.get("student_enrollment")
        if not enrollment:
            return json_error("Faça login como estudante para continuar.", 401)
        credential = services.repository.find_student_credential(
            current_app.config["DATABASE_PATH"], enrollment
        )
        if (
            not credential
            or session.get("student_token_version") != credential["token_version"]
        ):
            session.pop("student_enrollment", None)
            session.pop("student_token_version", None)
            return json_error("Acesso de estudante não encontrado.", 401)
        g.student_enrollment = enrollment
        g.student_must_change_password = bool(credential["must_change_password"])
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


@main.get("/privacidade")
def privacy_notice():
    return render_template("privacy.html")


@main.get("/aluno")
def student_portal():
    return render_template("student.html")


@main.post("/api/student-auth/login")
def student_login():
    if "csrf_token" in session:
        error = csrf_error()
        if error:
            return error
    body = request_body()
    try:
        student = services.authenticate_student(
            current_app.config["DATABASE_PATH"],
            body.get("enrollment"),
            body.get("password"),
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    session.clear()
    session["student_enrollment"] = student["enrollment"]
    credential = services.repository.find_student_credential(
        current_app.config["DATABASE_PATH"], student["enrollment"]
    )
    session["student_token_version"] = credential["token_version"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(
        {
            **student,
            "csrf_token": session["csrf_token"],
        }
    )


@main.get("/api/student-auth/session")
def student_session():
    enrollment = session.get("student_enrollment")
    credential = (
        services.repository.find_student_credential(
            current_app.config["DATABASE_PATH"], enrollment
        )
        if enrollment
        else None
    )
    if (
        not credential
        or session.get("student_token_version") != credential["token_version"]
    ):
        session.pop("student_enrollment", None)
        session.pop("student_token_version", None)
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return jsonify({"authenticated": False, "csrf_token": session["csrf_token"]})
    return jsonify(
        {
            "authenticated": True,
            "enrollment": enrollment,
            "name": credential["name"],
            "must_change_password": bool(credential["must_change_password"]),
            "csrf_token": session.get("csrf_token", ""),
        }
    )


@main.post("/api/student-auth/password")
@student_required
def change_student_password():
    error = csrf_error()
    if error:
        return error
    try:
        services.change_student_password(
            current_app.config["DATABASE_PATH"],
            g.student_enrollment,
            request_body(),
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    credential = services.repository.find_student_credential(
        current_app.config["DATABASE_PATH"], g.student_enrollment
    )
    session["student_token_version"] = credential["token_version"]
    return jsonify({"ok": True})


@main.post("/api/student-auth/qr")
@student_required
def create_student_qr():
    error = csrf_error()
    if error:
        return error
    try:
        result = services.issue_student_qr(
            current_app.config["DATABASE_PATH"],
            g.student_enrollment,
            current_app.config["SECRET_KEY"],
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(result)


@main.post("/api/student-auth/logout")
@student_required
def student_logout():
    error = csrf_error()
    if error:
        return error
    session.pop("student_enrollment", None)
    session.pop("student_token_version", None)
    return jsonify({"ok": True})


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
    return jsonify(
        {
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
            "csrf_token": session["csrf_token"],
        }
    )


@main.get("/api/auth/session")
def auth_session():
    if "user_id" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"authenticated": False, "csrf_token": session["csrf_token"]})
    user = services.repository.find_user_by_id(
        current_app.config["DATABASE_PATH"], session["user_id"]
    )
    if not user or not user["is_active"]:
        session.clear()
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"authenticated": False, "csrf_token": session["csrf_token"]})
    return jsonify(
        {
            "authenticated": True,
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
            "csrf_token": session["csrf_token"],
        }
    )


@main.post("/api/auth/logout")
@login_required
def logout():
    error = csrf_error()
    if error:
        return error
    session.clear()
    return jsonify({"ok": True})


@main.get("/api/users")
@admin_required
def list_users():
    return jsonify({"users": services.get_users(current_app.config["DATABASE_PATH"])})


@main.post("/api/users")
@admin_required
def create_managed_user():
    error = csrf_error()
    if error:
        return error
    try:
        user = services.create_managed_user(
            current_app.config["DATABASE_PATH"], request_body()
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(user), 201


@main.patch("/api/users/<int:user_id>")
@admin_required
def update_managed_user(user_id):
    error = csrf_error()
    if error:
        return error
    try:
        user = services.update_managed_user(
            current_app.config["DATABASE_PATH"],
            user_id,
            request_body(),
            g.user_id,
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(user)


@main.post("/api/students/<enrollment>/student-access")
@admin_required
def reset_student_access(enrollment):
    error = csrf_error()
    if error:
        return error
    try:
        password = services.reset_student_access(
            current_app.config["DATABASE_PATH"], enrollment
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify({"temporary_password": password, "portal_url": "/aluno"})


@main.post("/api/student-qr/verify")
@login_required
def verify_student_qr():
    error = csrf_error()
    if error:
        return error
    body = request_body()
    try:
        student = services.verify_student_qr(
            current_app.config["DATABASE_PATH"],
            body.get("token"),
            current_app.config["SECRET_KEY"],
            body.get("enrollment"),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)


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
            request_body().get("student_qr_token"),
            current_app.config["SECRET_KEY"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)
