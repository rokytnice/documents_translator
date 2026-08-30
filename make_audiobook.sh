#!/bin/bash
# Kapitelweises Hörbuch aus der fertigen Interpretation — lokal mit Piper TTS.
#
#   ./make_audiobook.sh --file output/ilias_interpretation.md
#   ./make_audiobook.sh --file output/ilias_interpretation.md --voice de_DE-eva_k-x_low
#   ./make_audiobook.sh --file output/ilias_interpretation.md --chapter 3 --force
#
# Pro Kapitel entsteht eine getaggte MP3 plus Playlist. Ein erneuter Lauf überspringt
# fertige Kapitel, ein Abbruch kostet also höchstens das laufende Kapitel.

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

PIPER_BIN="${PIPER_BIN:-$HOME/.local/bin/piper}"
if [ ! -x "$PIPER_BIN" ]; then
    echo "FEHLER: piper nicht gefunden unter $PIPER_BIN" >&2
    echo "Installation: pip install piper-tts, Stimmen nach ~/.local/share/piper/voices/" >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null; then
    echo "FEHLER: ffmpeg nicht installiert." >&2
    exit 1
fi

echo "Starte Hörbuch-Erzeugung..."
$VENV_DIR/bin/python src/audiobook.py "$@"
