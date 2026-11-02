#!/bin/bash
# Installiert den Befehl `utt` systemweit für den aktuellen Benutzer (~/.local/bin).
#   ./install.sh               installieren
#   ./install.sh --uninstall   Befehl wieder entfernen
set -eu
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
BIN_DIR="${PREFIX_BIN:-$HOME/.local/bin}"
LINK="$BIN_DIR/utt"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$LINK"; echo "Entfernt: $LINK (Projekt und .venv bleiben)"; exit 0
fi

chmod +x "$ROOT/bin/utt"
mkdir -p "$BIN_DIR" "$ROOT/books" "$ROOT/output"
ln -sfn "$ROOT/bin/utt" "$LINK"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Erstelle Python-Umgebung ..."
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/python" -m pip install -q --upgrade pip
fi
"$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Hinweis: $BIN_DIR ist nicht im PATH. Zeile in ~/.bashrc ergänzen:"
     echo "  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
echo "Installiert: $LINK -> $ROOT/bin/utt"
echo "Test: utt --help"
