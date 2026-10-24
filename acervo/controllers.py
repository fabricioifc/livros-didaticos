import hmac
import re
import secrets
import time
from functools import wraps

from flask import Blueprint, Response, current_app, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from . import google_oauth, services


main = Blueprint("main", __name__)


def json_error(message, status):
    return jsonify({"error": message}), status


def csrf_error():
    token = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(token, expected):
        return json_error("Sessão expirada. Atualize a página e tente novamente.", 403)
    return None


def start_session(user):
    now = int(time.time())
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["session_version"] = user["session_version"]
    session["login_at"] = now
    session["last_seen"] = now
    session["csrf_token"] = secrets.token_urlsafe(32)


def reset_anonymous_session():
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(32)


def session_user():
    """Devolve o usuário da sessão ou uma mensagem explicando por que ela acabou."""
    if "user_id" not in session:
        return None, "Faça login para continuar."
    now = int(time.time())
    config = current_app.config
    if (
        now - session.get("login_at", 0) > config["SESSION_MAX_AGE"]
        or now - session.get("last_seen", 0) > config["SESSION_IDLE_TIMEOUT"]
    ):
        return None, "Sua sessão expirou. Faça login novamente."
    user = services.repository.find_user_by_id(config["DATABASE_PATH"], session["user_id"])
    if not user or not user["is_active"]:
        return None, "Sua conta está desativada. Fale com um administrador."
    if user["session_version"] != session.get("session_version"):
        return None, "Sua sessão foi encerrada. Faça login novamente."
    session["last_seen"] = now
    return user, None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user, reason = session_user()
        if not user:
            reset_anonymous_session()
            return json_error(reason, 401)
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


