#!/bin/bash

# Pfad zum Virtual Environment
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
    # -qq unterdrückt die Ausgabe, wenn alles schon installiert ist
    pip install -r requirements.txt
fi

# 4. Das Python-Programm starten
echo "Starte Translator..."
python3 translator.py "$@"
