"""Baut aus deutschen SRT-Untertiteln ein lesbares Buch als DOCX.

Blocknummern und Timecodes fallen weg, reine Ton-/Musikhinweise ebenfalls.
Die Untertitel-Fragmente werden zu Absätzen zusammengefügt: ein neuer Absatz
beginnt, wo im Untertitel ein Sprecherwechsel ("- ") steht.
"""

import os
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Cm

TIME = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
# Cues, die nur aus einem Ton-/Musikhinweis bestehen: (ruhige Musik), ♪ (Musik) ♪
SOUND_ONLY = re.compile(r"^[♪\s]*\((?:[^()]*)\)[♪\s]*$")
SPEAKER = re.compile(r"^\[([^\]]{1,20})\]\s*")

# Kapitelüberschriften: Dateiname -> Titel im Buch
TITLES = {
    "00 - Introduction": "Einführung",
    "01 - The Billets": "Die Billets",
    "02 - Reading The Markings": "Die Markierungen lesen",
    "03 - The Marked Deck": "Das markierte Kartenspiel",
    "04 - The Switch Pad": "Der Wechselblock",
    "05 - The Envelopes": "Die Umschläge",
    "06 - The Bank Card": "Die Bankkarte",
    "07 - The Whisper": "Das Flüstern",
    "08 - The Secret Writer": "Der geheime Schreiber",
    "09 - The Dsp": "Das DSP-Prinzip",
    "10 - The Life Equation": "Die Lebensgleichung",
    "11 - The Predictions": "Die Vorhersagen",
    "12 - Peek Wallet": "Das Peek Wallet",
    "13 - The Esp Cards": "Die ESP-Karten",
    "14 - The Book": "Der Buchtest",
    "15 - The Readings": "Die Readings",
    "16 - The Spoon Bend": "Das Löffelbiegen",
    "17 - The UV Set": "Das UV-Set",
    "18 - The Phone Unlock": "Das Handy entsperren",
    "19 - The Performances": "Die Vorführungen",
    "20 - Htrm Refills": "Nachfüllmaterial",
    "The 1089 Force": "Die 1089-Force",
}

ORDER = list(TITLES)


def cues(path):
    """Liefert die Textblöcke einer SRT ohne Nummern und Timecodes."""
    txt = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", txt):
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        if len(lines) >= 2 and TIME.match(lines[1]):
            body = lines[2:]
        elif TIME.match(lines[0]):
            body = lines[1:]
        else:
            continue
        text = " ".join(s.strip() for s in body).strip()
        if text and not SOUND_ONLY.match(text):
            out.append(text)
    return out


def paragraphs(chunks, max_len=450):
    """Fügt Untertitel-Fragmente zu Absätzen zusammen (Absatz je Sprecherwechsel)."""
    paras, buf = [], ""
    for chunk in chunks:
        new_turn = chunk.startswith("- ")
        piece = chunk[2:].strip() if new_turn else chunk
        if new_turn and buf:
            paras.append(buf.strip())
            buf = ""
        if buf and len(buf) > max_len and re.search(r"[.!?…]$", buf):
            paras.append(buf.strip())
            buf = ""
        buf = f"{buf} {piece}".strip() if buf else piece
    if buf.strip():
        paras.append(buf.strip())
    return [re.sub(r"\s+", " ", p) for p in paras if p.strip()]


def add_paragraph(doc, text):
    """Setzt einen Absatz; ein führendes [Name] wird zum fetten Sprechernamen."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.first_line_indent = Cm(0)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    m = SPEAKER.match(text)
    if m:
        run = p.add_run(f"{m.group(1)}: ")
        run.bold = True
        text = text[m.end():]
    # weitere [Name]-Marker im Fließtext entfernen
    text = SPEAKER.sub(r"\1: ", text)
    p.add_run(text)
    return p


def build(srt_dir, out_path):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(11)

    doc.add_heading("Milos Zauberschule", level=0)
    sub = doc.add_paragraph("Gedanken lesen — die Tricks und ihre Methoden")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note = doc.add_paragraph(
        "Deutsche Fassung der Kursuntertitel, zu einem durchgehenden Text "
        "zusammengefügt. Zeitangaben, Untertitelnummern sowie reine Musik- und "
        "Geräuschhinweise sind entfernt."
    )
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in note.runs:
        run.italic = True
        run.font.size = Pt(9)

    # Kapitel einlesen; leere Kapitel (nur Musikhinweise) fallen weg
    chapters = []
    for key in ORDER:
        path = os.path.join(srt_dir, f"{key}-de.srt")
        if not os.path.exists(path):
            print(f"fehlt: {path}", file=sys.stderr)
            continue
        chunks = cues(path)
        paras = paragraphs(chunks)
        if paras:
            chapters.append((TITLES[key], chunks, paras))

    doc.add_page_break()
    doc.add_heading("Inhalt", level=1)
    stats = []
    for i, (title, _, _) in enumerate(chapters, 1):
        doc.add_paragraph(f"{i}. {title}")

    doc.add_page_break()

    for title, chunks, paras in chapters:
        doc.add_heading(title, level=1)
        for para in paras:
            add_paragraph(doc, para)
        doc.add_page_break()
        stats.append((title, len(chunks), len(paras)))

    doc.save(out_path)
    words = sum(len(p.text.split()) for p in doc.paragraphs)
    for title, c, p in stats:
        print(f"{title:35s} {c:5d} Untertitel -> {p:4d} Absätze")
    print(f"\n{out_path}: {len(stats)} Kapitel, rund {words} Wörter")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
