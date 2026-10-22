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


def create_user(database_path, email, password):
    email = normalize_email(email)
    if not is_ifc_email(email):
        raise ValueError("Use um e-mail @ifc.edu.br.")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
        raise ValueError("A senha precisa ter entre 12 e 128 caracteres.")
    repository.add_user(database_path, email, generate_password_hash(password), now_iso())


def authenticate(database_path, email, password):
    email = normalize_email(email)
    if not is_ifc_email(email) or not isinstance(password, str):
        raise ServiceError("Informe um e-mail @ifc.edu.br e uma senha.", 400)
    user = repository.find_user(database_path, email)
    if not user or not check_password_hash(user["password_hash"], password):
        raise ServiceError("E-mail ou senha incorretos.", 401)
    return user


def get_students(database_path, query, school_year):
    return repository.list_students(database_path, query.strip()[:100], school_year)


def get_student(database_path, enrollment, school_year=None):
    return repository.find_student(database_path, enrollment, school_year)


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


def sign_book(database_path, enrollment, book_id, action, signature, server_email, school_year):
    if action not in {"checkout", "return"}:
        raise ServiceError("Operação inválida.", 400)
    if not repository.find_student(database_path, enrollment, school_year):
        raise ServiceError("Estudante não encontrado.", 404)
    if not validate_signature(signature):
        raise ServiceError("A assinatura está inválida ou vazia.", 400)
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
    return repository.find_student(database_path, enrollment, school_year)
