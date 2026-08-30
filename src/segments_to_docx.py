"""Macht aus den Whisper-Segmenten ein Word-Dokument mit Zeitmarken.

Aufeinanderfolgende Segmente werden zu Absätzen zusammengefasst; ein neuer
Absatz beginnt bei einer längeren Sprechpause oder wenn der Absatz zu lang wird.
"""

import json
import os
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor


def stamp(seconds):
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def group(segments, gap=2.0, max_chars=700):
    """Segmente zu Absätzen bündeln: (startzeit, text)."""
    blocks, buf, start, prev_end = [], "", None, 0.0
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        pause = start is not None and seg["start"] - prev_end > gap
        if buf and (pause or len(buf) > max_chars):
            blocks.append((start, buf.strip()))
            buf, start = "", None
        if start is None:
            start = seg["start"]
        buf = f"{buf} {text}".strip()
        prev_end = seg["end"]
    if buf:
        blocks.append((start, buf.strip()))
    return blocks


def build(seg_json, out_path, source_name):
    segments = json.load(open(seg_json, encoding="utf-8"))
    blocks = group(segments)

    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)

    doc.add_heading("Transkript", level=0)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for line in [
        f"Quelle: {source_name}",
        f"Länge: {stamp(segments[-1]['end'])}",
        "Automatisch erstellt mit Whisper large-v3, ohne Sprechertrennung.",
        "Der Text ist maschinell erzeugt und nicht korrekturgelesen; "
        "Namen und Fachbegriffe können falsch erkannt sein.",
    ]:
        run = meta.add_run(line + "\n")
        run.italic = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    doc.add_paragraph()

    for start, text in blocks:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(10)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        mark = p.add_run(f"[{stamp(start)}]  ")
        mark.bold = True
        mark.font.size = Pt(9)
        p.add_run(text)

    doc.save(out_path)
    words = sum(len(t.split()) for _, t in blocks)
    print(f"{out_path}: {len(blocks)} Absätze, rund {words} Wörter, "
          f"Länge {stamp(segments[-1]['end'])}")


if __name__ == "__main__":
    seg_json, out_path = sys.argv[1:3]
    source = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(seg_json)
    build(seg_json, out_path, source)
