# PDF Translator

Ein Python-Tool zum seitenweisen Übersetzen von PDF- und EPUB-Dokumenten via Google Gemini API. Die Übersetzung wird Seite für Seite als Textdatei gespeichert und kann jederzeit unterbrochen und fortgesetzt werden.

## Projektstruktur

```
books/              ← Quell-PDFs und EPUBs hier ablegen
output/             ← Übersetzungen und Fortschrittsdateien
src/                ← Python-Skripte
translate_books.sh  ← Hauptskript: Bücher übersetzen
run_visual.sh       ← Visueller Translator (Text + Bilder)
create_pdf.sh       ← Markdown-Datei in PDF konvertieren
install.sh          ← Ersteinrichtung der Umgebung
```

## Shell-Skripte

### `translate_books.sh` — Bücher übersetzen
Das Hauptskript. Richtet das virtuelle Python-Environment automatisch ein, installiert alle Abhängigkeiten und startet die Übersetzung.

```bash
./translate_books.sh                        # alle Bücher in books/ übersetzen
./translate_books.sh --file books/buch.pdf  # einzelnes Buch
./translate_books.sh --lang english         # andere Zielsprache (Standard: deutsch)
./translate_books.sh --range 10-50          # nur Seiten 10–50
```

Bei einem Neustart setzt das Skript automatisch an der zuletzt übersetzten Seite weiter (Fortschritt wird in `output/<buch>.progress.json` gespeichert).

---

### `run_visual.sh` — Visueller Translator
Übersetzt eine PDF-Datei mitsamt Bildern und erstellt eine Markdown-Datei mit eingebetteten Bildbeschreibungen. Sucht automatisch nach einer PDF-Datei im Projektverzeichnis.

```bash
./run_visual.sh
```

---

### `create_pdf.sh` — Markdown zu PDF
Konvertiert eine übersetzte Markdown-Datei (`*_visual_deutsch.md`) in ein PDF.

```bash
./create_pdf.sh output/buch_visual_deutsch.md
./create_pdf.sh   # nimmt automatisch die neueste *_visual_deutsch.md
```

---

### `install.sh` — Ersteinrichtung
Installiert pip, erstellt das virtuelle Environment und installiert alle Abhängigkeiten. Nur einmalig nötig (bei normalem Gebrauch übernimmt `translate_books.sh` die Einrichtung automatisch).

```bash
./install.sh
```

---

## Konfiguration

**API Key** (erforderlich):
```bash
export GEMINI_API_KEY=DEIN_API_KEY
```

**Modell** (optional, Standard: `gemini-1.5-flash-lite-preview-06-17`):
```bash
export GEMINI_LLM=gemini-1.5-pro
```

## Auto-Resume

Jede übersetzte Seite wird sofort in `output/<buch>.progress.json` gespeichert:
```json
{
  "last_page": 42,
  "total_pages": 300,
  "language": "deutsch"
}
```
Bei einem Neustart liest das Skript diese Datei und macht automatisch weiter.

## Lizenz
MIT