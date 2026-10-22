"""Geração do termo de compromisso em PDF (mesmo conteúdo da impressão em print.js)."""
import base64
import io
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Horário de Brasília (sem horário de verão desde 2019).
LOCAL_TIMEZONE = timezone(timedelta(hours=-3))

TERM_RULES = [
    "Em caso de desistência do curso ou transferência para outra instituição, os livros "
    "deverão ser devolvidos para a liberação da transferência e/ou formalização da desistência.",
    "Em caso de perda, roubo ou dano aos livros didáticos, não haverá reposição destes itens "
    "ao(à) estudante.",
]

_INK = colors.HexColor("#1f2922")
_STYLES = {
    "header": ParagraphStyle("header", fontName="Helvetica", fontSize=8, leading=11, textColor=_INK),
    "title": ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=14, leading=18,
        alignment=TA_CENTER, spaceBefore=8 * mm, spaceAfter=5 * mm, textColor=_INK,
    ),
    "body": ParagraphStyle(
        "body", fontName="Times-Roman", fontSize=9.5, leading=14,
        alignment=TA_JUSTIFY, textColor=_INK,
    ),
    "subtitle": ParagraphStyle(
        "subtitle", fontName="Helvetica-Bold", fontSize=10, leading=13,
        spaceBefore=6 * mm, spaceAfter=2 * mm, textColor=_INK,
    ),
    "rule": ParagraphStyle(
        "rule", fontName="Times-Roman", fontSize=9.5, leading=13,
        leftIndent=6 * mm, bulletIndent=1 * mm, spaceAfter=2 * mm, textColor=_INK,
    ),
    "cell": ParagraphStyle("cell", fontName="Times-Roman", fontSize=8, leading=10, textColor=_INK),
    "head": ParagraphStyle(
        "head", fontName="Helvetica-Bold", fontSize=7, leading=9, alignment=TA_CENTER, textColor=_INK,
    ),
    "small": ParagraphStyle(
        "small", fontName="Helvetica", fontSize=6, leading=8, alignment=TA_CENTER, textColor=_INK,
    ),
    "blank": ParagraphStyle(
        "blank", fontName="Helvetica-Oblique", fontSize=7, leading=9,
        alignment=TA_CENTER, textColor=colors.HexColor("#888888"),
    ),
    "footer": ParagraphStyle("footer", fontName="Times-Roman", fontSize=7, leading=9, textColor=_INK),
}
_STYLES["header_right"] = ParagraphStyle("header_right", parent=_STYLES["header"], alignment=TA_RIGHT)
_STYLES["footer_right"] = ParagraphStyle("footer_right", parent=_STYLES["footer"], alignment=TA_RIGHT)


def format_date(value):
    if not value:
        return "—"
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    if moment.tzinfo:
        moment = moment.astimezone(LOCAL_TIMEZONE)
    return moment.strftime("%d/%m/%Y")


def _text(value):
    return escape(str(value))


def _signature_cell(signature, signed_at):
    if not signature:
        return Paragraph("Pendente", _STYLES["blank"])
    signed_on = Paragraph(format_date(signed_at), _STYLES["small"])
    try:
        data = base64.b64decode(signature.split(",", 1)[1])
        image = Image(io.BytesIO(data), width=35 * mm, height=10 * mm, kind="proportional")
    except Exception:
        # Uma imagem ilegível não deve impedir a exportação dos demais termos.
        return [Paragraph("Assinado", _STYLES["small"]), signed_on]
    return [image, signed_on]


def build_term_pdf(student, issued_on=None):
    """Devolve o PDF (bytes) do termo do estudante no ano letivo de `student`."""
    issued_on = issued_on or datetime.now(LOCAL_TIMEZONE)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Termo de compromisso {student['school_year']} - {student['name']}",
        author="Acervo IFC · Campus Fraiburgo",
    )
    width = A4[0] - 30 * mm

    header = Table(
        [[
            Paragraph("<b>INSTITUTO FEDERAL CATARINENSE</b><br/>Campus Fraiburgo", _STYLES["header"]),
            Paragraph(f"TERMO DE COMPROMISSO · {student['school_year']}", _STYLES["header_right"]),
        ]],
        colWidths=[width * 0.6, width * 0.4],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#888888")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    declaration = (
        f"Eu, <b>{_text(student['name'])}</b>, matrícula <b>{_text(student['enrollment'])}</b>, "
        f"estudante da turma do <b>{_text(student['grade'])} ano</b> do curso "
        f"<b>{_text(student['course_name'])} ({_text(student['course_abbreviation'])})</b>, "
        "declaro que recebi os livros relacionados neste termo ao longo do curso e assumo a "
        "responsabilidade de devolvê-los em perfeito estado de conservação ao final do Ensino "
        "Médio, em caso de transferência para outra instituição ou de desistência do curso."
    )

    rows = [[
        Paragraph("Título do volume", _STYLES["head"]),
        Paragraph("Assinatura do estudante<br/>no empréstimo", _STYLES["head"]),
        Paragraph("Assinatura do servidor<br/>na devolução", _STYLES["head"]),
    ]]
    for book in sorted(student["books"], key=lambda item: item["title"].casefold()):
        rows.append([
            Paragraph(_text(book["title"]), _STYLES["cell"]),
            _signature_cell(book["checkout_signature"], book["checkout_at"]),
            _signature_cell(book["return_signature"], book["return_at"]),
        ])
    books = Table(rows, colWidths=[width * 0.39, width * 0.305, width * 0.305], repeatRows=1)
    books.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#aaaaaa")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))

    footer = Table(
        [[
            Paragraph(f"Fraiburgo, {format_date(issued_on)}", _STYLES["footer"]),
            Paragraph(
                "Rua Cruz e Souza, nº 100 · Centro · Fraiburgo/SC · (49) 3202-8800", _STYLES["footer_right"]
            ),
        ]],
        colWidths=[width * 0.4, width * 0.6],
    )
    footer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    document.build([
        header,
        Paragraph("TERMO DE COMPROMISSO COM OS LIVROS DIDÁTICOS", _STYLES["title"]),
        Paragraph(declaration, _STYLES["body"]),
        Paragraph("REGRAS DE UTILIZAÇÃO DOS LIVROS DIDÁTICOS (PNLD)", _STYLES["subtitle"]),
        *(
            Paragraph(_text(rule), _STYLES["rule"], bulletText=f"{index}.")
            for index, rule in enumerate(TERM_RULES, start=1)
        ),
        Spacer(1, 6 * mm),
        books,
        Spacer(1, 9 * mm),
        footer,
    ])
    return buffer.getvalue()
