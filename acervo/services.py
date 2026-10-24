import csv
import io
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from . import repository, term_pdf
from .models import GRADES, is_ifc_email, normalize_email, now_iso, validate_signature


class ServiceError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


MAX_BACKUP_UPLOAD_BYTES = 64 * 1024 * 1024
BACKUP_FILENAME_PATTERN = r"backup-[0-9]{4}-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\.sqlite3"


def _is_valid_enrollment(enrollment):
    return isinstance(enrollment, str) and re.fullmatch(r"[0-9]{10}", enrollment) is not None


def create_user(database_path, email, password, is_admin=False):
    email = normalize_email(email)
    if not is_ifc_email(email):
        raise ValueError("Use um e-mail @ifc.edu.br.")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
        raise ValueError("A senha precisa ter entre 12 e 128 caracteres.")
    repository.add_user(
        database_path, email, generate_password_hash(password), now_iso(), is_admin
    )


LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW = 15 * 60
# Conferido quando o e-mail não existe, para o tempo de resposta não
# revelar quais contas estão cadastradas.
_UNKNOWN_USER_HASH = generate_password_hash("conta-inexistente")


def authenticate(database_path, email, password, now=None):
    email = normalize_email(email)
    if not is_ifc_email(email) or not isinstance(password, str):
        raise ServiceError("Informe um e-mail @ifc.edu.br e uma senha.", 400)
    now = time.time() if now is None else now
    window_start = now - LOGIN_FAILURE_WINDOW
    # O bloqueio vale por e-mail e é verificado antes da senha, para que
    # tentativas durante o bloqueio não revelem se a senha estava certa.
    if repository.count_login_failures(database_path, email, window_start) >= LOGIN_MAX_FAILURES:
        raise ServiceError(
            "Muitas tentativas de login. Aguarde 15 minutos e tente novamente.", 429
        )
    user = repository.find_user(database_path, email)
    password_ok = check_password_hash(
        user["password_hash"] if user else _UNKNOWN_USER_HASH, password
    )
    if not user or not user["is_active"] or not password_ok:
        repository.record_login_failure(database_path, email, now, window_start)
        raise ServiceError("E-mail ou senha incorretos.", 401)
    repository.clear_login_failures(database_path, email)
    return user


def get_users(database_path):
    return repository.list_users(database_path)


def create_managed_user(database_path, body):
    email = normalize_email(body.get("email"))
    password = body.get("password")
    is_admin = body.get("is_admin", False)
    if not isinstance(is_admin, bool):
        raise ServiceError("O perfil de administrador é inválido.", 400)
    if not is_ifc_email(email):
        raise ServiceError("Use um e-mail @ifc.edu.br.", 400)
    if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
        raise ServiceError("A senha precisa ter entre 12 e 128 caracteres.", 400)
    try:
        create_user(database_path, email, password, is_admin)
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed: users.email" in str(error):
            raise ServiceError("Já existe uma conta com esse e-mail.", 409) from error
        raise
    return next(user for user in repository.list_users(database_path) if user["email"] == email)


def update_managed_user(database_path, target_id, body, current_user_id):
    is_admin = body.get("is_admin")
    is_active = body.get("is_active")
    if not isinstance(is_admin, bool) or not isinstance(is_active, bool):
        raise ServiceError("Informe o perfil e o status da conta.", 400)
    if target_id == current_user_id and (not is_admin or not is_active):
        raise ServiceError("Não é possível remover seu próprio acesso de administrador.", 409)
    result = repository.update_user(database_path, target_id, is_admin, is_active)
    errors = {
        "not_found": ("Conta não encontrada.", 404),
        "last_admin": ("Não é possível desativar ou rebaixar o último administrador ativo.", 409),
    }
    if result:
        message, status = errors[result]
        raise ServiceError(message, status)
    return next(user for user in repository.list_users(database_path) if user["id"] == target_id)


def get_students(database_path, query, school_year, exact_year=False):
    return repository.list_students(
        database_path, query.strip()[:100], school_year, exact_year
    )


def get_school_years(database_path, current_year):
    return repository.list_school_years(database_path, current_year)


def get_student(database_path, enrollment, school_year=None):
    return repository.find_student(database_path, enrollment, school_year)


def _safe_filename(value):
    """Nome de arquivo portátil: sem acentos nem caracteres reservados."""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", "", ascii_text)
    return re.sub(r"\s+", " ", cleaned).strip(" .") or "sem-nome"


