#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MameCommander - frontend per MAME in stile Norton Commander
=============================================================

Frontend testuale monolitico per MAME:
  1. Verifica che mame.exe sia presente nella stessa cartella dell'eseguibile.
  2. Legge la cartella ROMS e raccoglie tutti i file .zip/.7z presenti.
  3. Interroga mame.exe stesso per sapere:
       - quali romset sono integri ("-verifyroms")
       - quali sono BIOS, quali non sono eseguibili (slot/device),
         e qual e' il nome completo ("-listxml")
  4. Mostra in un'interfaccia a pannello singolo, stile Norton Commander,
     solo i giochi realmente avviabili (non BIOS, non device, romset OK),
     con il nome completo e la versione di MAME rilevata.
  5. Salva i risultati in un database SQLite (MameCommander.db, nella
     stessa cartella dell'eseguibile) per gli avvii successivi: se il
     file esiste viene usato direttamente (avvio istantaneo, senza
     richiamare mame.exe), altrimenti viene creato. Da dentro l'app, F5
     rifà la scansione completa e riscrive il database.

Debug: avviare con il parametro "-debug" per generare un log dettagliato
(MameCommander_debug.log) di ogni chiamata a mame.exe. Senza questo
parametro nessun log viene creato.

Pensato per essere compilato con PyInstaller in un unico eseguibile:
    pyinstaller --onefile --console --name MameCommander MameCommander.py

Su Windows serve il pacchetto 'windows-curses' (vedi requirements.txt).
"""

APP_NAME = "MameCommander"
APP_VERSION = "1.0"

import curses
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------
# Configurazione / percorsi
# --------------------------------------------------------------------------

ROM_EXTENSIONS = (".zip", ".7z")
STATUS_OK = ("good", "best available")


def app_dir() -> str:
    """Cartella dove si trova l'eseguibile (o lo script, se non compilato)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()
MAME_EXE = os.path.join(APP_DIR, "mame.exe")
DB_PATH = os.path.join(APP_DIR, f"{APP_NAME}.db")  # cache dei giochi, stessa cartella dell'eseguibile

# Il log di debug viene creato SOLO se l'app e' avviata con "-debug" (o
# "--debug"): normalmente non scrive nulla su disco.
DEBUG_ENABLED = any(a.lower() in ("-debug", "--debug") for a in sys.argv[1:])

# Cartella ROMS: proviamo alcune varianti comuni di nome
ROMS_DIR_CANDIDATES = ["roms", "ROMS", "ROM", "rom"]


def find_roms_dir() -> Optional[str]:
    for name in ROMS_DIR_CANDIDATES:
        p = os.path.join(APP_DIR, name)
        if os.path.isdir(p):
            return p
    return None


# --------------------------------------------------------------------------
# Modello dati
# --------------------------------------------------------------------------

@dataclass
class Game:
    name: str
    description: str = ""
    is_bios: bool = False
    is_device: bool = False
    runnable: bool = True
    rom_status: str = "sconosciuto"

    @property
    def is_playable(self) -> bool:
        return (
            not self.is_bios
            and not self.is_device
            and self.runnable
            and self.rom_status in STATUS_OK
        )

    @property
    def display_name(self) -> str:
        return self.description if self.description else self.name


# --------------------------------------------------------------------------
# Utility: esecuzione di mame.exe a lotti, con callback di progresso
# --------------------------------------------------------------------------

DEBUG_LOG_PATH = os.path.join(APP_DIR, f"{APP_NAME}_debug.log")


def _log_debug(section: str, command: List[str], output: str):
    """Scrive un log dettagliato di ogni chiamata a mame.exe, per diagnosticare
    problemi di parsing con versioni di MAME dal comportamento inatteso.
    Attivo SOLO se l'app e' stata avviata con il parametro -debug."""
    if not DEBUG_ENABLED:
        return
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8", errors="ignore") as f:
            f.write("=" * 70 + "\n")
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {section}\n")
            f.write("Comando: " + " ".join(command) + "\n")
            f.write("-" * 70 + "\n")
            f.write(output)
            f.write("\n")
    except OSError:
        pass  # il log e' un extra, non deve mai bloccare l'app


def reset_debug_log():
    if not DEBUG_ENABLED:
        return
    try:
        if os.path.exists(DEBUG_LOG_PATH):
            os.remove(DEBUG_LOG_PATH)
    except OSError:
        pass


def _run_mame(args, progress_cb=None) -> str:
    """Esegue mame.exe con gli argomenti dati e ritorna lo stdout completo."""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    full_cmd = [MAME_EXE] + args
    proc = subprocess.run(
        full_cmd,
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        errors="ignore",
        creationflags=creationflags,
    )
    combined = proc.stdout + "\n" + proc.stderr
    _log_debug("Chiamata a mame.exe", full_cmd, combined)
    return combined


def verify_roms(rom_names: List[str], progress_cb=None) -> Dict[str, str]:
    """
    Usa 'mame.exe -verifyroms <nome>' UNA VOLTA PER OGNI ROM.
    Le versioni molto vecchie di MAME (es. 0.78b) non accettano piu' nomi
    sulla stessa riga di comando: passandone diversi restituiscono
    "error: duplicate gamename" e non verificano nulla. Chiamare mame.exe
    un nome alla volta funziona con qualsiasi versione.

    Il FORMATO dell'output varia molto tra le versioni di MAME:
      - versioni recenti: una riga per romset, es.
            romset puckman is good
            romset achase [pacman] is best available
      - MAME 0.78b (e altre versioni vecchie), quando gli si chiede UN
        singolo nome, non stampa affatto la riga per-romset: mostra solo
        una barra di progresso e un riepilogo a fine verifica, es.
            1 romsets found, 1 were OK.
        Oppure, per un nome non riconosciuto come romset avviabile
        (es. un BIOS come "neogeo"):
            romset "  neogeo" not supported!

    Per questo il parsing prova prima il formato "per riga" (piu' preciso,
    da' anche lo stato "best available"), e se non trova nulla ricade sul
    riepilogo a conteggio: se "found" == "were OK" e almeno 1, e' buono.
    """
    result: Dict[str, str] = {}
    line_re = re.compile(r"romset\s+(\S+)\s*(?:\[[^\]]+\])?\s+is\s+(.+?)\.?\s*$", re.IGNORECASE)
    not_supported_re = re.compile(r'romset\s+"?\s*(\S+)\s*"?\s+not supported', re.IGNORECASE)
    summary_re = re.compile(r"(\d+)\s+romsets?\s+found,\s+(\d+)\s+were\s+OK\.?", re.IGNORECASE)

    total = len(rom_names)
    for i, name in enumerate(rom_names, 1):
        if progress_cb:
            progress_cb(f"Verifica ROM: {name} ({i}/{total})")
        out = _run_mame(["-verifyroms", name])

        status = None

        # 1) formato "per riga" (versioni recenti di MAME, e alcune vecchie
        #    quando ci sono piu' righe di dettaglio da mostrare)
        for line in out.splitlines():
            line = line.strip()
            m = line_re.search(line)
            if m and m.group(1).strip().lower() == name.lower():
                status = m.group(2).strip().lower()
                break

        # 2) nome non riconosciuto/non avviabile (es. BIOS in MAME vecchi)
        if status is None and not_supported_re.search(out):
            status = "non supportato da questa versione di mame"

        # 3) formato "a riepilogo" (MAME 0.78b e altre versioni vecchie)
        if status is None:
            sm = summary_re.search(out)
            if sm:
                found_n, ok_n = int(sm.group(1)), int(sm.group(2))
                status = "good" if (found_n > 0 and ok_n == found_n) else "bad"

        if status:
            result[name] = status
    return result


# Estrae singolarmente ogni blocco <machine>...</machine> o <game>...</game>
# dal testo grezzo, invece di fare il parse dell'intero documento XML.
# Questo evita che un singolo blocco malformato (bug noti in vecchie versioni
# di MAME con caratteri non "escapati", es. "&") faccia fallire il parsing
# di TUTTI i romset del lotto.
_ELEMENT_RE = re.compile(r"<(machine|game)\b.*?</\1\s*>", re.DOTALL | re.IGNORECASE)

# L'attributo "build" sulla radice <mame build="0.78b (Sep 1 2003)" ...>
# e' presente in -listxml praticamente in ogni versione di MAME: lo
# usiamo per mostrare la versione nella barra del titolo, senza bisogno
# di una chiamata separata.
_BUILD_RE = re.compile(r'''build\s*=\s*["']([^"']*)["']''', re.IGNORECASE)


def _looks_like_error(text: str) -> bool:
    """Alcune versioni di MAME (es. 0.78b) non supportano '-version' e
    rispondono con un messaggio di errore ("error: unknown option..."):
    non va mai mostrato come se fosse la versione."""
    t = text.strip().lower()
    return t.startswith("error") or "unknown option" in t or "while parsing" in t


def get_mame_version_via_cli() -> Optional[str]:
    """Fallback: chiede la versione direttamente con 'mame.exe -version'.
    Usato solo se non e' stato possibile ricavarla dall'output di -listxml.
    Se anche questo comando non e' supportato (versioni molto vecchie),
    ritorna None invece di mostrare il messaggio di errore come versione."""
    out = _run_mame(["-version"])
    for line in out.splitlines():
        line = line.strip()
        if line and not _looks_like_error(line):
            return line
    return None


def _sanitize_entities(fragment: str) -> str:
    """Corregge il bug piu' comune delle vecchie liste XML di MAME: un
    carattere '&' non seguito da un'entita' valida (es. "Rock & Roll")
    che rende l'XML non ben formato."""
    return re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", fragment)


def fetch_machine_info(rom_names: List[str], progress_cb=None) -> Tuple[Dict[str, Game], Optional[str]]:
    """
    Usa 'mame.exe -listxml <nome>' UNA VOLTA PER OGNI ROM, per lo stesso
    motivo di compatibilita' spiegato in verify_roms(): le versioni vecchie
    di MAME non accettano piu' nomi sulla stessa riga di comando.
    Ottiene: descrizione completa, se e' un BIOS, se e' un device, se e'
    eseguibile, e la versione di MAME (dall'attributo "build").
    """
    games: Dict[str, Game] = {}
    mame_version: Optional[str] = None
    total = len(rom_names)
    total_found = 0
    for i, name in enumerate(rom_names, 1):
        if progress_cb:
            progress_cb(f"Lettura informazioni MAME: {name} ({i}/{total})")
        out = _run_mame(["-listxml", name])

        if mame_version is None:
            bm = _BUILD_RE.search(out)
            if bm and bm.group(1).strip():
                mame_version = bm.group(1).strip()

        for m in _ELEMENT_RE.finditer(out):
            fragment = m.group(0)
            machine = None
            try:
                machine = ET.fromstring(fragment)
            except ET.ParseError:
                try:
                    machine = ET.fromstring(_sanitize_entities(fragment))
                except ET.ParseError:
                    continue  # solo questo romset viene saltato

            found_name = machine.get("name", "")
            desc_el = machine.find("description")
            description = desc_el.text.strip() if desc_el is not None and desc_el.text else found_name
            # isbios/isdevice/runnable non esistevano nelle versioni piu'
            # vecchie di MAME: se l'attributo manca, il default e' "non lo e'".
            is_bios = machine.get("isbios", "no") == "yes"
            is_device = machine.get("isdevice", "no") == "yes"
            runnable = machine.get("runnable", "yes") != "no"
            # Rete di sicurezza: nelle versioni molto vecchie senza attributo
            # isbios, i set BIOS hanno spesso "BIOS" nella descrizione.
            if not is_bios and "[BIOS]" in description.upper().replace(" ", ""):
                is_bios = True
            games[found_name] = Game(
                name=found_name,
                description=description,
                is_bios=is_bios,
                is_device=is_device,
                runnable=runnable,
            )
            total_found += 1

    _log_debug(
        "Riepilogo parsing -listxml",
        ["(parsing interno)"],
        f"Blocchi <machine>/<game> trovati e interpretati in totale: {total_found} su {total} rom richieste.\n"
        f"Versione MAME rilevata: {mame_version}",
    )
    return games, mame_version


def scan_rom_files(roms_dir: str) -> List[str]:
    names = []
    for entry in os.scandir(roms_dir):
        if entry.is_file():
            base, ext = os.path.splitext(entry.name)
            if ext.lower() in ROM_EXTENSIONS:
                names.append(base)
    return sorted(set(names))


def build_game_list(rom_names: List[str], progress_cb=None) -> Tuple[List[Game], Optional[str]]:
    """Pipeline completa: verifica integrita' + info da MAME, poi filtro.
    Ritorna (giochi_avviabili, versione_mame)."""
    reset_debug_log()
    _log_debug("Avvio scansione", ["(riepilogo)"], f"ROM trovate nella cartella: {len(rom_names)}\n{rom_names}")

    statuses = verify_roms(rom_names, progress_cb)
    _log_debug(
        "Riepilogo verifica ROM",
        ["(riepilogo)"],
        f"Righe di stato interpretate: {len(statuses)} su {len(rom_names)} rom cercate.\n{statuses}",
    )
    ok_names = [n for n, s in statuses.items() if s in STATUS_OK]

    if not ok_names:
        _log_debug(
            "ATTENZIONE",
            ["(riepilogo)"],
            "Nessun romset risulta 'good' o 'best available'. "
            "Controlla sopra l'output grezzo di -verifyroms: se e' vuoto, "
            "mame.exe potrebbe non trovare la cartella ROMS, oppure il "
            "formato di output di questa versione di MAME e' diverso dal "
            "previsto.",
        )
        return [], None

    infos, mame_version = fetch_machine_info(ok_names, progress_cb)
    if not mame_version:
        mame_version = get_mame_version_via_cli()
    _log_debug(
        "Riepilogo -listxml",
        ["(riepilogo)"],
        f"Romset con info recuperate da -listxml: {len(infos)} su {len(ok_names)} attesi.",
    )

    playable = []
    for name in ok_names:
        game = infos.get(name)
        if game is None:
            # mame.exe non ha riconosciuto il nome (rom non valida per questa
            # versione di MAME): la saltiamo.
            continue
        game.rom_status = statuses.get(name, "sconosciuto")
        if game.is_playable:
            playable.append(game)

    _log_debug(
        "Riepilogo finale",
        ["(riepilogo)"],
        f"Giochi giocabili dopo il filtro BIOS/device/runnable: {len(playable)}",
    )

    playable.sort(key=lambda g: g.display_name.lower())
    return playable, mame_version


# --------------------------------------------------------------------------
# Cache su SQLite (MameCommander.db, nella cartella dell'eseguibile)
# --------------------------------------------------------------------------

def load_cache_from_db(db_path: str) -> Optional[Tuple[List[Game], str]]:
    """Se il database esiste ed e' leggibile, ritorna (giochi, versione_mame).
    Altrimenti ritorna None (nessuna cache utilizzabile)."""
    if not os.path.isfile(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name, description FROM games ORDER BY description COLLATE NOCASE")
            rows = cur.fetchall()
            games = [
                Game(name=n, description=d, is_bios=False, is_device=False, runnable=True, rom_status="good")
                for n, d in rows
            ]
            mame_version = "sconosciuta"
            try:
                cur.execute("SELECT value FROM meta WHERE key = 'mame_version'")
                row = cur.fetchone()
                if row and row[0]:
                    mame_version = row[0]
            except sqlite3.Error:
                pass
            return games, mame_version
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def save_cache_to_db(db_path: str, games: List[Game], mame_version: str):
    """Riscrive interamente MameCommander.db con l'elenco dei giochi avviabili
    e la versione di MAME rilevata. Non blocca l'app in caso di errore."""
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("CREATE TABLE games (name TEXT PRIMARY KEY, description TEXT NOT NULL)")
            cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            cur.executemany(
                "INSERT INTO games (name, description) VALUES (?, ?)",
                [(g.name, g.description) for g in games],
            )
            cur.execute("INSERT INTO meta (key, value) VALUES ('mame_version', ?)", (mame_version or "sconosciuta",))
            cur.execute(
                "INSERT INTO meta (key, value) VALUES ('updated_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # la cache e' un extra: se fallisce, l'app continua a funzionare


# --------------------------------------------------------------------------
# Interfaccia testuale stile Norton Commander
# --------------------------------------------------------------------------

COLOR_NORMAL = 1
COLOR_SELECTED = 2
COLOR_TITLE = 3
COLOR_ERROR = 4
COLOR_FUNCKEYS = 5


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_NORMAL, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COLOR_TITLE, curses.COLOR_YELLOW, curses.COLOR_BLUE)
    curses.init_pair(COLOR_ERROR, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(COLOR_FUNCKEYS, curses.COLOR_BLACK, curses.COLOR_CYAN)


def draw_error_screen(stdscr, lines: List[str]):
    stdscr.clear()
    stdscr.bkgd(" ", curses.color_pair(COLOR_ERROR))
    h, w = stdscr.getmaxyx()
    for i, line in enumerate(lines):
        if i + 2 < h:
            stdscr.addstr(2 + i, 2, line[: w - 4], curses.color_pair(COLOR_ERROR))
    stdscr.addstr(h - 2, 2, "Premi un tasto per uscire...", curses.color_pair(COLOR_ERROR))
    stdscr.refresh()
    stdscr.getch()


def draw_progress(stdscr, message: str):
    stdscr.erase()
    stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))
    h, w = stdscr.getmaxyx()
    title = f" {APP_NAME} {APP_VERSION} "
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.color_pair(COLOR_TITLE) | curses.A_BOLD)
    stdscr.addstr(h // 2, max(0, (w - len(message)) // 2), message[: w - 2], curses.color_pair(COLOR_NORMAL))
    stdscr.refresh()


class App:
    def __init__(self, stdscr, games: List[Game], mame_version: str = "sconosciuta"):
        self.stdscr = stdscr
        self.games = games
        self.mame_version = mame_version
        self.filtered = games
        self.selected = 0
        self.top = 0
        self.search = ""
        self.search_time = 0.0

    # -- disegno -----------------------------------------------------------

    def draw(self):
        stdscr = self.stdscr
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))

        # Titolo
        title = f" {APP_NAME} {APP_VERSION} - MAME {self.mame_version} - {len(self.filtered)} giochi disponibili "
        stdscr.attron(curses.color_pair(COLOR_TITLE) | curses.A_BOLD)
        stdscr.addstr(0, 0, title.ljust(w)[: w - 1])
        stdscr.attroff(curses.color_pair(COLOR_TITLE) | curses.A_BOLD)

        # Area lista (bordo semplice stile NC)
        list_top = 1
        list_bottom = h - 3
        visible_rows = list_bottom - list_top

        if self.selected < self.top:
            self.top = self.selected
        if self.selected >= self.top + visible_rows:
            self.top = self.selected - visible_rows + 1

        for row in range(visible_rows):
            idx = self.top + row
            y = list_top + row
            if idx >= len(self.filtered):
                stdscr.addstr(y, 0, " " * (w - 1), curses.color_pair(COLOR_NORMAL))
                continue
            game = self.filtered[idx]
            text = f" {game.display_name} ({game.name})"
            text = text.ljust(w - 1)[: w - 1]
            attr = curses.color_pair(COLOR_SELECTED) if idx == self.selected else curses.color_pair(COLOR_NORMAL)
            stdscr.addstr(y, 0, text, attr)

        # Barra di stato
        status = f" Cerca: {self.search}" if self.search else " Digita per cercare, F5 nuovi giochi, F6 ricostruisci DB"
        stdscr.addstr(h - 2, 0, status.ljust(w)[: w - 1], curses.color_pair(COLOR_NORMAL))

        # Barra tasti funzione
        funckeys = " F1 Aiuto  F5 Nuovi giochi  F6 Ricostruisci  Invio Avvia  F10/Esc Esci "
        stdscr.addstr(h - 1, 0, funckeys.ljust(w)[: w - 1], curses.color_pair(COLOR_FUNCKEYS))

        stdscr.refresh()

    # -- ricerca incrementale ------------------------------------------------

    def apply_search(self):
        if not self.search:
            self.filtered = self.games
        else:
            s = self.search.lower()
            self.filtered = [g for g in self.games if s in g.display_name.lower() or s in g.name.lower()]
        self.selected = 0
        self.top = 0

    # -- azioni --------------------------------------------------------------

    def launch_selected(self):
        if not self.filtered:
            return
        game = self.filtered[self.selected]
        curses.def_prog_mode()
        curses.endwin()
        # Sovrascriviamo il testo residuo sulla console originale (es. il
        # messaggio "Avvio MameCommander..." di run_cmd.bat/run_ps.ps1) con
        # un messaggio esplicito: resta visibile finche' il gioco e' aperto,
        # cosi' e' chiaro cosa sta girando e si evita di rilanciarne un altro
        # per errore mentre si e' ancora dentro la partita.
        print(f"{APP_NAME}: lancio ROM '{game.name}'...")
        try:
            # Lanciamo mame.exe in una console Windows NUOVA e separata da
            # quella del frontend. Necessario perche' PDCurses (usato da
            # windows-curses) gestisce la console in un modo che, se
            # mame.exe eredita lo stesso handle, causa su alcune versioni
            # (es. 0.78b, DirectInput) l'errore:
            #   "Unable to open the keyboard device. (error 32)"
            # (sharing violation sull'handle della tastiera). Con una
            # console dedicata, mame.exe puo' aprirla in esclusiva senza
            # conflitti col processo padre.
            creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            proc = subprocess.Popen([MAME_EXE, game.name], cwd=APP_DIR, creationflags=creationflags)
            proc.wait()
        except Exception as exc:
            print(f"Errore avviando {game.name}: {exc}")
            input("Premi invio per continuare...")
        # Ripristiniamo la modalita' curses PRIMA di ridisegnare (l'ordine
        # inverso lascia a volte lo schermo bloccato sul prompt originale).
        curses.reset_prog_mode()
        # La console potrebbe ancora mostrare il testo di prima di endwin()
        # (curses non sa che nel frattempo e' stato eseguito un altro
        # programma): clearok forza il PROSSIMO refresh a ridisegnare tutto
        # da zero, cosi' il menu ricompare sempre, invece di restare sul
        # prompt "avvio in corso".
        self.stdscr.clearok(True)
        curses.curs_set(0)
        self.stdscr.refresh()

    def show_help(self):
        stdscr = self.stdscr
        h, w = stdscr.getmaxyx()
        lines = [
            "Frecce su/giu: muovi selezione",
            "PagUp/PagDown: scorri pagina",
            "Home/End: inizio/fine lista",
            "Digita lettere: filtra i giochi per nome",
            "Backspace: cancella ricerca",
            "Invio: avvia il gioco selezionato",
            "F5: cerca solo le ROM nuove (non ritocca quelle gia' in DB)",
            "F6: ricostruisce l'intero database da zero",
            "F10 / Esc: esci",
            "",
            f"Versione MAME rilevata: {self.mame_version}",
            "Avvia con il parametro -debug per generare un log dettagliato",
            "",
            "Premi un tasto per tornare...",
        ]
        stdscr.erase()
        stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))
        for i, line in enumerate(lines):
            stdscr.addstr(2 + i, 4, line, curses.color_pair(COLOR_NORMAL))
        stdscr.refresh()
        stdscr.getch()

    # -- loop principale -------------------------------------------------

    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.apply_search()
        while True:
            self.draw()
            ch = self.stdscr.getch()

            if ch in (curses.KEY_UP,):
                if self.selected > 0:
                    self.selected -= 1
            elif ch in (curses.KEY_DOWN,):
                if self.selected < len(self.filtered) - 1:
                    self.selected += 1
            elif ch == curses.KEY_PPAGE:
                self.selected = max(0, self.selected - 10)
            elif ch == curses.KEY_NPAGE:
                self.selected = min(len(self.filtered) - 1, self.selected + 10) if self.filtered else 0
            elif ch == curses.KEY_HOME:
                self.selected = 0
            elif ch == curses.KEY_END:
                self.selected = max(0, len(self.filtered) - 1)
            elif ch in (curses.KEY_ENTER, 10, 13):
                self.launch_selected()
            elif ch == curses.KEY_F1:
                self.show_help()
            elif ch == curses.KEY_F5:
                return "refresh_new"
            elif ch == curses.KEY_F6:
                return "refresh_full"
            elif ch in (curses.KEY_F10, 27):  # F10 o Esc
                return "quit"
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self.search = self.search[:-1]
                self.apply_search()
            elif 32 <= ch <= 126:
                self.search += chr(ch)
                self.apply_search()


