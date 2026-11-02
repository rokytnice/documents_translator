#!/usr/bin/env python3
"""Übersetzt "The Twelve-Factor App" (Adam Wiggins, MIT-Lizenz, github.com/heroku/12factor) ins Deutsche
mit der Claude-CLI-Anbindung dieses Projekts (src/llm.py). Fortsetzbar: fertige Kapitel liegen in output/12factor_de/."""
import sys, os, json, urllib.request, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import llm
ORDER = ["background","intro","toc","codebase","dependencies","config","backing-services","build-release-run","processes","port-binding","concurrency","disposability","dev-prod-parity","logs","admin-processes","who"]
SRC = ROOT / "books" / "12factor_en"; OUT = ROOT / "output" / "12factor_de"
SRC.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
model = llm.get_model()
PROMPT = ("Übersetze den folgenden Markdown-Text (Kapitel aus 'The Twelve-Factor App') präzise ins Deutsche. "
          "Behalte Markdown-Struktur, Überschriften, Listen, Codeblöcke und Links unverändert bei, übersetze Code nicht, "
          "Fachbegriffe (z. B. Codebase, Build, Release, Backing Service, Config, Port-Binding) wo üblich englisch lassen. "
          "Gib NUR die Übersetzung aus.\n\n---\n{text}")
for name in ORDER:
    out = OUT / f"{name}.md"
    if out.exists() and out.stat().st_size > 20: print("skip", name); continue
    src = SRC / f"{name}.md"
    if not src.exists():
        data = urllib.request.urlopen(f"https://raw.githubusercontent.com/heroku/12factor/main/content/en/{name}.md", timeout=30).read().decode()
        src.write_text(data)
    text = src.read_text()
    res = model.generate_content(PROMPT.format(text=text)).text.strip()
    out.write_text(res + "\n"); print("ok", name, len(text), "->", len(res), flush=True)
parts = ["# Die Twelve-Factor App (Deutsche Übersetzung)\n\n*Original: Adam Wiggins, https://12factor.net – MIT-Lizenz. Übersetzung automatisch erstellt.*\n"]
for n in ["background","intro","toc","codebase","dependencies","config","backing-services","build-release-run","processes","port-binding","concurrency","disposability","dev-prod-parity","logs","admin-processes","who"]:
    parts.append((OUT / f"{n}.md").read_text())
(ROOT / "output" / "twelve-factor-app_deutsch.md").write_text("\n\n".join(parts))
print("fertig")
