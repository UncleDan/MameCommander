#!/bin/sh
#
# MameCommander - Copyright (c) 2026 Daniele Lolli
# Licenza MIT: vedi il file LICENSE.
# SPDX-License-Identifier: MIT
#
# MameCommander e' un programma di utilita' non affiliato al progetto
# MAME. Ogni merito dell'emulazione va al team di sviluppo di MAME.
#
#
# MameCommander - script di installazione per Linux
# =================================================
#
# Uso:
#   sh install.sh                installa per l'utente corrente (~/.local)
#   sudo sh install.sh --system  installa per tutti gli utenti (/usr/local)
#   sh install.sh --uninstall    disinstalla (aggiungi --system se serve)
#   sh install.sh --help         mostra questo messaggio
#
# Invocarlo con "sh install.sh" invece di "./install.sh" e' voluto:
# funziona anche quando il permesso di esecuzione e' andato perso, cosa
# che succede sempre se il progetto e' passato per Windows (il filesystem
# di Windows non conserva i permessi Unix). Se preferisci "./install.sh",
# dai prima:  chmod +x install.sh
#
# Lo script si occupa da solo di rimettere i permessi corretti ai file che
# installa E a quelli originali del progetto, e di convertire eventuali
# fine-riga CRLF in LF.
#
# SE COMPARE L'ERRORE "bad interpreter" O ERRORI DI SINTASSI STRANI:
# significa che questo stesso file ha i fine-riga in formato Windows.
# Correggilo una volta con uno di questi comandi, poi rilancia:
#   sed -i 's/\r$//' install.sh
#   dos2unix install.sh
#
# Non serve compilare nulla: MameCommander e' uno script Python e su Linux
# 'curses' e 'sqlite3' fanno gia' parte della libreria standard.
#
# Cosa fa l'installazione:
#   - copia MameCommander.py e il lanciatore in una cartella dedicata
#   - crea un collegamento eseguibile in una cartella del PATH
#   - crea una voce di menu (.desktop) per avviarlo da terminale grafico
#
# Nessun file viene scritto fuori da queste posizioni, e la disinstallazione
# le rimuove tutte.

set -e

APP_NAME="MameCommander"
CMD_NAME="mamecommander"

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

MODE="user"
ACTION="install"

for arg in "$@"; do
    case "$arg" in
        --system)    MODE="system" ;;
        --user)      MODE="user" ;;
        --uninstall) ACTION="uninstall" ;;
        --help|-h)
            # Stampa l'intestazione commentata fino alla prima riga di
            # codice, cosi' resta corretta anche se la si modifica.
            awk 'NR>1 { if ($0 !~ /^#/ && $0 != "") exit; sub(/^# ?/, ""); print }' "$0"
            exit 0 ;;
        *)
            echo "Opzione non riconosciuta: $arg" >&2
            echo "Usa --help per l'elenco delle opzioni." >&2
            exit 1 ;;
    esac
done

if [ "$MODE" = "system" ]; then
    LIB_DIR="/usr/local/lib/$CMD_NAME"
    BIN_DIR="/usr/local/bin"
    DESKTOP_DIR="/usr/local/share/applications"
    ICON_DIR="/usr/local/share/icons/hicolor/256x256/apps"
else
    LIB_DIR="$HOME/.local/lib/$CMD_NAME"
    BIN_DIR="$HOME/.local/bin"
    DESKTOP_DIR="$HOME/.local/share/applications"
    ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
fi

DESKTOP_FILE="$DESKTOP_DIR/$CMD_NAME.desktop"

# --------------------------------------------------------------------------
# Disinstallazione
# --------------------------------------------------------------------------
if [ "$ACTION" = "uninstall" ]; then
    echo "Disinstallazione di $APP_NAME ($MODE)..."
    rm -f "$BIN_DIR/$CMD_NAME"
    rm -f "$DESKTOP_FILE"
    rm -f "$ICON_DIR/$CMD_NAME.png"
    rm -rf "$LIB_DIR"
    echo "Fatto. Rimossi:"
    echo "  $BIN_DIR/$CMD_NAME"
    echo "  $LIB_DIR"
    echo "  $DESKTOP_FILE"
    echo "  $ICON_DIR/$CMD_NAME.png"
    echo
    echo "Nota: le ROM, mame.ini e l'eventuale MameCommander.db non sono"
    echo "stati toccati: stanno nelle tue cartelle e restano dove sono."
    exit 0
