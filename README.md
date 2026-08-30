# PDF Translator

A Python tool for translating PDF and EPUB documents page by page. The model is reached through the Claude Code CLI (`claude`) by default; the Gemini API can be selected with `--provider gemini`. Translations are saved incrementally and can be interrupted and resumed at any time.

## Project Structure

```
books/                              ← Place source PDFs and EPUBs here
output/                             ← Translations and progress files
src/                                ← Python scripts
scripts/
  translate_books.sh                ← Main script: translate books
  translate_books_with_images.sh    ← Visual translator (text + images)
  convert_pdf_from_md.sh            ← Convert Markdown file to PDF
  prepare_env.sh                    ← Initial setup
```

## Shell Scripts

### `scripts/translate_books.sh` — Translate books
The main script. Automatically sets up the virtual Python environment, installs all dependencies, and starts the translation.

```bash
./scripts/translate_books.sh                          # translate all books in books/
./scripts/translate_books.sh --file books/book.pdf    # single book
./scripts/translate_books.sh --lang english           # different target language (default: deutsch)
./scripts/translate_books.sh --range 10-50            # only pages 10–50
```

On restart, the script automatically continues from the last translated page (progress is saved in `output/<book>.progress.json`).

---

### `scripts/translate_books_with_images.sh` — Visual translator
Translates a PDF including images and creates a Markdown file with embedded image descriptions. Automatically searches for a PDF file in the project directory.

```bash
./scripts/translate_books_with_images.sh
```

---

### `scripts/convert_pdf_from_md.sh` — Markdown to PDF
Converts a translated Markdown file (`*_visual_deutsch.md`) into a PDF.

```bash
./scripts/convert_pdf_from_md.sh output/book_visual_deutsch.md
./scripts/convert_pdf_from_md.sh   # automatically picks the most recent *_visual_deutsch.md
```

---

### `scripts/prepare_env.sh` — Initial setup
Installs pip, creates the virtual environment, and installs all dependencies. Only needed once (for normal use, `translate_books.sh` handles setup automatically).

```bash
./scripts/prepare_env.sh
```

---

## Configuration

**API Key** (required):
```bash
# Standard: Claude CLI, kein API-Key nötig.
export CLAUDE_CLI=/pfad/zu/claude        # optional, falls nicht im PATH

# Optional Gemini statt Claude (pro Aufruf oder für die ganze Shell):
#   python src/translator.py --provider gemini ...
export LLM_PROVIDER=gemini               # optional, setzt den Standard um
export GEMINI_API_KEY=YOUR_API_KEY       # nur für den Gemini-Pfad
# Achtung: Free-Tier = 20 Anfragen pro Modell und Tag.
```

**Model** (optional, sonst das Standardmodell des Anbieters):
```bash
export CLAUDE_MODEL=claude-sonnet-5   # bzw. GEMINI_LLM=gemini-2.5-flash
```

## Auto-Resume

After each translated page, progress is saved to `output/<book>.progress.json`:
```json
{
  "last_page": 42,
  "total_pages": 300,
  "language": "deutsch"
}
```
On restart, the script reads this file and continues automatically.

## License
MIT
