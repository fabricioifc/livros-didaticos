import base64
import binascii
import os
import re
import struct
import zlib
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
    return len(decoded) <= 1_000_000 and _signature_png_has_ink(decoded)


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_SIGNATURE_MIN_SIDE = 20
_SIGNATURE_MAX_PIXELS = 4_000_000
# Bytes não nulos mínimos nos pixels: um traço curto já passa de algumas centenas.
_SIGNATURE_MIN_INK = 64


def _signature_png_has_ink(data):
    """Confere se é um PNG RGBA íntegro, como o gerado pelo canvas, e não está em branco.

    O canvas parte de pixels transparentes (todos os bytes zero). Os filtros
    do PNG mantêm zeros em áreas vazias, então basta contar bytes não nulos
    nos dados descomprimidos, sem reconstruir a imagem.
    """
    if not data.startswith(_PNG_HEADER):
        return False
    position = len(_PNG_HEADER)
    header = None
    compressed = []
    ended = False
    while position + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        chunk = data[position + 8:position + 8 + length]
        crc_end = position + 12 + length
        if len(chunk) != length or crc_end > len(data):
            return False
        (crc,) = struct.unpack(">I", data[crc_end - 4:crc_end])
        if zlib.crc32(kind + chunk) != crc:
            return False
        if header is None and kind != b"IHDR":
            return False
        if kind == b"IHDR":
            header = chunk
        elif kind == b"IDAT":
            compressed.append(chunk)
        elif kind == b"IEND":
            ended = True
            break
        position = crc_end
    if not header or len(header) != 13 or not compressed or not ended:
        return False
    width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if (
        bit_depth != 8 or color_type != 6 or interlace != 0
        or min(width, height) < _SIGNATURE_MIN_SIDE
        or width * height > _SIGNATURE_MAX_PIXELS
    ):
        return False
    stride = width * 4 + 1
    expected = stride * height
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(b"".join(compressed), expected + 1)
    except zlib.error:
        return False
    if len(pixels) != expected or decompressor.unconsumed_tail:
        return False
    filters = pixels[::stride]
    if any(value > 4 for value in filters):
        return False
    ink = len(pixels) - pixels.count(0) - (height - filters.count(0))
    return ink >= _SIGNATURE_MIN_INK