def export_year_terms(database_path, school_year, current_year):
    """ZIP com um PDF por estudante, em uma pasta por curso."""
    if not isinstance(school_year, int) or school_year > current_year or school_year < 1900:
        raise ServiceError("Ano letivo inválido.", 400)
    students = repository.list_students(database_path, "", school_year, exact_year=True)
    if not students:
        raise ServiceError(f"Não há termos registrados para {school_year}.", 404)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for summary in students:
            student = repository.find_student(database_path, summary["enrollment"], school_year)
            folder = _safe_filename(
                f"{student['course_abbreviation'] or ''} - {student['course_name']}".strip(" -")
            )
            filename = _safe_filename(f"{student['enrollment']} - {student['name']}")
            zipped.writestr(f"{folder}/{filename}.pdf", term_pdf.build_term_pdf(student))
    return archive.getvalue()


def get_courses(database_path, include_inactive=False):
    return repository.list_courses(database_path, include_inactive)


def create_course(database_path, body):
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        raise ServiceError("Informe o nome do curso (até 150 caracteres).", 400)
    abbreviation = body.get("abbreviation")
    if not isinstance(abbreviation, str):
        raise ServiceError("Informe uma sigla com 3 a 5 caracteres.", 400)
    abbreviation = abbreviation.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,5}", abbreviation):
        raise ServiceError(
            "A sigla deve conter de 3 a 5 letras ou números.",
            400,
        )
    try:
        course_id = repository.add_course(
            database_path, name.strip(), abbreviation
        )
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed: courses.name" in str(error):
            raise ServiceError("Já existe um curso com esse nome.", 409) from error
        if "courses.abbreviation" in str(error):
            raise ServiceError("Já existe um curso com essa sigla.", 409) from error
        raise
    return repository.find_course(database_path, course_id)


def update_course(database_path, course_id, body):
    is_active = body.get("is_active")
    if not isinstance(is_active, bool):
        raise ServiceError("Informe se o curso está ativo.", 400)
    result = repository.set_course_active(database_path, course_id, is_active)
    if result == "not_found":
        raise ServiceError("Curso não encontrado.", 404)
    if result == "last_active_course":
        raise ServiceError("Não é possível desativar o último curso ativo.", 409)
    return repository.find_course(database_path, course_id)


def update_school_year(database_path, backup_directory, value, current_year):
    if isinstance(value, bool) or not isinstance(value, int) or not 1900 <= value <= 2100:
        raise ServiceError("Informe um ano letivo válido entre 1900 e 2100.", 400)
    if value < current_year:
        raise ServiceError(
            "Não é possível voltar para um ano anterior, pois os ciclos letivos e "
            "arquivamentos já criados não podem ser desfeitos.",
            409,
        )
    backup = None
    if value > current_year:
        try:
            backup = create_database_backup(database_path, backup_directory, current_year)
        except ServiceError as error:
            raise ServiceError(f"{error} O ano letivo não foi alterado.", error.status) from error
    try:
        result = repository.update_school_year(database_path, value)
    except ValueError as error:
        raise ServiceError(str(error), 409) from error
    if result == "cannot_decrease":
        raise ServiceError(
            "O ano letivo já foi atualizado por outra solicitação. Atualize a página.",
            409,
        )
    return value, backup


def create_database_backup(database_path, backup_directory, school_year):
    filename = (
        f"backup-{school_year}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-"
        f"{uuid.uuid4().hex[:8]}.sqlite3"
    )
    try:
        repository.create_database_backup(database_path, backup_directory, filename)
    except (OSError, sqlite3.Error, ValueError) as error:
        raise ServiceError(
            "Não foi possível criar e validar o backup completo.",
            500,
        ) from error
    return {"filename": filename, "created_at": now_iso()}


def list_database_backups(backup_directory):
    backup_directory = Path(backup_directory)
    if not backup_directory.is_dir():
        return []
    backups = []
    for path in backup_directory.iterdir():
        if not path.is_file() or not re.fullmatch(BACKUP_FILENAME_PATTERN, path.name):
            continue
        stat = path.stat()
        backups.append(
            {
                "filename": path.name,
                "size": stat.st_size,
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)
                ),
            }
        )
    return sorted(backups, key=lambda backup: backup["created_at"], reverse=True)


