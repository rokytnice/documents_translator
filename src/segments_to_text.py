"""Macht aus den Whisper-Segmenten ein lesbares Transkript mit Zeitmarken.

Aufeinanderfolgende Segmente werden zu Absätzen zusammengefasst; ein neuer
Absatz beginnt bei einer längeren Sprechpause. Liegt ein Sprecher-Label vor
(nach der Diarisierung), wird zusätzlich bei jedem Sprecherwechsel umbrochen.
"""

import json
import sys


def stamp(seconds):
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main(seg_json, out_txt, gap=2.0, max_chars=700):
    segments = json.load(open(seg_json, encoding="utf-8"))
    blocks, buf, start, speaker = [], "", None, None

    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        spk = seg.get("speaker")
        pause = start is not None and seg["start"] - prev_end > gap
        switch = speaker is not None and spk != speaker
        if buf and (switch or pause or len(buf) > max_chars):
            blocks.append((start, speaker, buf.strip()))
            buf, start = "", None
        if start is None:
            start, speaker = seg["start"], spk
        buf = f"{buf} {text}".strip()
        prev_end = seg["end"]
    if buf:
        blocks.append((start, speaker, buf.strip()))

    with open(out_txt, "w", encoding="utf-8") as fh:
        fh.write("Transkript\n")
        fh.write(f"Quelle: {seg_json}\n")
        fh.write(f"Länge: {stamp(segments[-1]['end'])} · {len(segments)} Segmente\n")
        if not any(s.get("speaker") for s in segments):
            fh.write("Hinweis: ohne Sprechertrennung — die Zuordnung der Stimmen "
                     "fehlt noch.\n")
        fh.write("\n" + "=" * 70 + "\n\n")
        for start, spk, text in blocks:
            label = f"[{stamp(start)}] "
            if spk:
                label += f"{spk}: "
            fh.write(label + text + "\n\n")

    print(f"{out_txt}: {len(blocks)} Absätze aus {len(segments)} Segmenten")


if __name__ == "__main__":
    main(*sys.argv[1:3])
