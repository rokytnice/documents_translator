"""Bebilderte Fassung des Buches: DOCX und PDF mit Standbildern aus den Videos.

Die Bilder stammen aus src/extract_frames.sh, die Stellen aus
src/srt_pick_frames.py. Ein Bild wird hinter dem Absatz gesetzt, in dem der
zugehörige Untertitel steht.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from srt_pick_frames import parse  # noqa: E402
from srt_to_docx import SOUND_ONLY, SPEAKER, TITLES, ORDER  # noqa: E402


def blocks(path):
    """Cues ohne reine Ton-/Musikhinweise, mit Original-Index."""
    out = []
    for i, start, end, text in parse(path):
        text = re.sub(r"\s+", " ", text).strip()
        if text and not SOUND_ONLY.match(text):
            out.append((i, text))
    return out


def paragraphs_with_cues(chunks, max_len=450):
    """Wie srt_to_docx.paragraphs, merkt sich aber die enthaltenen Cue-Indizes."""
    paras, buf, first, last = [], "", None, None
    for idx, chunk in chunks:
        new_turn = chunk.startswith("- ")
        piece = chunk[2:].strip() if new_turn else chunk
        if (new_turn and buf) or (
            buf and len(buf) > max_len and re.search(r"[.!?…]$", buf)
        ):
            paras.append((buf.strip(), first, last))
            buf, first = "", None
        if first is None:
            first = idx
        last = idx
        buf = f"{buf} {piece}".strip() if buf else piece
    if buf.strip():
        paras.append((buf.strip(), first, last))
    return [(re.sub(r"\s+", " ", t), a, b) for t, a, b in paras if t.strip()]


def caption(text, limit=95):
    """Kurze Bildunterschrift aus dem Untertitel an dieser Stelle."""
    text = re.sub(r"^-\s*", "", re.sub(r"\[[^\]]{1,20}\]\s*", "", text)).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut + " …"
    return text


def chapters(srt_dir, plan_path, img_dir):
    """[(Titel, [(Absatz, cue_von, cue_bis)], {cue_index: (bildpfad, unterschrift)})]"""
    plan = json.load(open(plan_path, encoding="utf-8"))
    out = []
    for key in ORDER:
        srt = os.path.join(srt_dir, f"{key}-de.srt")
        if not os.path.exists(srt):
            continue
        paras = paragraphs_with_cues(blocks(srt))
        if not paras:
            continue
        images = {}
        for n, pick in enumerate(plan.get(key, []), 1):
            path = os.path.join(img_dir, f"{key}_{n:02d}.jpg")
            if os.path.exists(path):
                images[pick["cue"]] = (path, caption(pick["text"]))
        out.append((TITLES[key], paras, images))
    return out


def place(paras, images):
    """Ordnet jedes Bild dem Absatz zu, in dem sein Untertitel steht."""
    slots = {}
    for cue, item in sorted(images.items()):
        target = len(paras) - 1
        for i, (_, a, b) in enumerate(paras):
            if a is not None and a <= cue <= b:
                target = i
                break
            if a is not None and a > cue:
                target = max(0, i - 1)
                break
        slots.setdefault(target, []).append(item)
    return slots


# ---------------------------------------------------------------- DOCX

def build_docx(data, out_path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm

    doc = Document()
    doc.styles["Normal"].font.name = "Georgia"
    doc.styles["Normal"].font.size = Pt(11)

    doc.add_heading("Milos Zauberschule", level=0)
    for text, style, size, italic in [
        ("Gedanken lesen — die Tricks und ihre Methoden", None, 13, False),
        ("Deutsche Fassung der Kursuntertitel mit Standbildern aus den Videos. "
         "Zeitangaben, Untertitelnummern sowie reine Musik- und Geräuschhinweise "
         "sind entfernt.", None, 9, True),
    ]:
        p = doc.add_paragraph(text)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.italic = italic
            run.font.size = Pt(size)

    doc.add_page_break()
    doc.add_heading("Inhalt", level=1)
    for i, (title, _, _) in enumerate(data, 1):
        doc.add_paragraph(f"{i}. {title}")
    doc.add_page_break()

    fig = 0
    for title, paras, images in data:
        doc.add_heading(title, level=1)
        slots = place(paras, images)
        for i, (text, _, _) in enumerate(paras):
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            m = SPEAKER.match(text)
            if m:
                run = p.add_run(f"{m.group(1)}: ")
                run.bold = True
                text = text[m.end():]
            p.add_run(SPEAKER.sub(r"\1: ", text))
            for path, cap in slots.get(i, []):
                fig += 1
                pic = doc.add_paragraph()
                pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pic.paragraph_format.space_before = Pt(8)
                pic.add_run().add_picture(path, width=Cm(13))
                c = doc.add_paragraph(f"Abb. {fig} — {cap}")
                c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                c.paragraph_format.space_after = Pt(12)
                for run in c.runs:
                    run.italic = True
                    run.font.size = Pt(8.5)
        doc.add_page_break()
    doc.save(out_path)
    return fig


# ---------------------------------------------------------------- PDF

def build_pdf(data, out_path):
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak,
        Image, KeepTogether,
    )
    from srt_to_pdf import BODY, H1, TITLE, SUBTITLE, NOTE, TOC, clean, footer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from PIL import Image as PILImage

    CAP = ParagraphStyle(
        "cap", fontName="Times-Italic", fontSize=8, leading=11,
        alignment=TA_CENTER, spaceBefore=3, spaceAfter=10,
    )
    max_w = A5[0] - 34 * mm

    def figure(path, cap, number):
        w, h = PILImage.open(path).size
        width = min(max_w, 105 * mm)
        img = Image(path, width=width, height=width * h / w)
        return KeepTogether([
            Spacer(1, 4 * mm), img,
            Paragraph(f"Abb. {number} — {clean(cap)}", CAP),
        ])

    doc = BaseDocTemplate(
        out_path, pagesize=A5,
        leftMargin=18 * mm, rightMargin=16 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="Milos Zauberschule (bebildert)",
        author="Deutsche Fassung der Kursuntertitel",
    )
    doc.addPageTemplates(PageTemplate(
        id="all",
        frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)],
        onPage=footer,
    ))

    story = [
        Spacer(1, 45 * mm),
        Paragraph("Milos Zauberschule", TITLE),
        Paragraph("Gedanken lesen — die Tricks und ihre Methoden", SUBTITLE),
        Paragraph(
            "Deutsche Fassung der Kursuntertitel mit Standbildern aus den "
            "Videos. Zeitangaben, Untertitelnummern sowie reine Musik- und "
            "Geräuschhinweise sind entfernt.", NOTE,
        ),
        PageBreak(),
        Paragraph("Inhalt", H1),
    ]
    for i, (title, _, _) in enumerate(data, 1):
        story.append(Paragraph(f"{i}.&nbsp;&nbsp;{clean(title)}", TOC))
    story.append(PageBreak())

    fig = 0
    for title, paras, images in data:
        story.append(Paragraph(clean(title), H1))
        slots = place(paras, images)
        for i, (text, _, _) in enumerate(paras):
            m = SPEAKER.match(text)
            if m:
                story.append(Paragraph(
                    f"<b>{clean(m.group(1))}:</b> {clean(text[m.end():])}", BODY))
            else:
                story.append(Paragraph(SPEAKER.sub(r"\1: ", clean(text)), BODY))
            for path, cap in slots.get(i, []):
                fig += 1
                story.append(figure(path, cap, fig))
        story.append(PageBreak())

    doc.build(story)
    return fig


if __name__ == "__main__":
    srt_dir, plan, img_dir, out_docx, out_pdf = sys.argv[1:6]
    data = chapters(srt_dir, plan, img_dir)
    n = build_docx(data, out_docx)
    print(f"{out_docx}: {len(data)} Kapitel, {n} Abbildungen")
    n = build_pdf(data, out_pdf)
    print(f"{out_pdf}: {len(data)} Kapitel, {n} Abbildungen")