def restore_database_backup(database_path, backup_directory, uploaded_file, filename, school_year):
    if not isinstance(filename, str) or Path(filename).suffix.lower() not in {
        ".sqlite",
        ".sqlite3",
        ".db",
    }:
        raise ServiceError("Selecione um arquivo SQLite de backup.", 400)

    backup_directory = Path(backup_directory)
    try:
        backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".restore-", suffix=".sqlite3", dir=backup_directory
        )
    except OSError as error:
        raise ServiceError("Não foi possível preparar a restauração do backup.", 500) from error

    temporary_path = Path(temporary_name)
    try:
        size = 0
        with os.fdopen(descriptor, "wb") as temporary_file:
            while chunk := uploaded_file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BACKUP_UPLOAD_BYTES:
                    raise ServiceError("O backup excede o limite de 64 MB.", 413)
                temporary_file.write(chunk)
        if size == 0:
            raise ServiceError("O arquivo de backup está vazio.", 400)
        try:
            repository.validate_database_backup(temporary_path)
        except (sqlite3.Error, ValueError) as error:
            raise ServiceError(
                f"Backup inválido ou incompatível: {error}",
                400,
            ) from error

        safety_backup = create_database_backup(
            database_path, backup_directory, school_year
        )
        safety_backup_path = backup_directory / safety_backup["filename"]
        try:
            repository.restore_database_backup(database_path, temporary_path)
            # Aplica as migrações a backups criados por versões anteriores.
            repository.initialize_db(database_path, school_year)
        except (OSError, sqlite3.Error) as error:
            try:
                repository.restore_database_backup(database_path, safety_backup_path)
            except (OSError, sqlite3.Error) as rollback_error:
                raise ServiceError(
                    "A restauração falhou e não foi possível recuperar automaticamente "
                    "o banco anterior. O backup de segurança está disponível para "
                    f"restauração manual: {safety_backup['filename']}.",
                    500,
                ) from rollback_error
            raise ServiceError(
                "A restauração falhou; o banco anterior foi recuperado. "
                f"Backup de segurança: {safety_backup['filename']}.",
                500,
            ) from error
        return safety_backup
    finally:
        temporary_path.unlink(missing_ok=True)


def create_student(database_path, body, school_year):
    name = body.get("name")
    enrollment = body.get("enrollment")
    grade = body.get("grade")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        raise ServiceError("Informe o nome do estudante (até 150 caracteres).", 400)
    if not _is_valid_enrollment(enrollment.strip() if isinstance(enrollment, str) else enrollment):
        raise ServiceError("A matrícula deve conter exatamente 10 números.", 400)
    if grade not in GRADES:
        raise ServiceError("Selecione o 1º, 2º ou 3º ano.", 400)
    course_id = body.get("course_id")
    if isinstance(course_id, bool) or not isinstance(course_id, int):
        raise ServiceError("Selecione um curso válido.", 400)
    course = repository.find_course(database_path, course_id)
    if not course or not course["is_active"]:
        raise ServiceError("O curso selecionado não existe ou está inativo.", 400)
    enrollment = enrollment.strip()
    try:
        repository.add_student(
            database_path,
            enrollment,
            name.strip(),
            grade,
            course_id,
            now_iso(),
            school_year,
        )
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed: students.enrollment" in str(error):
            raise ServiceError("Já existe um estudante com essa matrícula.", 409) from error
        raise
    return repository.find_student(database_path, enrollment, school_year)


def _normalized_header(value):
    value = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(char for char in value if not unicodedata.combining(char))


def _normalize_grade(value):
    normalized = _normalized_header(value)
    match = re.fullmatch(r"([123])\s*(?:[º°oa]\s*)?(?:ano)?", normalized)
    return f"{match.group(1)}º" if match else None


