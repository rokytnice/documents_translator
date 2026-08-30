"""Cue-Texte aus SRT exportieren und übersetzte Texte wieder einsetzen.

export: schreibt je Cue eine Zeile "<nr>|<text>" (interne Umbrüche als ⏎).
merge:  baut die deutsche SRT aus Original-Timecodes + übersetzten Zeilen.
"""
import re, sys, os

TIME = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")


def parse(path):
    txt = open(path, encoding="utf-8-sig", errors="replace").read()
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", txt):
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if not lines:
            continue
        if len(lines) >= 2 and TIME.match(lines[1]):
            cues.append((lines[0], lines[1], lines[2:]))
        elif TIME.match(lines[0]):
            cues.append((None, lines[0], lines[1:]))
    return cues


def export(src, dst):
    cues = parse(src)
    with open(dst, "w", encoding="utf-8") as fh:
        for i, (_, _, text) in enumerate(cues, 1):
            fh.write(f"{i}|" + " ⏎ ".join(text) + "\n")
    print(f"{len(cues)} Cues -> {dst}")


def merge(src, trans, dst):
    cues = parse(src)
    out = {}
    for line in open(trans, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        nr, _, text = line.partition("|")
        if not nr.strip().isdigit():
            sys.exit(f"Zeile ohne Nummer: {line[:60]!r}")
        out[int(nr)] = text
    missing = [i for i in range(1, len(cues) + 1) if i not in out]
    if missing:
        sys.exit(f"FEHLT: {len(missing)} Cues, erste: {missing[:10]}")
    extra = [i for i in out if i > len(cues)]
    if extra:
        sys.exit(f"ZU VIEL: {extra[:10]}")
    blocks = []
    for i, (idx, timing, _) in enumerate(cues, 1):
        body = [s for s in out[i].split(" ⏎ ")]
        block = ([idx] if idx is not None else []) + [timing] + body
        blocks.append("\n".join(block))
    open(dst, "w", encoding="utf-8").write("\n\n".join(blocks) + "\n")
    print(f"{dst}: {len(cues)} Cues geschrieben")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "export":
        export(sys.argv[2], sys.argv[3])
    elif cmd == "merge":
        merge(sys.argv[2], sys.argv[3], sys.argv[4])
