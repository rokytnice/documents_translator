"""Wählt aus den deutschen Untertiteln die Stellen, an denen etwas gezeigt wird.

Ausgabe: TSV mit Kapitel, Zeitstempel, Cue-Index und Bildunterschrift — die
Vorlage dafür, an welchen Stellen später Standbilder ins Buch kommen.
"""

import json
import os
import re
import sys

TIME = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)

# Wörter, die auf eine Demonstration hindeuten ("schau, so hältst du das")
STRONG = [
    "schau", "sieh", "siehst", "pass auf", "zeige dir", "zeig", "guck",
    "so sieht", "so aussieht", "wie das aussieht", "genau so", "so hältst",
    "so herum", "hier so", "das hier", "so wie", "wie du siehst",
]
MEDIUM = [
    " so ", "hier", "dreh", "leg ", "legst", "halt ", "hältst", "nimm ",
    "nimmst", "schieb", "drück", "falte", "reib", "wisch", "tipp",
    "markierung", "spreiz", "abzähl", "biege", "bieg ",
]
# Cues, die für ein Standbild nichts hergeben
SKIP = re.compile(
    r"^[-\s]*(ja|nein|okay|genau|mhm|jep|richtig|klar|wow|danke|mm|hä|oh)\b", re.I
)


def parse(path):
    """SRT -> Liste von (index, start_sec, end_sec, text)."""
    txt = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    out = []
    for i, block in enumerate(re.split(r"\n\s*\n", txt)):
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        timing = None
        if len(lines) >= 2 and TIME.match(lines[1]):
            timing, body = TIME.match(lines[1]), lines[2:]
        elif TIME.match(lines[0]):
            timing, body = TIME.match(lines[0]), lines[1:]
        if not timing:
            continue
        g = [int(x) for x in timing.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        out.append((len(out), start, end, " ".join(s.strip() for s in body)))
    return out


def score(text):
    low = f" {text.lower()} "
    if SKIP.match(text.strip()) or len(text) < 28:
        return 0
    s = 0
    for w in STRONG:
        if w in low:
            s += 3
    for w in MEDIUM:
        if w in low:
            s += 1
    if "(" in text:  # reiner Ton-/Musikhinweis
        s -= 2
    return s


def pick(cues, per_minute=0.5, min_gap=40, cap=26):
    """Wählt gut verteilte Stellen mit hoher Punktzahl."""
    if not cues:
        return []
    duration = cues[-1][2]
    want = max(4, min(cap, round(duration / 60 * per_minute)))
    ranked = sorted(
        ((score(t), i, st, en, t) for i, st, en, t in cues if score(t) > 0),
        key=lambda r: (-r[0], r[2]),
    )
    chosen = []
    for sc, i, st, en, t in ranked:
        if len(chosen) >= want:
            break
        stamp = st + min(1.2, max(0.3, (en - st) / 2))
        if any(abs(stamp - c["t"]) < min_gap for c in chosen):
            continue
        chosen.append({"t": round(stamp, 2), "cue": i, "score": sc, "text": t})
    chosen.sort(key=lambda c: c["t"])
    return chosen


def main(srt_dir, out_json):
    from srt_to_docx import TITLES, ORDER

    plan = {}
    total = 0
    for key in ORDER:
        path = os.path.join(srt_dir, f"{key}-de.srt")
        if not os.path.exists(path):
            continue
        cues = parse(path)
        picks = pick(cues)
        if not picks:
            continue
        plan[key] = picks
        total += len(picks)
        mins = cues[-1][2] / 60 if cues else 0
        print(f"{TITLES[key]:30s} {mins:6.1f} min  -> {len(picks):3d} Bilder")
    json.dump(plan, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\ngesamt {total} Bilder -> {out_json}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main(sys.argv[1], sys.argv[2])
