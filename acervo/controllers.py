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


@main.get("/api/courses")
@login_required
def list_courses():
    courses = services.get_courses(
        current_app.config["DATABASE_PATH"],
        include_inactive=True,
    )
    return jsonify({"courses": courses})


@main.post("/api/courses")
@admin_required
def create_course():
    error = csrf_error()
    if error:
        return error
    try:
        course = services.create_course(
            current_app.config["DATABASE_PATH"], request_body()
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(course), 201


@main.patch("/api/courses/<int:course_id>")
@admin_required
def update_course(course_id):
    error = csrf_error()
    if error:
        return error
    try:
        course = services.update_course(
            current_app.config["DATABASE_PATH"], course_id, request_body()
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(course)


@main.get("/api/students")
@login_required
def list_students():
    current_year = current_app.config["SCHOOL_YEAR"]
    requested_year = request.args.get("year", type=int)
    school_year = requested_year or current_year
    if school_year > current_year or school_year < 1900:
        return json_error("Ano letivo inválido.", 400)
    students = services.get_students(
        current_app.config["DATABASE_PATH"],
        request.args.get("q", ""),
        school_year,
        exact_year=requested_year is not None,
    )
    return jsonify({"students": students, "school_year": school_year})


@main.get("/api/school-years")
@login_required
def list_school_years():
    years = services.get_school_years(
        current_app.config["DATABASE_PATH"], current_app.config["SCHOOL_YEAR"]
    )
    return jsonify({"school_years": years})


@main.post("/api/settings/school-year")
@admin_required
def update_school_year():
    error = csrf_error()
    if error:
        return error
    try:
        school_year = services.update_school_year(
            current_app.config["DATABASE_PATH"],
            request_body().get("school_year"),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    current_app.config["SCHOOL_YEAR"] = school_year
    return jsonify({"school_year": school_year})


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
    template = "\ufeffmatricula;nome;turma;curso\r\n;;;\r\n;;;\r\n"
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


@main.get("/api/students/<enrollment>/books/<book_id>/history")
@login_required
def get_book_history(enrollment, book_id):
    try:
        history = services.get_book_signature_history(
            current_app.config["DATABASE_PATH"], enrollment, book_id
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify({"history": history})


@main.post("/api/students/<enrollment>/books/<book_id>/<action>/cancel")
@login_required
def cancel_book_signature(enrollment, book_id, action):
    error = csrf_error()
    if error:
        return error
    try:
        student = services.cancel_book_signature(
            current_app.config["DATABASE_PATH"],
            enrollment,
            book_id,
            action,
            request_body(),
            g.user_email,
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
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
            request_body().get("enrollment_confirmation"),
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)


@main.post("/api/students/<enrollment>/books/checkout")
@login_required
def record_book_checkouts(enrollment):
    error = csrf_error()
    if error:
        return error
    body = request_body()
    try:
        student = services.sign_books(
            current_app.config["DATABASE_PATH"],
            enrollment,
            body.get("book_ids"),
            body.get("signature"),
            g.user_email,
            current_app.config["SCHOOL_YEAR"],
            body.get("enrollment_confirmation"),
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)
