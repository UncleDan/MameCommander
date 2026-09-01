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
     con il nome completo.

Pensato per essere compilato con PyInstaller in un unico eseguibile:
    pyinstaller --onefile --console --name MameCommander MameCommander.py

Su Windows serve il pacchetto 'windows-curses' (vedi requirements.txt).
"""

APP_NAME = "MameCommander"
APP_VERSION = "1.0"

import curses
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional

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

DEBUG_LOG_PATH = os.path.join(APP_DIR, "MameCommander_debug.log")


def _log_debug(section: str, command: List[str], output: str):
    """Scrive un log dettagliato di ogni chiamata a mame.exe, per diagnosticare
    problemi di parsing con versioni di MAME dal comportamento inatteso."""
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


def _sanitize_entities(fragment: str) -> str:
    """Corregge il bug piu' comune delle vecchie liste XML di MAME: un
    carattere '&' non seguito da un'entita' valida (es. "Rock & Roll")
    che rende l'XML non ben formato."""
    return re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", fragment)


def fetch_machine_info(rom_names: List[str], progress_cb=None) -> Dict[str, Game]:
    """
    Usa 'mame.exe -listxml <nome>' UNA VOLTA PER OGNI ROM, per lo stesso
    motivo di compatibilita' spiegato in verify_roms(): le versioni vecchie
    di MAME non accettano piu' nomi sulla stessa riga di comando.
    Ottiene: descrizione completa, se e' un BIOS, se e' un device, se e'
    eseguibile.
    """
    games: Dict[str, Game] = {}
    total = len(rom_names)
    total_found = 0
    for i, name in enumerate(rom_names, 1):
        if progress_cb:
            progress_cb(f"Lettura informazioni MAME: {name} ({i}/{total})")
        out = _run_mame(["-listxml", name])

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
        f"Blocchi <machine>/<game> trovati e interpretati in totale: {total_found} su {total} rom richieste.",
    )
    return games


def scan_rom_files(roms_dir: str) -> List[str]:
    names = []
    for entry in os.scandir(roms_dir):
        if entry.is_file():
            base, ext = os.path.splitext(entry.name)
            if ext.lower() in ROM_EXTENSIONS:
                names.append(base)
    return sorted(set(names))


def build_game_list(rom_names: List[str], progress_cb=None) -> List[Game]:
    """Pipeline completa: verifica integrita' + info da MAME, poi filtro."""
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
        return []

    infos = fetch_machine_info(ok_names, progress_cb)
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
    return playable


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
    def __init__(self, stdscr, games: List[Game]):
        self.stdscr = stdscr
        self.games = games
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
        title = f" {APP_NAME} {APP_VERSION} - {len(self.filtered)} giochi disponibili "
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
        status = f" Cerca: {self.search}" if self.search else " Digita per cercare, F5 aggiorna"
        stdscr.addstr(h - 2, 0, status.ljust(w)[: w - 1], curses.color_pair(COLOR_NORMAL))

        # Barra tasti funzione
        funckeys = " F1 Aiuto  F5 Aggiorna  Invio Avvia  F10/Esc Esci "
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
        self.stdscr.clear()
        curses.reset_prog_mode()
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
            "F5: rifai la scansione di ROMS e riverifica",
            "F10 / Esc: esci",
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
                return "refresh"
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

def load_games_with_ui(stdscr, roms_dir: str) -> List[Game]:
    def progress_cb(msg):
        draw_progress(stdscr, msg)

    draw_progress(stdscr, "Scansione cartella ROMS...")
    rom_names = scan_rom_files(roms_dir)
    if not rom_names:
        return []
    return build_game_list(rom_names, progress_cb)


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

    while True:
        games = load_games_with_ui(stdscr, roms_dir)
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

        app = App(stdscr, games)
        action = app.run()
        if action == "quit":
            return
        # action == "refresh": ricomincia il ciclo (rilegge tutto)


if __name__ == "__main__":
    curses.wrapper(main)