def import_students(database_path, filename, content, school_year):
    if not isinstance(filename, str) or not filename.lower().endswith(".csv"):
        raise ServiceError("Selecione um arquivo com extensão .csv.", 400)
    if not content:
        raise ServiceError("O arquivo CSV está vazio.", 400)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1252")
        except UnicodeDecodeError as error:
            raise ServiceError("O arquivo deve usar codificação UTF-8 ou Windows-1252.", 400) from error

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        delimiter = ";" if sample.splitlines() and sample.splitlines()[0].count(";") > sample.splitlines()[0].count(",") else ","
        dialect = csv.excel
        dialect.delimiter = delimiter

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
        headers = reader.fieldnames or []
        normalized_headers = {_normalized_header(header): header for header in headers if header}
        required = {"matricula", "nome", "turma", "curso"}
        if not required.issubset(normalized_headers):
            raise ServiceError(
                "O CSV precisa ter cabeçalhos para matrícula, nome, turma e curso.",
                400,
            )

        courses = repository.list_courses(database_path)
        course_identifiers = {}
        for course in courses:
            course_identifiers[course["name"].casefold()] = course["id"]
            course_identifiers[course["abbreviation"].casefold()] = course["id"]
        valid_students = []
        invalid_rows = []
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not (value or "").strip() for value in row.values() if isinstance(value, str)):
                continue
            enrollment = (row.get(normalized_headers["matricula"]) or "").strip()
            name = (row.get(normalized_headers["nome"]) or "").strip()
            grade_value = (row.get(normalized_headers["turma"]) or "").strip()
            course_name = (row.get(normalized_headers["curso"]) or "").strip()
            grade = _normalize_grade(grade_value)
            course_id = course_identifiers.get(course_name.casefold())

            if not _is_valid_enrollment(enrollment):
                invalid_rows.append({"line": line_number, "reason": "matrícula inválida"})
            elif not name or len(name) > 150:
                invalid_rows.append({"line": line_number, "reason": "nome ausente ou maior que 150 caracteres"})
            elif not grade:
                invalid_rows.append({"line": line_number, "reason": "turma deve ser 1º, 2º ou 3º"})
            elif course_id is None:
                invalid_rows.append({"line": line_number, "reason": "curso inválido ou inativo"})
            else:
                valid_students.append(
                    {
                        "enrollment": enrollment,
                        "name": name,
                        "grade": grade,
                        "course_id": course_id,
                        "created_at": now_iso(),
                    }
                )
    except csv.Error as error:
        raise ServiceError("Não foi possível interpretar o arquivo CSV.", 400) from error

    imported = repository.import_students(database_path, valid_students, school_year)
    ignored = len(valid_students) - imported
    return {
        "imported": imported,
        "ignored": ignored,
        "invalid": len(invalid_rows),
        "errors": invalid_rows[:50],
    }


def update_student(database_path, enrollment, body, school_year):
    name = body.get("name")
    grade = body.get("grade")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        raise ServiceError("Informe o nome do estudante (até 150 caracteres).", 400)
    if grade not in GRADES:
        raise ServiceError("Selecione o 1º, 2º ou 3º ano.", 400)
    course_id = body.get("course_id")
    if isinstance(course_id, bool) or not isinstance(course_id, int):
        raise ServiceError("Selecione um curso válido.", 400)
    course = repository.find_course(database_path, course_id)
    current = repository.find_student(database_path, enrollment, school_year)
    if not current:
        raise ServiceError("Estudante não encontrado.", 404)
    if current["is_archived"]:
        raise ServiceError("Reative o vínculo antes de editar o cadastro.", 409)
    if not course or (not course["is_active"] and current["course_id"] != course_id):
        raise ServiceError("O curso selecionado não existe ou está inativo.", 400)
    if not repository.update_student(
        database_path, enrollment, name.strip(), grade, course_id, school_year
    ):
        raise ServiceError("Estudante não encontrado.", 404)
    return repository.find_student(database_path, enrollment, school_year)


def archive_student(database_path, enrollment, body, actor_email):
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ServiceError("Informe o motivo do desligamento (até 500 caracteres).", 400)
    result = repository.archive_student(
        database_path, enrollment, actor_email, reason.strip(), now_iso()
    )
    errors = {
        "not_found": ("Estudante não encontrado.", 404),
        "already_archived": ("Este estudante já está desvinculado.", 409),
    }
    if result:
        message, status = errors[result]
        raise ServiceError(message, status)
    return repository.find_student(database_path, enrollment)


def reactivate_student(database_path, enrollment, actor_email, school_year):
    result = repository.reactivate_student(
        database_path, enrollment, school_year, actor_email, now_iso()
    )
    errors = {
        "not_found": ("Estudante não encontrado.", 404),
        "not_archived": ("Este estudante não está desvinculado.", 409),
    }
    if result:
        message, status = errors[result]
        raise ServiceError(message, status)
    return repository.find_student(database_path, enrollment, school_year)


def delete_student(database_path, enrollment):
    result = repository.delete_student_without_history(database_path, enrollment)
    errors = {
        "not_found": ("Estudante não encontrado.", 404),
        "has_history": (
            "Este cadastro possui empréstimos, devoluções, assinaturas ou histórico. "
            "Desvincule o estudante para preservar os registros.",
            409,
        ),
    }
    if result:
        message, status = errors[result]
        raise ServiceError(message, status)


def get_book_signature_history(database_path, enrollment, book_id):
    history = repository.get_book_signature_history(database_path, enrollment, book_id)
    if history is None:
        raise ServiceError("Livro não encontrado para este estudante.", 404)
    return history


