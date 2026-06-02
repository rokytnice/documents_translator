#!/bin/bash

# Pfad zum Virtual Environment
VENV_DIR=".venv"

# 1. Prüfen ob venv existiert
if [ ! -d "$VENV_DIR" ]; then
    echo "Bitte starte erst ./run.sh um die Umgebung einzurichten, oder: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 2. Venv aktivieren
source $VENV_DIR/bin/activate

# 3. Programm starten
echo "Starte Visuellen Translator (Bilder & Text)..."
# Suche nach PDF Datei im Ordner falls keine angegeben
PDF_FILE=$(find . -maxdepth 1 -name "*.pdf" | head -n 1)

if [ -z "$PDF_FILE" ]; then
    echo "Keine PDF Datei gefunden."
else
    echo "Verarbeite: $PDF_FILE"
    $VENV_DIR/bin/python src/visual_translator.py "$PDF_FILE" "deutsch"
fi
