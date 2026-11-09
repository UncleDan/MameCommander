#!/bin/sh
# build.sh by Daniele Lolli (UncleDan) feat. Claude AI - Release 1.3 - 2026-11-08 23-20-33
#
# MameCommander - Copyright (c) 2026 Daniele Lolli
# Licenza MIT: vedi il file LICENSE.
# SPDX-License-Identifier: MIT
#
# MameCommander e' un programma di utilita' non affiliato al progetto
# MAME. Ogni merito dell'emulazione va al team di sviluppo di MAME.
#
#
# MameCommander - compilazione dell'eseguibile per Linux
# ======================================================
#
# Uso:
#   sh build.sh            compila l'eseguibile in ../dist/mamecommander
#   sh build.sh --clean    rimuove soltanto i file di compilazione
#   sh build.sh --help     mostra questo messaggio
#
# ATTENZIONE - su Linux compilare NON serve quasi mai.
# MameCommander e' uno script Python e sui sistemi Linux 'curses' e
# 'sqlite3' fanno gia' parte della libreria standard: si esegue
# direttamente, senza dipendenze da installare. Per l'uso normale usa
# ../install.sh, che e' piu' semplice e non richiede PyInstaller.
#
# Questo script serve nei casi particolari in cui vuoi un binario unico:
#   - distribuirlo a chi non ha Python installato
#   - metterlo su una chiavetta insieme a MAME, senza installare nulla
#
# LIMITE IMPORTANTE DEI BINARI PYINSTALLER SU LINUX:
# il binario prodotto e' legato alla versione di glibc del sistema su cui
# viene compilato. Un eseguibile compilato su una distribuzione recente
# NON parte su una piu' vecchia (errore tipico: "GLIBC_2.xx not found").
# Il contrario invece funziona. Quindi, se ti serve un binario portabile,
# compilalo sulla distribuzione piu' VECCHIA che intendi supportare.
#
# I file temporanei finiscono in ../.pyi-work e NON nella cartella "build",
# che contiene gli script di compilazione e va lasciata intatta.

set -e

APP_NAME="MameCommander"
OUT_NAME="mamecommander"

# La cartella di questo script; ".." e' la radice del progetto.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

WORK_DIR="$PROJECT_DIR/.pyi-work"
DIST_DIR="$PROJECT_DIR/dist"

ACTION="build"
for arg in "$@"; do
    case "$arg" in
        --clean) ACTION="clean" ;;
        --help|-h)
            awk 'NR>1 { if ($0 !~ /^#/ && $0 != "") exit; sub(/^# ?/, ""); print }' "$0"
            exit 0 ;;
        *)
            echo "Opzione non riconosciuta: $arg" >&2
            echo "Usa --help per l'elenco delle opzioni." >&2
            exit 1 ;;
    esac
done

cd "$PROJECT_DIR"

if [ "$ACTION" = "clean" ]; then
    echo "Pulizia dei file di compilazione..."
    rm -rf "$WORK_DIR" "$DIST_DIR" "$PROJECT_DIR/$APP_NAME.spec"
    find "$PROJECT_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    echo "Fatto."
    exit 0
fi

echo "============================================================"
echo " $APP_NAME - Build eseguibile per Linux"
echo "============================================================"
echo " Cartella progetto: $PROJECT_DIR"
echo

if [ ! -f "$PROJECT_DIR/$APP_NAME.py" ]; then
    echo "ERRORE: $APP_NAME.py non trovato in $PROJECT_DIR" >&2
    echo "Questo script deve restare nella sottocartella 'build'." >&2
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERRORE: Python 3 non trovato." >&2
    exit 1
fi
echo "Python: $($PY --version 2>&1)"

if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
    echo
    echo "PyInstaller non risulta installato."
    echo "Installalo con uno di questi comandi, poi rilancia:"
    echo "  $PY -m pip install --user pyinstaller"
    echo "  sudo apt install pyinstaller        # Debian/Ubuntu"
    echo
    echo "Nota: sulle distribuzioni recenti pip rifiuta di installare"
    echo "pacchetti a livello di sistema (PEP 668). In quel caso usa un"
    echo "ambiente virtuale:"
    echo "  $PY -m venv .venv && . .venv/bin/activate && pip install pyinstaller"
    exit 1
fi
echo "PyInstaller: $("$PY" -m PyInstaller --version 2>&1)"
echo

echo "[1/2] Pulizia build precedenti..."
rm -rf "$WORK_DIR" "$DIST_DIR" "$PROJECT_DIR/$APP_NAME.spec"

echo "[2/2] Compilazione..."
# Su Linux l'icona NON si incorpora nell'eseguibile: il formato ELF non
# ha una sezione risorse come i .exe di Windows. L'icona viene invece
# associata dalla voce di menu (.desktop) che crea install.sh.
"$PY" -m PyInstaller \
    --onefile \
    --console \
    --name "$OUT_NAME" \
    --workpath "$WORK_DIR" \
    --specpath "$WORK_DIR" \
    --distpath "$DIST_DIR" \
    "$PROJECT_DIR/$APP_NAME.py"

chmod +x "$DIST_DIR/$OUT_NAME"

echo
echo "============================================================"
echo " Fatto! Eseguibile creato in:"
echo "   $DIST_DIR/$OUT_NAME"
echo
echo " Dimensione: $(du -h "$DIST_DIR/$OUT_NAME" | cut -f1)"
echo " Compilato con: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo "sistema sconosciuto")"
echo
echo " Ricorda: cerca l'eseguibile di MAME, la cartella roms e il"
echo " proprio database nella PROPRIA cartella (oltre che nel PATH"
echo " e in ~/.mame), non nella directory di lavoro."
echo "============================================================"