fi

# --------------------------------------------------------------------------
# Controlli preliminari
# --------------------------------------------------------------------------
echo "Installazione di $APP_NAME ($MODE)"
echo

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERRORE: Python 3 non trovato." >&2
    echo "Installalo con il gestore pacchetti della tua distribuzione, ad es.:" >&2
    echo "  Debian/Ubuntu:  sudo apt install python3" >&2
    echo "  Fedora:         sudo dnf install python3" >&2
    echo "  Arch:           sudo pacman -S python" >&2
    exit 1
fi

# Verifichiamo che curses ci sia davvero: alcune distribuzioni molto
# ridotte (o certi container) pacchettizzano Python senza il modulo.
if ! "$PY" -c "import curses, sqlite3" >/dev/null 2>&1; then
    echo "ERRORE: al tuo Python mancano i moduli 'curses' o 'sqlite3'." >&2
    echo "Di norma sono inclusi; se non ci sono, su Debian/Ubuntu installa:" >&2
    echo "  sudo apt install python3-full libncursesw6" >&2
    exit 1
fi
echo "Python trovato: $($PY --version 2>&1)"

if [ ! -f "$SRC_DIR/$APP_NAME.py" ]; then
    echo "ERRORE: $APP_NAME.py non trovato accanto a questo script." >&2
    echo "Esegui install.sh dalla cartella del progetto scompattato." >&2
    exit 1
fi

if [ "$MODE" = "system" ] && [ "$(id -u)" -ne 0 ]; then
    echo "ERRORE: l'installazione di sistema richiede i privilegi di root." >&2
    echo "Riprova con:  sudo $0 --system" >&2
    exit 1
fi

# MAME non e' obbligatorio adesso, ma avvisare subito evita di scoprire il
# problema solo al primo avvio.
if command -v mame >/dev/null 2>&1 || command -v mame64 >/dev/null 2>&1; then
    echo "MAME trovato:   $(command -v mame 2>/dev/null || command -v mame64)"
else
    echo "AVVISO: MAME non risulta installato o non e' nel PATH."
    echo "        MameCommander lo cercera' comunque all'avvio, anche nella"
    echo "        propria cartella. Per installarlo, ad es.:"
    echo "          Debian/Ubuntu:  sudo apt install mame"
    echo "          Fedora:         sudo dnf install mame"
fi
echo

# --------------------------------------------------------------------------
# Copia dei file
# --------------------------------------------------------------------------
mkdir -p "$LIB_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"

cp "$SRC_DIR/$APP_NAME.py" "$LIB_DIR/"
[ -f "$SRC_DIR/README.md" ] && cp "$SRC_DIR/README.md" "$LIB_DIR/"
# La licenza va distribuita insieme al software: la MIT richiede che la
# nota di copyright accompagni ogni copia, quindi la si installa accanto
# ai file del programma invece di lasciarla solo nell'archivio.
[ -f "$SRC_DIR/LICENSE" ] && cp "$SRC_DIR/LICENSE" "$LIB_DIR/"
# Icona per la voce di menu. Su Linux non si incorpora nell'eseguibile
# (il formato ELF non ha una sezione risorse come i .exe di Windows):
# si installa come file e la si indica nel .desktop.
[ -f "$SRC_DIR/$APP_NAME.png" ] && cp "$SRC_DIR/$APP_NAME.png" "$ICON_DIR/$CMD_NAME.png"
if [ -f "$SRC_DIR/$CMD_NAME" ]; then
    cp "$SRC_DIR/$CMD_NAME" "$LIB_DIR/"
fi