# --------------------------------------------------------------------------
# Avvio / pipeline principale
# --------------------------------------------------------------------------

def draw_info_screen(stdscr, lines: List[str]):
    """Come draw_error_screen ma con i colori normali: per messaggi
    informativi (es. esito di un aggiornamento), non errori."""
    stdscr.clear()
    stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))
    h, w = stdscr.getmaxyx()
    for i, line in enumerate(lines):
        if i + 2 < h:
            stdscr.addstr(2 + i, 2, line[: w - 4], curses.color_pair(COLOR_NORMAL))
    stdscr.addstr(h - 2, 2, "Premi un tasto per continuare...", curses.color_pair(COLOR_NORMAL))
    stdscr.refresh()
    stdscr.getch()


def scan_and_cache(stdscr, roms_dir: str) -> Tuple[List[Game], str]:
    """RICOSTRUZIONE COMPLETA (tasto F6): rifa' la scansione via mame.exe
    di TUTTE le ROM presenti in ROMS e riscrive da zero la cache
    MameCommander.db. Ritorna (giochi, versione_mame)."""
    def progress_cb(msg):
        draw_progress(stdscr, msg)

    draw_progress(stdscr, "Scansione completa cartella ROMS...")
    rom_names = scan_rom_files(roms_dir)
    if not rom_names:
        return [], "sconosciuta"

    games, mame_version = build_game_list(rom_names, progress_cb)
    mame_version = mame_version or "sconosciuta"
    if games:
        # Non salviamo una scansione vuota: meglio ritentare al prossimo
        # avvio piuttosto che bloccare l'utente su una cache vuota.
        draw_progress(stdscr, "Aggiornamento database...")
        save_cache_to_db(DB_PATH, games, mame_version)
    return games, mame_version


