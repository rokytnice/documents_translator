"""Baut aus den deutschen SRT-Untertiteln dasselbe Buch als PDF.

Nutzt dieselbe Aufbereitung wie src/srt_to_docx.py (Timecodes und Nummern raus,
Fragmente zu Absätzen zusammengefügt), setzt das Ergebnis aber mit ReportLab.
"""

import os
import re
import sys

from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from srt_to_docx import cues, paragraphs, TITLES, ORDER, SPEAKER  # noqa: E402

BODY = ParagraphStyle(
    "body", fontName="Times-Roman", fontSize=10.5, leading=15,
    alignment=TA_JUSTIFY, spaceAfter=5,
)
H1 = ParagraphStyle(
    "h1", fontName="Times-Bold", fontSize=17, leading=21,
    spaceBefore=0, spaceAfter=14,
)
TITLE = ParagraphStyle(
    "title", fontName="Times-Bold", fontSize=26, leading=32,
    alignment=TA_CENTER, spaceAfter=10,
)
SUBTITLE = ParagraphStyle(
    "subtitle", fontName="Times-Italic", fontSize=13, leading=18,
    alignment=TA_CENTER, spaceAfter=26,
)
NOTE = ParagraphStyle(
    "note", fontName="Times-Italic", fontSize=8.5, leading=12,
    alignment=TA_CENTER,
)
TOC = ParagraphStyle(
    "toc", fontName="Times-Roman", fontSize=11, leading=17,
)


def clean(text):
    """XML-Sonderzeichen escapen, Zeichen ohne Glyphe in Times ersetzen."""
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    text = text.replace("♪", "").replace("⏎", " ")
    return re.sub(r"\s+", " ", text).strip()


def body_paragraph(text):
    """Absatz setzen; ein führendes [Name] wird zum fetten Sprechernamen."""
    m = SPEAKER.match(text)
    if m:
        rest = clean(text[m.end():])
        return Paragraph(f"<b>{clean(m.group(1))}:</b> {rest}", BODY)
    return Paragraph(SPEAKER.sub(r"\1: ", clean(text)), BODY)


def footer(canvas, doc):
    """Seitenzahl unten mittig, ab der zweiten Seite."""
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont("Times-Roman", 9)
    canvas.drawCentredString(A5[0] / 2, 12 * mm, str(doc.page))
    canvas.restoreState()


def build(srt_dir, out_path):
    chapters = []
    for key in ORDER:
        path = os.path.join(srt_dir, f"{key}-de.srt")
        if not os.path.exists(path):
            print(f"fehlt: {path}", file=sys.stderr)
            continue
        paras = paragraphs(cues(path))
        if paras:
            chapters.append((TITLES[key], paras))

    doc = BaseDocTemplate(
        out_path, pagesize=A5,
        leftMargin=18 * mm, rightMargin=16 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="Milos Zauberschule", author="Deutsche Fassung der Kursuntertitel",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="text",
    )
    doc.addPageTemplates(PageTemplate(id="all", frames=[frame], onPage=footer))

    story = [
        Spacer(1, 45 * mm),
        Paragraph("Milos Zauberschule", TITLE),
        Paragraph("Gedanken lesen — die Tricks und ihre Methoden", SUBTITLE),
        Paragraph(
            "Deutsche Fassung der Kursuntertitel, zu einem durchgehenden Text "
            "zusammengefügt. Zeitangaben, Untertitelnummern sowie reine Musik- "
            "und Geräuschhinweise sind entfernt.", NOTE,
        ),
        PageBreak(),
        Paragraph("Inhalt", H1),
    ]
    for i, (title, _) in enumerate(chapters, 1):
        story.append(Paragraph(f"{i}.&nbsp;&nbsp;{clean(title)}", TOC))
    story.append(PageBreak())

    for title, paras in chapters:
        story.append(Paragraph(clean(title), H1))
        story.extend(body_paragraph(p) for p in paras)
        story.append(PageBreak())

    doc.build(story)
    print(f"{out_path}: {len(chapters)} Kapitel")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
