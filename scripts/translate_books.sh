#!/bin/bash
cd "$(dirname "$0")/.."

VENV_DIR=".venv"

# 1. Prüfen ob venv existiert, wenn nicht erstellen
if [ ! -d "$VENV_DIR" ]; then
    echo "Erstelle Virtual Environment..."
    python3 -m venv $VENV_DIR
fi

# 2. Venv aktivieren (nur für dieses Skript)
source $VENV_DIR/bin/activate

# 3. Abhängigkeiten installieren/aktualisieren
if [ -f "requirements.txt" ]; then
    $VENV_DIR/bin/pip install -q -r requirements.txt
fi

# 4. Das Python-Programm starten
echo "Starte Translator..."
$VENV_DIR/bin/python src/translator.py "$@"