def scan_new_only(
    stdscr, roms_dir: str, existing_games: List[Game], existing_version: str
) -> Tuple[List[Game], str, int]:
    """RICERCA SOLO NUOVI GIOCHI (tasto F5): confronta i file in ROMS con
    quelli gia' presenti nel database e interroga mame.exe SOLO per i nomi
    nuovi, senza ritoccare le righe gia' verificate. Molto piu' veloce di
    una scansione completa quando si aggiungono poche ROM alla volta.

    ATTENZIONE (accettato esplicitamente dall'utente): questa modalita' non
    si accorge delle ROM rimosse dalla cartella ROMS, che restano in lista
    finche' non si fa una ricostruzione completa (F6).

    Ritorna (giochi_totali, versione_mame, numero_nuovi_trovati).
    """
    draw_progress(stdscr, "Ricerca nuove ROM...")
    existing_names = {g.name for g in existing_games}
    rom_names = scan_rom_files(roms_dir)
    new_names = [n for n in rom_names if n not in existing_names]

    if not new_names:
        return existing_games, existing_version, 0

    def progress_cb(msg):
        draw_progress(stdscr, msg)

    new_games, mame_version = build_game_list(new_names, progress_cb)
    mame_version = mame_version or existing_version or "sconosciuta"

    if not new_games:
        return existing_games, existing_version, 0

    merged = existing_games + new_games
    merged.sort(key=lambda g: g.display_name.lower())
    draw_progress(stdscr, "Aggiornamento database...")
    save_cache_to_db(DB_PATH, merged, mame_version)
    return merged, mame_version, len(new_games)


