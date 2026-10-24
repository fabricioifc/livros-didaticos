import base64
import binascii
import os
import re
from datetime import datetime, timezone


SCHOOL_YEAR = int(os.environ.get("SCHOOL_YEAR") or datetime.now().year)
GRADES = {"1º", "2º", "3º"}
# Catálogo inicial. "grade" None indica volume único: o mesmo exemplar
# acompanha o estudante nos três anos até a devolução. Os códigos mantêm os
# identificadores usados antes do cadastro de livros.
DEFAULT_CATALOG = [
    ("portugues", "360° Língua Portuguesa — 1º ano", "1º"),
    ("portugues", "360° Língua Portuguesa — 2º ano", "2º"),
    ("portugues", "360° Língua Portuguesa — 3º ano", "3º"),
    ("redacao", "360° Redação", None),
    ("arte", "360° Arte", None),
    ("ingles", "Ways — English for Life — Inglês", None),
    ("espanhol", "¡Sí, se puede! — Espanhol", None),
    ("educacao-fisica", "360° Educação Física", None),
    ("educacao-digital", "360° Educação Digital", None),
    ("filosofia", "Filosofia por toda parte", None),
    ("sociologia", "Sociologia por toda parte", None),
    ("historia", "História por toda parte", None),
    ("geografia", "Geografia por toda parte", None),
    ("quimica", "Identidade Saraiva — Química", None),
    ("fisica", "Identidade Saraiva — Física", None),
    ("biologia", "Identidade Saraiva — Biologia", None),
    ("matematica", "Do seu jeito — Matemática — Volume 1", "1º"),
    ("matematica", "Do seu jeito — Matemática — Volume 2", "2º"),
    ("matematica", "Do seu jeito — Matemática — Volume 3", "3º"),
]
_SIGNATURE_DATA = re.compile(r"^data:image/png;base64,([A-Za-z0-9+/]*={0,2})$")


def catalog_book_key(book, school_year):
    """Identificador do livro no termo do estudante.

    Volume único usa sempre o mesmo identificador, para que o empréstimo
    atravesse os ciclos; livro de ano específico ganha um por ciclo.
    """
    base = book["code"] or f"livro-{book['id']}"
    if book["grade"] is None:
        return base
    return f"{base}-{school_year}-{book['grade'][0]}"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(value):
    return value.strip().lower() if isinstance(value, str) else ""


def is_ifc_email(email):
    return len(email) <= 254 and re.fullmatch(r"[^@\s]+@ifc\.edu\.br", email) is not None


def validate_signature(data):
    if not isinstance(data, str) or len(data) > 1_400_000:
        return False
    match = _SIGNATURE_DATA.fullmatch(data)
    if not match:
        return False
    try:
        decoded = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError):
        return False
    return decoded.startswith(b"\x89PNG\r\n\x1a\n") and len(decoded) <= 1_000_000