@main.get("/service-worker.js")
def service_worker():
    response = send_from_directory(
        current_app.static_folder,
        "service-worker.js",
        mimetype="application/javascript",
        max_age=0,
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@main.get("/privacidade")
def privacy_notice():
    return render_template("privacy.html")


@main.post("/api/auth/login")
def login():
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
    start_session(user)
    return jsonify(
        {
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
            "csrf_token": session["csrf_token"],
        }
    )


@main.get("/api/auth/session")
def auth_session():
    user, _ = session_user()
    if not user:
        if "user_id" in session or "csrf_token" not in session:
            reset_anonymous_session()
        return jsonify(
            {
                "authenticated": False,
                "csrf_token": session["csrf_token"],
                "google_enabled": google_oauth.is_configured(current_app.config),
            }
        )
    return jsonify(
        {
            "authenticated": True,
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
            "csrf_token": session["csrf_token"],
            "google_enabled": google_oauth.is_configured(current_app.config),
        }
    )


@main.get("/api/auth/google/start")
def google_login_start():
    if not google_oauth.is_configured(current_app.config):
        return json_error("Login com Google não configurado.", 404)
    url, flow = google_oauth.start(current_app.config)
    session["google_oauth"] = flow
    return redirect(url)


@main.get("/api/auth/google/callback")
def google_login_callback():
    flow = session.pop("google_oauth", None)

    def failed(code, detail):
        current_app.logger.warning("Login com Google recusado (%s): %s", code, detail)
        return redirect(url_for("main.index", login_error=code))

    if not google_oauth.is_configured(current_app.config):
        return failed("google", "login com Google não configurado")
    if request.args.get("error"):
        return failed("cancelado", request.args.get("error"))
    try:
        google_oauth.check_callback_state(flow, request.args.get("state"))
        code = request.args.get("code")
        if not code:
            raise google_oauth.GoogleAuthError("google", "Retorno do Google sem código.")
        tokens = google_oauth.exchange_code(current_app.config, code, flow["verifier"])
        email = google_oauth.id_token_email(tokens["id_token"], current_app.config, flow["nonce"])
        user = services.google_login(current_app.config["DATABASE_PATH"], email)
    except google_oauth.GoogleAuthError as error:
        return failed(error.code, error)
    except services.ServiceError as error:
        return failed("conta", error)
    start_session(user)
    return redirect(url_for("main.index"))


@main.post("/api/auth/logout")
@login_required
def logout():
    error = csrf_error()
    if error:
        return error
    # Invalida também cópias do cookie desta conta em outros dispositivos.
    services.repository.bump_session_version(current_app.config["DATABASE_PATH"], g.user_id)
    reset_anonymous_session()
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


@main.get("/api/books")
@admin_required
def list_books():
    return jsonify({"books": services.repository.list_books(current_app.config["DATABASE_PATH"])})


@main.post("/api/books")
@admin_required
def create_book():
    error = csrf_error()
    if error:
        return error
    try:
        book = services.create_book(
            current_app.config["DATABASE_PATH"],
            request_body(),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(book), 201


@main.put("/api/books/<int:book_id>")
@admin_required
def update_book(book_id):
    error = csrf_error()
    if error:
        return error
    try:
        book = services.update_book(
            current_app.config["DATABASE_PATH"],
            book_id,
            request_body(),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(book)


@main.delete("/api/books/<int:book_id>")
@admin_required
def delete_book(book_id):
    error = csrf_error()
    if error:
        return error
    try:
        services.delete_book(current_app.config["DATABASE_PATH"], book_id)
    except services.ServiceError as error:
        return handle_service_error(error)
    return "", 204


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


@main.get("/api/school-years/<int:school_year>/terms.zip")
@admin_required
def export_year_terms(school_year):
    try:
        archive = services.export_year_terms(
            current_app.config["DATABASE_PATH"], school_year, current_app.config["SCHOOL_YEAR"]
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return Response(
        archive,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="termos-{school_year}.zip"',
            "Cache-Control": "no-store",
        },
    )


@main.post("/api/settings/school-year")
@admin_required
def update_school_year():
    error = csrf_error()
    if error:
        return error
    try:
        school_year, backup = services.update_school_year(
            current_app.config["DATABASE_PATH"],
            current_app.config["BACKUP_PATH"],
            request_body().get("school_year"),
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        if error.status >= 500:
            current_app.logger.error("Falha ao avançar o ano letivo: %s", error)
        return handle_service_error(error)
    current_app.config["SCHOOL_YEAR"] = school_year
    return jsonify({"school_year": school_year, "backup": backup})


@main.get("/api/backups")
@admin_required
def list_backups():
    return jsonify({"backups": services.list_database_backups(current_app.config["BACKUP_PATH"])})


@main.post("/api/backups")
@admin_required
def create_backup():
    error = csrf_error()
    if error:
        return error
    try:
        backup = services.create_database_backup(
            current_app.config["DATABASE_PATH"],
            current_app.config["BACKUP_PATH"],
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        current_app.logger.error("Falha ao criar backup: %s", error)
        return handle_service_error(error)
    return jsonify({"backup": backup}), 201


@main.post("/api/backups/restore")
@admin_required
def restore_backup():
    error = csrf_error()
    if error:
        return error
    # O limite global protege as demais rotas; o banco completo pode ser maior.
    request.max_content_length = services.MAX_BACKUP_UPLOAD_BYTES + 1024 * 1024
    uploaded = request.files.get("backup")
    if not uploaded:
        return json_error("Selecione um arquivo SQLite de backup.", 400)
    try:
        safety_backup = services.restore_database_backup(
            current_app.config["DATABASE_PATH"],
            current_app.config["BACKUP_PATH"],
            uploaded.stream,
            uploaded.filename,
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        if error.status >= 500:
            current_app.logger.error("Falha ao restaurar backup: %s", error)
        return handle_service_error(error)
    current_app.logger.warning(
        "Banco restaurado por %s. Backup de segurança: %s",
        g.user_email,
        safety_backup["filename"],
    )
    # A restauração encerra todas as sessões, inclusive a atual.
    reset_anonymous_session()
    return jsonify({"safety_backup": safety_backup, "csrf_token": session["csrf_token"]})


@main.get("/api/backups/<filename>")
@admin_required
def download_backup(filename):
    if not re.fullmatch(services.BACKUP_FILENAME_PATTERN, filename):
        return json_error("Backup não encontrado.", 404)
    response = send_from_directory(
        current_app.config["BACKUP_PATH"],
        filename,
        as_attachment=True,
        mimetype="application/vnd.sqlite3",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@main.post("/api/students")
@admin_required
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
@admin_required
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
@admin_required
def download_import_template():
    template = "\ufeffmatricula;nome;turma;curso\r\n;;;\r\n;;;\r\n"
    return Response(
        template,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="modelo-estudantes.csv"'},
    )


@main.put("/api/students/<enrollment>")
@admin_required
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


@main.post("/api/students/<enrollment>/archive")
@admin_required
def archive_student(enrollment):
    error = csrf_error()
    if error:
        return error
    try:
        student = services.archive_student(
            current_app.config["DATABASE_PATH"],
            enrollment,
            request_body(),
            g.user_email,
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)


@main.post("/api/students/<enrollment>/reactivate")
@admin_required
def reactivate_student(enrollment):
    error = csrf_error()
    if error:
        return error
    try:
        student = services.reactivate_student(
            current_app.config["DATABASE_PATH"],
            enrollment,
            g.user_email,
            current_app.config["SCHOOL_YEAR"],
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)


@main.delete("/api/students/<enrollment>")
@admin_required
def delete_student(enrollment):
    error = csrf_error()
    if error:
        return error
    try:
        services.delete_student(current_app.config["DATABASE_PATH"], enrollment)
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify({"ok": True})


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
        )
    except services.ServiceError as error:
        return handle_service_error(error)
    return jsonify(student)