# --------------------------------------------------------------------------
# Normalizzazione: permessi e fine-riga
# --------------------------------------------------------------------------
# Se il progetto e' stato scompattato o modificato su Windows, i file
# arrivano qui senza il bit di esecuzione e, spesso, con i fine-riga in
# formato CRLF. Su Linux il CRLF e' fatale per uno script: il kernel legge
# la riga "#!/bin/sh\r" e cerca un interprete chiamato "sh\r", che non
# esiste, restituendo l'errore fuorviante "bad interpreter". Sistemiamo
# entrambe le cose qui, una volta per tutte, invece di lasciarlo fare
# all'utente a mano.
strip_cr() {
    # Rimuove i CR finali solo se ce ne sono davvero, cosi' non tocchiamo
    # inutilmente la data dei file gia' in formato Unix.
    if [ -f "$1" ] && grep -q "$(printf '\r')" "$1" 2>/dev/null; then
        tmp="$1.tmp$$"
        tr -d '\r' < "$1" > "$tmp" && mv "$tmp" "$1"
        echo "  fine-riga CRLF convertiti in LF: $(basename "$1")"
    fi
}

strip_cr "$LIB_DIR/$APP_NAME.py"
strip_cr "$LIB_DIR/$CMD_NAME"

chmod 755 "$LIB_DIR/$APP_NAME.py"
[ -f "$LIB_DIR/$CMD_NAME" ] && chmod 755 "$LIB_DIR/$CMD_NAME"
[ -f "$LIB_DIR/README.md" ] && chmod 644 "$LIB_DIR/README.md"
[ -f "$LIB_DIR/LICENSE" ] && chmod 644 "$LIB_DIR/LICENSE"
chmod 755 "$LIB_DIR"

# Rimettiamo il bit di esecuzione anche sui file ORIGINALI del progetto:
# cosi', se in seguito lo esegui direttamente dalla cartella scompattata
# senza reinstallare, funziona comunque.
[ -w "$SRC_DIR/$CMD_NAME" ] && chmod +x "$SRC_DIR/$CMD_NAME" 2>/dev/null || true
[ -w "$SRC_DIR/$APP_NAME.py" ] && chmod +x "$SRC_DIR/$APP_NAME.py" 2>/dev/null || true
[ -w "$SRC_DIR/install.sh" ] && chmod +x "$SRC_DIR/install.sh" 2>/dev/null || true

echo "Copiato in:     $LIB_DIR"

# Il comando nel PATH e' un piccolo script, non un link simbolico: cosi'
# funziona anche se l'utente sposta o copia il file altrove.
cat > "$BIN_DIR/$CMD_NAME" <<EOF
#!/bin/sh
exec "$PY" "$LIB_DIR/$APP_NAME.py" "\$@"
EOF
chmod +x "$BIN_DIR/$CMD_NAME"
echo "Comando creato: $BIN_DIR/$CMD_NAME"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
GenericName=Frontend per MAME
Comment=Frontend testuale per MAME in stile Norton Commander
Exec=$BIN_DIR/$CMD_NAME
Icon=$CMD_NAME
Terminal=true
Categories=Game;Emulator;
Keywords=mame;arcade;emulatore;emulator;
EOF
echo "Voce di menu:   $DESKTOP_FILE"
[ -f "$ICON_DIR/$CMD_NAME.png" ] && echo "Icona:          $ICON_DIR/$CMD_NAME.png"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
# Alcuni ambienti desktop mostrano la nuova icona solo dopo aver
# aggiornato la cache del tema.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$(dirname "$(dirname "$(dirname "$ICON_DIR")")")" >/dev/null 2>&1 || true
fi

# --------------------------------------------------------------------------
# Esito
# --------------------------------------------------------------------------
echo
echo "Installazione completata (versione script Python, non compilata)."
echo
echo "Nessun binario e' stato creato: viene eseguito direttamente"
echo "$APP_NAME.py con $PY. Per aggiornarlo in futuro bastera'"
echo "sostituire il file e rilanciare questo script."
echo
echo "Avvialo con:    $CMD_NAME"
echo "Con log debug:  $CMD_NAME -debug"
echo "Per rimuoverlo: $SRC_DIR/install.sh --uninstall$([ "$MODE" = system ] && echo ' --system')"

# ~/.local/bin non e' nel PATH su tutte le distribuzioni: se manca, il
# comando appena creato non verrebbe trovato e sembrerebbe un errore.
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo
        echo "ATTENZIONE: $BIN_DIR non risulta nel tuo PATH."
        echo "Aggiungilo, poi riapri il terminale:"
        echo "  echo 'export PATH=\"\$PATH:$BIN_DIR\"' >> ~/.profile"
        echo "Oppure avvialo con il percorso completo: $BIN_DIR/$CMD_NAME"
        ;;
esac
