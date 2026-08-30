#!/bin/bash
# Moderne Interpretation eines historischen Textes — Seite für Seite, ein Stil.
#
#   ./interpret_book.sh --file books/Homer_Odyssee_Deutsch_Voss.pdf
#   ./interpret_book.sh --file books/Homer_Ilias_Deutsch_Voss.pdf --range 40-80
#   ./interpret_book.sh --file books/... --style follett_style.md --force
#
# Ohne --range läuft das ganze Buch. Ein Abbruch ist unkritisch: der nächste Start
# setzt hinter der letzten fertigen Seite fort (output/*.progress.json).

cd "$(dirname "$0")"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Erstelle Virtual Environment..."
    python3 -m venv $VENV_DIR
fi

source $VENV_DIR/bin/activate

if [ -f "requirements.txt" ]; then
    $VENV_DIR/bin/pip install -q -r requirements.txt
fi

if ! command -v "${CLAUDE_CLI:-claude}" >/dev/null 2>&1; then
    echo "FEHLER: Claude CLI nicht gefunden (CLAUDE_CLI setzen oder installieren)." >&2
    exit 1
fi

echo "Starte Interpretations-Agent..."
$VENV_DIR/bin/python src/interpreter.py "$@"