def cancel_book_signature(
    database_path, enrollment, book_id, action, body, actor_email, school_year
):
    if action not in {"checkout", "return"}:
        raise ServiceError("Operação de cancelamento inválida.", 400)
    reason = body.get("reason")
    if not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 500:
        raise ServiceError("Informe o motivo da correção (entre 5 e 500 caracteres).", 400)
    result = repository.cancel_book_signature(
        database_path,
        enrollment,
        book_id,
        action,
        reason.strip(),
        now_iso(),
        actor_email,
        school_year,
    )
    errors = {
        "book_not_found": ("Livro não encontrado para este estudante.", 404),
        "checkout_not_found": ("Não há uma entrega ativa para cancelar.", 409),
        "return_not_found": ("Não há uma devolução ativa para cancelar.", 409),
        "return_must_be_cancelled_first": (
            "Cancele a devolução antes de cancelar a entrega.", 409
        ),
        "invalid_action": ("Operação de cancelamento inválida.", 400),
    }
    if result:
        message, status = errors[result]
        raise ServiceError(message, status)
    return repository.find_student(database_path, enrollment, school_year) or repository.find_student(
        database_path, enrollment
    )


def sign_book(
    database_path,
    enrollment,
    book_id,
    action,
    signature,
    server_email,
    school_year,
    enrollment_confirmation=None,
):
    if action not in {"checkout", "return"}:
        raise ServiceError("Operação inválida.", 400)
    student = repository.find_student(database_path, enrollment, school_year)
    if action == "checkout" and (
        not student or student["status"] != "active" or student["is_archived"]
    ):
        raise ServiceError("Não é possível registrar uma entrega fora do ciclo letivo ativo.", 409)
    if not student and action == "return":
        student = repository.find_student(database_path, enrollment)
    if not student:
        raise ServiceError("Estudante não encontrado.", 404)
    if not validate_signature(signature):
        raise ServiceError("A assinatura está inválida ou vazia.", 400)
    if action == "checkout" and (
        not isinstance(enrollment_confirmation, str)
        or enrollment_confirmation.strip() != enrollment
    ):
        raise ServiceError(
            "A matrícula informada não corresponde ao estudante selecionado.",
            400,
        )
    result = repository.record_signature(
        database_path,
        enrollment,
        book_id,
        action,
        signature,
        now_iso(),
        server_email,
        school_year,
    )
    errors = {
        "book_not_found": ("Livro não encontrado para este estudante.", 404),
        "checkout_required": ("O servidor só pode registrar a devolução de um livro já entregue.", 409),
        "already_checked_out": ("A assinatura de entrega deste título já foi registrada.", 409),
        "already_returned": ("A devolução deste título já foi registrada.", 409),
        "wrong_school_year": ("A entrega deste título pertence a outro ano letivo.", 409),
    }
    if result:
        message, status = errors[result]
        raise ServiceError(message, status)
    return repository.find_student(database_path, enrollment, school_year) or repository.find_student(
        database_path, enrollment
    )


def sign_books(
    database_path,
    enrollment,
    book_ids,
    signature,
    server_email,
    school_year,
    enrollment_confirmation,
):
    if not isinstance(book_ids, list) or not 1 <= len(book_ids) <= 30:
        raise ServiceError("Selecione pelo menos um livro para registrar a entrega.", 400)
    if any(not isinstance(book_id, str) or not book_id for book_id in book_ids):
        raise ServiceError("A seleção de livros é inválida.", 400)
    if len(set(book_ids)) != len(book_ids):
        raise ServiceError("A seleção contém livros repetidos.", 400)
    student = repository.find_student(database_path, enrollment, school_year)
    if not student or student["status"] != "active" or student["is_archived"]:
        raise ServiceError("Não é possível registrar uma entrega fora do ciclo letivo ativo.", 409)
    if (
        not isinstance(enrollment_confirmation, str)
        or enrollment_confirmation.strip() != enrollment
    ):
        raise ServiceError(
            "A matrícula informada não corresponde ao estudante selecionado.",
            400,
        )
    if not validate_signature(signature):
        raise ServiceError("A assinatura está inválida ou vazia.", 400)
    result = repository.record_signatures(
        database_path,
        enrollment,
        book_ids,
        signature,
        now_iso(),
        server_email,
        school_year,
    )
    errors = {
        "book_not_found": "Um dos livros selecionados não pertence ao termo deste estudante.",
        "wrong_school_year": "Um dos livros selecionados não pode ser entregue neste ano letivo.",
        "already_checked_out": "Um dos livros selecionados já foi entregue.",
    }
    if result:
        error, _book_id = result
        raise ServiceError(errors[error], 409 if error != "book_not_found" else 404)
    return repository.find_student(database_path, enrollment, school_year)
