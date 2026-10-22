import base64
import binascii
import os
import re
from datetime import datetime, timezone


SCHOOL_YEAR = int(os.environ.get("SCHOOL_YEAR") or datetime.now().year)
GRADES = {"1º", "2º", "3º"}
SHARED_BOOKS = [
    ("redacao", "360° Redação"),
    ("arte", "360° Arte"),
    ("ingles", "Ways — English for Life — Inglês"),
    ("espanhol", "¡Sí, se puede! — Espanhol"),
    ("educacao-fisica", "360° Educação Física"),
    ("educacao-digital", "360° Educação Digital"),
    ("filosofia", "Filosofia por toda parte"),
    ("sociologia", "Sociologia por toda parte"),
    ("historia", "História por toda parte"),
    ("geografia", "Geografia por toda parte"),
    ("quimica", "Identidade Saraiva — Química"),
    ("fisica", "Identidade Saraiva — Física"),
    ("biologia", "Identidade Saraiva — Biologia"),
]
_SIGNATURE_DATA = re.compile(r"^data:image/png;base64,([A-Za-z0-9+/]*={0,2})$")


def book_list(grade, school_year=SCHOOL_YEAR):
    year_number = grade[0]
    return [
        {
            "id": f"portugues-{school_year}-{year_number}",
            "title": f"360° Língua Portuguesa — {grade} ano",
        },
        *({"id": book_id, "title": title} for book_id, title in SHARED_BOOKS),
        {
            "id": f"matematica-{school_year}-{year_number}",
            "title": f"Do seu jeito — Matemática — Volume {year_number}",
        },
    ]


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
