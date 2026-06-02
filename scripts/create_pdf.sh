#!/bin/bash
cd "$(dirname "$0")/.."

VENV_DIR=".venv"

# 1. Prüfen ob venv existiert
if [ ! -d "$VENV_DIR" ]; then
    echo "Bitte starte erst ./run.sh um die Umgebung einzurichten."
    exit 1
fi

# 2. Venv aktivieren
source $VENV_DIR/bin/activate

# 3. PDF Konvertierung starten
echo "Suche nach Markdown Datei..."

# Wenn ein Argument übergeben wurde, nutze dieses
if [ ! -z "$1" ]; then
    FILE="$1"
else
    # Sonst nimm die neueste visual_deutsch.md Datei
    FILE=$(ls -t *_visual_deutsch.md 2>/dev/null | head -n 1)
fi

if [ -z "$FILE" ]; then
    echo "Keine Markdown-Datei (*_visual_deutsch.md) gefunden."
    echo "Bitte gib die Datei an: ./create_pdf.sh <datei.md>"
    exit 1
fi

echo "Konvertiere Datei: $FILE"
$VENV_DIR/bin/python src/md_to_pdf.py "$FILE"
