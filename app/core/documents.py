from __future__ import annotations

import re
from datetime import datetime
from html import escape, unescape
from io import BytesIO

from bs4 import BeautifulSoup, NavigableString, Tag

from app.db.models import DigestHistory


def _plain_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a"):
        href = link.get("href")
        if href:
            link.string = f"{link.get_text(strip=True)} ({href})"
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return unescape(text).strip()


def _document_title(digest: DigestHistory) -> str:
    created = digest.created_at.strftime("%d.%m.%Y %H:%M") if isinstance(digest.created_at, datetime) else ""
    return f"ИнфоПульс: дайджест {digest.period} от {created}".strip()


def build_digest_docx(digest: DigestHistory) -> bytes:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import RGBColor

    document = Document()
    document.add_heading(_document_title(digest), level=1)
    document.add_paragraph(f"Период: {digest.period}")
    document.add_paragraph(f"Режим: {digest.source_mode}")
    document.add_paragraph("")

    soup = BeautifulSoup(digest.digest_text, "html.parser")

    def add_node(paragraph, node) -> None:
        if isinstance(node, NavigableString):
            paragraph.add_run(str(node))
            return
        if not isinstance(node, Tag):
            return

        if node.name == "br":
            paragraph.add_run().add_break(WD_BREAK.LINE)
            return

        if node.name == "a":
            href = node.get("href", "")
            text = node.get_text(strip=True) or href
            run = paragraph.add_run(text)
            run.font.color.rgb = RGBColor(5, 99, 193)
            run.underline = True
            if href:
                paragraph.add_run(f" ({href})")
            return

        run = paragraph.add_run()
        if node.name == "b":
            run.bold = True
        elif node.name == "i":
            run.italic = True
        run.text = node.get_text()

    for child in soup.children:
        if isinstance(child, NavigableString) and not str(child).strip():
            continue
        style = "Intense Quote" if isinstance(child, Tag) and child.name == "blockquote" else None
        paragraph = document.add_paragraph(style=style)
        add_node(paragraph, child)

    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def build_digest_pdf(digest: DigestHistory) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    stream = BytesIO()
    font_name = "Helvetica"
    for font_path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            pdfmetrics.registerFont(TTFont("DigestSans", font_path))
            font_name = "DigestSans"
            break
        except Exception:
            continue

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("DigestNormal", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=14)
    title = ParagraphStyle("DigestTitle", parent=styles["Title"], fontName=font_name, fontSize=16, leading=20)
    quote = ParagraphStyle(
        "DigestQuote",
        parent=normal,
        leftIndent=12,
        borderColor=colors.lightgrey,
        borderWidth=1,
        borderPadding=8,
        backColor=colors.whitesmoke,
    )

    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story = [Paragraph(_document_title(digest), title), Spacer(1, 8)]
    story.append(Paragraph(f"Период: {digest.period}<br/>Режим: {digest.source_mode}", normal))
    story.append(Spacer(1, 12))

    soup = BeautifulSoup(digest.digest_text, "html.parser")

    def add_pdf_text(text: str, style=normal) -> None:
        for line in text.splitlines():
            line = line.strip()
            if line:
                story.append(Paragraph(line, style))
            else:
                story.append(Spacer(1, 6))

    for child in soup.children:
        if isinstance(child, NavigableString):
            add_pdf_text(escape(str(child)))
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "blockquote":
            add_pdf_text(escape(child.get_text(" ", strip=True)), quote)
        else:
            add_pdf_text(str(child), normal)

    doc.build(story)
    return stream.getvalue()
