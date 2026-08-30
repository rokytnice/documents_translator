"""Übersetzt SRT-Untertitel und lässt Nummern und Timecodes unangetastet.

Nur die Textzeilen einer Cue gehen an das Modell; Index und Zeitstempel werden
1:1 aus der Quelldatei übernommen. Die Cues werden in Batches als nummerierte
Zeilen übergeben, damit die Zuordnung Cue -> Übersetzung erhalten bleibt.

Der Modellzugriff läuft standardmäßig über die Claude Code CLI; mit
`--provider gemini` alternativ über die Gemini-API (dort gilt das
Tageskontingent des Free-Tiers).
"""

import argparse
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
MARKER = "@@"


def parse_srt(text):
    """Zerlegt SRT-Text in [(index_zeile, zeit_zeile, [textzeilen]), ...]."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    cues = []
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if not lines:
            continue
        if len(lines) >= 2 and TIME_RE.match(lines[1]):
            cues.append((lines[0], lines[1], lines[2:]))
        elif TIME_RE.match(lines[0]):
            cues.append((None, lines[0], lines[1:]))
        else:
            logging.warning("Block ohne Timecode übersprungen: %r", lines[:1])
    return cues


def render_srt(cues, texts):
    out = []
    for (idx, timing, _), new_text in zip(cues, texts):
        block = []
        if idx is not None:
            block.append(idx)
        block.append(timing)
        block.extend(new_text)
        out.append("\n".join(block))
    return "\n\n".join(out) + "\n"


PROMPT = """Du übersetzt Untertitel aus dem Englischen ins Deutsche.

Regeln:
- Jede Eingabezeile beginnt mit "{marker}<nummer>{marker} " gefolgt vom Text.
- Gib GENAU so viele Zeilen zurück, in derselben Reihenfolge, mit demselben Präfix.
- Übersetze nur den Text nach dem Präfix. Keine Nummern, Zeiten oder Präfixe ändern.
- Untertitel sind mitten im Satz zerschnitten: übersetze jede Zeile so, dass die
  Aufteilung erhalten bleibt, auch wenn ein Fragment für sich unvollständig wirkt.
- Natürliches, gesprochenes Deutsch, Zuschauer duzen.
- Keine Erklärungen, keine Anführungszeichen, keine leeren Zeilen einfügen.

Zeilen:
{payload}"""


def translate_batch(model, chunks, max_retries=4):
    """chunks: Liste von Strings (je eine Cue, Zeilenumbrüche als \\n innerhalb)."""
    payload = "\n".join(
        f"{MARKER}{i}{MARKER} " + c.replace("\n", " ⏎ ") for i, c in enumerate(chunks)
    )
    prompt = PROMPT.format(marker=MARKER, payload=payload)

    for attempt in range(max_retries):
        try:
            answer = model.generate_content(prompt).text
            got = {}
            for line in answer.split("\n"):
                m = re.match(rf"\s*{MARKER}(\d+){MARKER}\s?(.*)$", line)
                if m:
                    got[int(m.group(1))] = m.group(2).strip()
            if len(got) == len(chunks) and set(got) == set(range(len(chunks))):
                return [
                    got[i].replace(" ⏎ ", "\n").replace("⏎", "\n")
                    for i in range(len(chunks))
                ]
            logging.warning(
                "Antwort unvollständig (%d von %d Zeilen), Versuch %d",
                len(got), len(chunks), attempt + 1,
            )
        except llm.transient_errors() as exc:
            logging.warning("Modellaufruf gescheitert: %s (Versuch %d)",
                            exc, attempt + 1)
        time.sleep(3)

    if len(chunks) == 1:
        # Lieber abbrechen als eine englische Zeile unbemerkt durchreichen.
        raise RuntimeError(f"Cue nicht übersetzbar: {chunks[0][:60]!r}")
    half = len(chunks) // 2
    logging.info("Teile Batch (%d) und versuche erneut", len(chunks))
    return (translate_batch(model, chunks[:half])
            + translate_batch(model, chunks[half:]))


def translate_file(model, src, dst, batch_size=40):
    with open(src, encoding="utf-8-sig", errors="replace") as fh:
        cues = parse_srt(fh.read())
    texts = ["\n".join(c[2]) for c in cues]
    result = []
    for start in range(0, len(texts), batch_size):
        result.extend(translate_batch(model, texts[start:start + batch_size]))
        logging.info("%s: %d/%d Cues", os.path.basename(src), len(result), len(texts))
    assert len(result) == len(cues), f"{src}: {len(result)} != {len(cues)}"
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(render_srt(cues, [r.split("\n") for r in result]))
    return len(cues)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--model", default=None,
                    help="Modellname beim gewählten Anbieter")
    llm.add_provider_argument(ap)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    model = llm.get_model(args.model, args.provider)
    logging.info("Anbieter: %s", llm.resolve(args.provider))
    for path in args.files:
        name = os.path.basename(path)
        out = os.path.join(args.outdir, re.sub(r"-en\.srt$", "-de.srt", name))
        if os.path.exists(out) and os.path.getsize(out) > 0:
            logging.info("überspringe %s (existiert)", os.path.basename(out))
            continue
        n = translate_file(model, path, out, args.batch_size)
        logging.info("fertig: %s (%d Cues)", os.path.basename(out), n)


if __name__ == "__main__":
    main()
