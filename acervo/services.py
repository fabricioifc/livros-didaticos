import csv
import io
import re
import sqlite3
import unicodedata

from werkzeug.security import check_password_hash, generate_password_hash

from . import repository
from .models import GRADES, is_ifc_email, normalize_email, now_iso, validate_signature


class ServiceError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def create_user(database_path, email, password, is_admin=False):
    email = normalize_email(email)
    if not is_ifc_email(email):
        raise ValueError("Use um e-mail @ifc.edu.br.")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
        raise ValueError("A senha precisa ter entre 12 e 128 caracteres.")
    repository.add_user(
        database_path, email, generate_password_hash(password), now_iso(), is_admin
    )


def authenticate(database_path, email, password):
    email = normalize_email(email)
    if not is_ifc_email(email) or not isinstance(password, str):
        raise ServiceError("Informe um e-mail @ifc.edu.br e uma senha.", 400)
    user = repository.find_user(database_path, email)
    if (
        not user
        or not user["is_active"]
        or not check_password_hash(user["password_hash"], password)
    ):
        raise ServiceError("E-mail ou senha incorretos.", 401)
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


def update_school_year(database_path, value, current_year):
    if isinstance(value, bool) or not isinstance(value, int) or not 1900 <= value <= 2100:
        raise ServiceError("Informe um ano letivo válido entre 1900 e 2100.", 400)
    if value < current_year:
        raise ServiceError(
            "Não é possível voltar para um ano anterior, pois os ciclos letivos e "
            "arquivamentos já criados não podem ser desfeitos.",
            409,
        )
    try:
        result = repository.update_school_year(database_path, value)
    except ValueError as error:
        raise ServiceError(str(error), 409) from error
    if result == "cannot_decrease":
        raise ServiceError(
            "O ano letivo já foi atualizado por outra solicitação. Atualize a página.",
            409,
        )
    return value


def create_student(database_path, body, school_year):
    name = body.get("name")
    enrollment = body.get("enrollment")
    grade = body.get("grade")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        raise ServiceError("Informe o nome do estudante (até 150 caracteres).", 400)
    if not isinstance(enrollment, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,30}", enrollment.strip()):
        raise ServiceError("Informe uma matrícula válida (até 30 letras, números ou hífens).", 400)
    if grade not in GRADES:
        raise ServiceError("Selecione o 1º, 2º ou 3º ano.", 400)
    enrollment = enrollment.strip()
    try:
        repository.add_student(
            database_path, enrollment, name.strip(), grade, now_iso(), school_year
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
        required = {"matricula", "nome", "turma"}
        if not required.issubset(normalized_headers):
            raise ServiceError(
                "O CSV precisa ter cabeçalhos para matrícula, nome e turma.",
                400,
            )

        valid_students = []
        invalid_rows = []
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not (value or "").strip() for value in row.values() if isinstance(value, str)):
                continue
            enrollment = (row.get(normalized_headers["matricula"]) or "").strip()
            name = (row.get(normalized_headers["nome"]) or "").strip()
            grade_value = (row.get(normalized_headers["turma"]) or "").strip()
            grade = _normalize_grade(grade_value)

            if not re.fullmatch(r"[A-Za-z0-9-]{1,30}", enrollment):
                invalid_rows.append({"line": line_number, "reason": "matrícula inválida"})
            elif not name or len(name) > 150:
                invalid_rows.append({"line": line_number, "reason": "nome ausente ou maior que 150 caracteres"})
            elif not grade:
                invalid_rows.append({"line": line_number, "reason": "turma deve ser 1º, 2º ou 3º"})
            else:
                valid_students.append(
                    {
                        "enrollment": enrollment,
                        "name": name,
                        "grade": grade,
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
    if not repository.update_student(database_path, enrollment, name.strip(), grade, school_year):
        raise ServiceError("Estudante não encontrado.", 404)
    return repository.find_student(database_path, enrollment, school_year)


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
    if action == "checkout" and (not student or student["status"] != "active"):
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
    if not student or student["status"] != "active":
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