def main(stdscr):
    init_colors()
    curses.curs_set(0)

    # 1. mame.exe presente?
    if not os.path.isfile(MAME_EXE):
        draw_error_screen(
            stdscr,
            [
                "ERRORE: mame.exe non trovato.",
                f"Percorso atteso: {MAME_EXE}",
                "Copia questo eseguibile nella stessa cartella di mame.exe e riprova.",
            ],
        )
        return

    # 2. cartella ROMS presente?
    roms_dir = find_roms_dir()
    if roms_dir is None:
        draw_error_screen(
            stdscr,
            [
                "ERRORE: cartella ROMS non trovata.",
                f"Cercata in: {APP_DIR} (nomi provati: roms, ROMS, ROM, rom)",
                "Crea la cartella ROMS accanto a mame.exe e mettici i romset.",
            ],
        )
        return

    # 3. Se esiste gia' MameCommander.db, usiamolo (avvio istantaneo, senza
    #    richiamare mame.exe). Altrimenti facciamo la scansione completa e
    #    lo creiamo.
    draw_progress(stdscr, "Verifica database...")
    cached = load_cache_from_db(DB_PATH)
    if cached is not None and cached[0]:
        games, mame_version = cached
    else:
        games, mame_version = scan_and_cache(stdscr, roms_dir)

    while True:
        if not games:
            draw_error_screen(
                stdscr,
                [
                    "Nessun gioco avviabile trovato.",
                    "Verifica che i file in ROMS siano romset MAME validi",
                    "(non BIOS-only) e compatibili con la versione di mame.exe.",
                ],
            )
            return

        app = App(stdscr, games, mame_version)
        action = app.run()

        if action == "quit":
            return

        elif action == "refresh_new":
            games, mame_version, new_count = scan_new_only(stdscr, roms_dir, games, mame_version)
            if new_count > 0:
                draw_info_screen(
                    stdscr,
                    [
                        f"Trovati {new_count} nuovi giochi.",
                        "Database aggiornato (le voci gia' presenti non sono state ritoccate).",
                    ],
                )
            else:
                draw_info_screen(
                    stdscr,
                    [
                        "Nessun nuovo gioco trovato.",
                        "La lista era gia' aggiornata.",
                    ],
                )

        elif action == "refresh_full":
            games, mame_version = scan_and_cache(stdscr, roms_dir)


if __name__ == "__main__":
    curses.wrapper(main)
