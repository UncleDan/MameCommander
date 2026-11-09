#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# MameCommander.py by Daniele Lolli (UncleDan) feat. Claude AI - Release 1.3 - 2026-11-08 23-20-33
#
# MameCommander - frontend per MAME in stile Norton Commander
# Copyright (c) 2026 Daniele Lolli
#
# Distribuito con licenza MIT: vedi il file LICENSE.
# Puoi usarlo, modificarlo e ridistribuirlo liberamente, anche a scopo
# commerciale; l'unico obbligo e' conservare la nota di copyright qui
# sopra e il testo della licenza.
#
# SPDX-License-Identifier: MIT
#
# ---------------------------------------------------------------------------
# NOTA SU MAME
#
# Questo e' un semplice programma di utilita': si limita a elencare i
# romset presenti e a richiamare l'eseguibile di MAME. Non contiene
# codice di MAME, non lo modifica e non ne fa parte in alcun modo.
#
# L'autore NON e' in alcun modo affiliato al progetto MAME ne' al suo
# team di sviluppo.
#
# Tutto il merito del lavoro vero - decenni di reverse engineering,
# documentazione e preservazione di migliaia di macchine arcade - va al
# fantastico team di sviluppo di MAME e a chi vi ha contribuito.
# Senza il loro lavoro questo frontend non avrebbe alcun senso di esistere.
#
# MAME e' un marchio e un progetto indipendente: https://www.mamedev.org/
# ---------------------------------------------------------------------------
"""
MameCommander - frontend per MAME in stile Norton Commander
=============================================================

Frontend testuale monolitico per MAME:
  1. Individua l'eseguibile di MAME (mame/mame.exe), accanto a questo
     programma oppure nel PATH di sistema.
  2. Legge la cartella delle ROM e raccoglie tutti i file .zip/.7z
     presenti. La cerca accanto al programma, nel 'rompath' di mame.ini
     o in ~/.mame/roms.
  3. Interroga MAME stesso per sapere:
       - quali romset sono integri ("-verifyroms")
       - quali sono BIOS, quali non sono eseguibili (slot/device),
         e qual e' il nome completo ("-listxml")
  4. Mostra in un'interfaccia a pannello singolo, stile Norton Commander,
     solo i giochi realmente avviabili (non BIOS, non device, romset OK),
     con il nome completo e la versione di MAME rilevata.
  5. Salva i risultati in un database SQLite (MameCommander.db, nella
     stessa cartella del programma) per gli avvii successivi: se il
     file esiste viene usato direttamente (avvio istantaneo, senza
     richiamare MAME), altrimenti viene creato. Da dentro l'app, F5
     cerca solo le ROM nuove e F6 ricostruisce il database da zero.

Parametri: "-newconsole" avvia MAME in una finestra di console propria
invece che in quella del frontend (di norma non serve).

Debug: avviare con il parametro "-debug" per generare un log dettagliato
(MameCommander_debug.log) di ogni chiamata a MAME. Senza questo
parametro nessun log viene creato.

FUNZIONA SU WINDOWS E SU LINUX con lo stesso identico sorgente.

  - Linux: si esegue direttamente, senza compilare e senza installare
    nulla (curses e sqlite3 fanno parte della libreria standard):
        ./mamecommander
  - Windows: serve il pacchetto 'windows-curses' (vedi requirements.txt),
    e conviene compilarlo in un unico .exe con PyInstaller:
        pyinstaller --onefile --console --name MameCommander MameCommander.py

Licenza: MIT (vedi il file LICENSE distribuito insieme a questo file).
"""

APP_NAME = "MameCommander"
APP_VERSION = "1.3"

import configparser
import curses
import os
import re
import zipfile
import shutil
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
# "non verificato": il romset non e' stato controllato (nessun DAT
# disponibile, oppure archivio .7z che la libreria standard non sa
# aprire). Lo si considera avviabile, segnalandolo in lista con "?":
# meglio lasciar provare che escludere a priori un gioco che funziona.
STATUS_UNVERIFIED = "non verificato"
STATUS_OK = ("good", "best available", STATUS_UNVERIFIED)


def app_dir() -> str:
    """Cartella dove si trova l'eseguibile (o lo script, se non compilato)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()
DB_PATH = os.path.join(APP_DIR, f"{APP_NAME}.db")  # cache dei giochi, stessa cartella dell'eseguibile

# Nomi possibili dell'eseguibile di MAME, in ordine di preferenza.
# Su Windows ha estensione .exe; su Linux/macOS no, e le build a 64 bit
# di qualche anno fa si chiamavano "mame64".
if os.name == "nt":
    MAME_EXE_CANDIDATES = ["mame.exe", "mame64.exe"]
else:
    MAME_EXE_CANDIDATES = ["mame", "mame64"]


def find_mame_exe() -> Optional[str]:
    """Cerca l'eseguibile di MAME, prima accanto al frontend e poi nel PATH.

    Su Windows MAME e' quasi sempre una cartella autonoma, quindi lo si
    trova accanto a noi. Su Linux invece e' di solito installato dalla
    distribuzione (/usr/bin/mame, /usr/games/mame...): in quel caso non
    e' nella nostra cartella e va cercato nel PATH.
    """
    for name in MAME_EXE_CANDIDATES:
        p = os.path.join(APP_DIR, name)
        if os.path.isfile(p):
            return p
    for name in MAME_EXE_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


MAME_EXE = find_mame_exe()


# --------------------------------------------------------------------------
# Configurazione facoltativa: MameCommander.ini
# --------------------------------------------------------------------------
#
# Di norma non serve: il programma trova da solo MAME o RetroArch. Il file
# serve quando sono presenti ENTRAMBI e si vuole scegliere quale usare, o
# quando i file stanno in posizioni non standard. Esempio completo nel file
# MameCommander.ini.example incluso nel progetto.
#
# Nome volutamente diverso da X-MameCommander.ini, che appartiene a
# X-Launcher di winPenPack e non c'entra con questa configurazione.

CONFIG_PATH = os.path.join(APP_DIR, f"{APP_NAME}.ini")
CONFIG_KEYS = ("engine", "retroarch", "core", "dat", "roms")


def _carica_config() -> Dict[str, str]:
    """Legge MameCommander.ini, se esiste. I percorsi relativi vengono
    risolti rispetto alla cartella del programma, cosi' la configurazione
    resta valida anche spostando l'intera cartella (es. su una chiavetta)."""
    risultato: Dict[str, str] = {}
    if not os.path.isfile(CONFIG_PATH):
        return risultato
    cp = configparser.ConfigParser()
    try:
        cp.read(CONFIG_PATH, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return risultato
    if not cp.has_section(APP_NAME):
        return risultato
    for chiave in CONFIG_KEYS:
        valore = cp.get(APP_NAME, chiave, fallback="").strip().strip('"')
        if not valore:
            continue
        if chiave != "engine":
            valore = os.path.expanduser(valore)
            if not os.path.isabs(valore):
                valore = os.path.normpath(os.path.join(APP_DIR, valore))
        else:
            valore = valore.lower()
        risultato[chiave] = valore
    return risultato


def _engine_da_riga_di_comando() -> Optional[str]:
    """Legge "-engine mame" o "-engine retroarch" dagli argomenti. Ha la
    precedenza sul file di configurazione, cosi' lo si puo' impostare anche
    dal campo Parameters di X-Launcher senza toccare altro."""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a.lower() in ("-engine", "--engine") and i + 1 < len(args):
            return args[i + 1].lower()
        if a.lower().startswith(("-engine=", "--engine=")):
            return a.split("=", 1)[1].lower()
    return None


CONFIG = _carica_config()
_engine_cli = _engine_da_riga_di_comando()
if _engine_cli:
    CONFIG["engine"] = _engine_cli


# --------------------------------------------------------------------------
# Motori di emulazione: MAME classico oppure RetroArch + MAME 2003-Plus
# --------------------------------------------------------------------------

if os.name == "nt":
    RETROARCH_EXE_NAMES = ["retroarch.exe"]
    CORE_FILE_NAME = "mame2003_plus_libretro.dll"
else:
    RETROARCH_EXE_NAMES = ["retroarch"]
    CORE_FILE_NAME = "mame2003_plus_libretro.so"

DAT_FILE_NAME = "mame2003-plus.xml"


@dataclass
class Engine:
    """Il programma che avvia effettivamente i giochi.

    kind = "mame"       mame.exe classico, interrogabile con -verifyroms e
                        -listxml per sapere quali romset sono utilizzabili.
    kind = "retroarch"  RetroArch con il core MAME 2003-Plus. RetroArch non
                        si puo' interrogare in quel modo: titoli e stato dei
                        romset si ricavano dal file DAT del core (vedi
                        load_dat), che e' anche piu' veloce.
    """
    kind: str
    exe: str
    workdir: str
    core: Optional[str] = None

    @property
    def label(self) -> str:
        return "MAME" if self.kind == "mame" else "MAME 2003-Plus (RetroArch)"

    def command_for(self, rom_name: str, rom_path: Optional[str]) -> List[str]:
        """Riga di comando per avviare un gioco.

        MAME vuole il NOME del romset e cerca il file da se'; RetroArch
        vuole invece il PERCORSO COMPLETO del file, perche' non conosce la
        cartella delle ROM.
        """
        if self.kind == "retroarch":
            return [self.exe, "-L", self.core, rom_path or rom_name]
        return [self.exe, rom_name]


def _cartelle_retroarch_candidate() -> List[str]:
    """Dove cercare un RetroArch portatile: accanto al programma, in una
    sottocartella RetroArch, oppure in una cartella RetroArch allo stesso
    livello (disposizione tipica delle raccolte portatili come winPenPack,
    con ogni programma in una sua cartella dentro Bin)."""
    padre = os.path.dirname(APP_DIR)
    candidate = [
        APP_DIR,
        os.path.join(APP_DIR, "RetroArch"),
        os.path.join(APP_DIR, "retroarch"),
        os.path.join(padre, "RetroArch"),
        os.path.join(padre, "retroarch"),
    ]
    if os.name != "nt":
        candidate.append(os.path.expanduser("~/.config/retroarch"))
    return candidate


def find_retroarch() -> Optional[Engine]:
    """Cerca RetroArch e il core MAME 2003-Plus. Servono ENTRAMBI: RetroArch
    senza il core non saprebbe avviare i giochi arcade, e viceversa."""
    exe = None
    configurato = CONFIG.get("retroarch")
    if configurato:
        # Accettiamo sia il percorso dell'eseguibile sia quello della cartella.
        if os.path.isdir(configurato):
            for n in RETROARCH_EXE_NAMES:
                if os.path.isfile(os.path.join(configurato, n)):
                    exe = os.path.join(configurato, n)
                    break
        elif os.path.isfile(configurato):
            exe = configurato
    else:
        for cartella in _cartelle_retroarch_candidate():
            for n in RETROARCH_EXE_NAMES:
                p = os.path.join(cartella, n)
                if os.path.isfile(p):
                    exe = p
                    break
            if exe:
                break
        if exe is None:
            for n in RETROARCH_EXE_NAMES:
                trovato = shutil.which(n)
                if trovato:
                    exe = trovato
                    break
    if exe is None:
        return None

    ra_dir = os.path.dirname(os.path.abspath(exe))

    core = CONFIG.get("core")
    if core and not os.path.isfile(core):
        return None
    if not core:
        candidate = [os.path.join(ra_dir, "cores", CORE_FILE_NAME)]
        if os.name != "nt":
            candidate += [
                os.path.expanduser(f"~/.config/retroarch/cores/{CORE_FILE_NAME}"),
                f"/usr/lib/libretro/{CORE_FILE_NAME}",
                f"/usr/lib/x86_64-linux-gnu/libretro/{CORE_FILE_NAME}",
            ]
        core = next((c for c in candidate if os.path.isfile(c)), None)
    if core is None:
        return None

    return Engine(kind="retroarch", exe=exe, workdir=ra_dir, core=core)


def available_engines() -> Dict[str, Optional[Engine]]:
    """Tutti i motori presenti sul sistema, senza alcuna precedenza fra
    loro: quale usare lo decide l'utente (F9), non il programma."""
    return {
        "mame": Engine(kind="mame", exe=MAME_EXE, workdir=APP_DIR) if MAME_EXE else None,
        "retroarch": find_retroarch(),
    }


def forced_engine_kind() -> Tuple[Optional[str], str]:
    """Motore imposto da -engine o da MameCommander.ini. Ritorna
    (motore, errore). "auto" o nessun valore = nessuna imposizione: si usa
    la scelta fatta con F9."""
    scelta = CONFIG.get("engine", "auto")
    if scelta == "auto":
        return None, ""
    if scelta not in ENGINE_KINDS:
        return None, f"valore di 'engine' non valido: '{scelta}' (usare auto, mame o retroarch)"
    return scelta, ""


ENGINE_DESCRIPTIONS = {
    "mame": "MAME (mame.exe)",
    "retroarch": "MAME 2003-Plus (RetroArch)",
}


def engine_missing_reason(kind: str) -> str:
    if kind == "mame":
        return f"non trovato ({' o '.join(MAME_EXE_CANDIDATES)} accanto al programma o nel PATH)"
    return f"non trovato (servono retroarch e il core {CORE_FILE_NAME})"


def find_dat(engine: Engine, roms_dir: Optional[str]) -> Optional[str]:
    """Cerca il file DAT di MAME 2003-Plus (mame2003-plus.xml).

    Il core lo genera dal menu MAME ("Generate XML DAT") e lo salva nella
    cartella dei salvataggi di RetroArch, sotto mame2003-plus. Una copia
    si trova anche nel repository del core su GitHub, nella cartella
    metadata, ma non sempre aggiornata: meglio quella generata dal core
    che si usa davvero.
    """
    configurato = CONFIG.get("dat")
    if configurato:
        return configurato if os.path.isfile(configurato) else None

    candidate = [os.path.join(APP_DIR, DAT_FILE_NAME)]
    if engine.kind == "retroarch":
        for sotto in ("saves", "system", "savefiles"):
            candidate.append(os.path.join(engine.workdir, sotto, "mame2003-plus", DAT_FILE_NAME))
    if roms_dir:
        candidate += [
            os.path.join(roms_dir, DAT_FILE_NAME),
            os.path.join(roms_dir, "mame2003-plus", DAT_FILE_NAME),
        ]
    if os.name != "nt":
        for sotto in ("saves", "system"):
            candidate.append(os.path.expanduser(f"~/.config/retroarch/{sotto}/mame2003-plus/{DAT_FILE_NAME}"))
    return next((c for c in candidate if os.path.isfile(c)), None)


def rom_file_path(roms_dir: str, name: str) -> Optional[str]:
    """Percorso completo del file di un romset (serve a RetroArch, che a
    differenza di MAME non cerca le ROM da se')."""
    for ext in ROM_EXTENSIONS:
        for variante in (ext, ext.upper()):
            p = os.path.join(roms_dir, name + variante)
            if os.path.isfile(p):
                return p
    return None

# Il log di debug viene creato SOLO se l'app e' avviata con "-debug" (o
# "--debug"): normalmente non scrive nulla su disco.
DEBUG_ENABLED = any(a.lower() in ("-debug", "--debug") for a in sys.argv[1:])

# Con "-newconsole" MAME viene avviato in una finestra di console propria
# invece che in quella del frontend. Non e' il comportamento predefinito:
# vedi la nota in launch_selected().
NEW_CONSOLE = any(a.lower() in ("-newconsole", "--newconsole") for a in sys.argv[1:])

# Cartella ROMS: proviamo alcune varianti comuni di nome. Su Windows la
# differenza tra maiuscole e minuscole e' irrilevante, ma su Linux il
# filesystem le distingue, quindi provarle tutte serve davvero.
ROMS_DIR_CANDIDATES = ["roms", "ROMS", "ROM", "rom"]

# File di configurazione di MAME, da cui possiamo leggere il "rompath"
# quando le ROM non sono accanto al frontend (situazione tipica su Linux,
# dove stanno in ~/.mame/roms).
MAME_INI_CANDIDATES = [
    os.path.join(APP_DIR, "mame.ini"),
    os.path.expanduser("~/.mame/mame.ini"),
]

_ROMPATH_RE = re.compile(r"^\s*rompath\s+(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _rompaths_from_ini() -> List[str]:
    """Estrae le cartelle elencate in 'rompath' dentro mame.ini, se esiste.
    MAME accetta piu' percorsi separati da ';' (Windows) o ':' (Unix)."""
    paths: List[str] = []
    for ini in MAME_INI_CANDIDATES:
        if not os.path.isfile(ini):
            continue
        try:
            with open(ini, "r", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _ROMPATH_RE.finditer(text):
            raw = m.group(1).strip().strip('"')
            for part in re.split(r"[;:]" if os.name != "nt" else ";", raw):
                part = part.strip()
                if not part:
                    continue
                part = os.path.expanduser(part)
                if not os.path.isabs(part):
                    part = os.path.join(os.path.dirname(ini), part)
                paths.append(part)
    return paths


def find_roms_dir() -> Optional[str]:
    """Individua la cartella delle ROM. Ordine di ricerca:
    0. la voce "roms" di MameCommander.ini, se presente;
    1. una sottocartella accanto al frontend (roms/ROMS/ROM/rom);
    2. il 'rompath' dichiarato in mame.ini (locale o in ~/.mame);
    3. il percorso predefinito di MAME su Linux (~/.mame/roms).
    """
    configurata = CONFIG.get("roms")
    if configurata:
        # Indicata esplicitamente nella configurazione: vince su tutto.
        return configurata if os.path.isdir(configurata) else None
    for name in ROMS_DIR_CANDIDATES:
        p = os.path.join(APP_DIR, name)
        if os.path.isdir(p):
            return p
    for p in _rompaths_from_ini():
        if os.path.isdir(p):
            return p
    default_home = os.path.expanduser("~/.mame/roms")
    if os.path.isdir(default_home):
        return default_home
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
    # Scelta manuale dell'utente (F7), a TRE stati:
    #   None  = nessuna forzatura, vale il giudizio di MAME
    #   True  = bloccato a mano (anche se MAME lo direbbe avviabile)
    #   False = sbloccato a mano (anche se MAME lo direbbe inutilizzabile)
    # Serve un terzo stato perche' la forzatura deve poter andare in
    # entrambe le direzioni: un booleano non saprebbe distinguere "non
    # forzato" da "forzato a sbloccato".
    override: Optional[bool] = None

    @property
    def is_permanently_blocked(self) -> bool:
        """BIOS e device non sono giochi: non si avviano da soli, in nessun
        caso. Non e' un giudizio sullo stato del romset ma su cosa la voce
        e', quindi non e' sbloccabile nemmeno a mano."""
        return self.is_bios or self.is_device

    @property
    def is_playable(self) -> bool:
        """Vero se MAME considera il romset integro e avviabile.
        E' il solo giudizio di MAME, senza le forzature dell'utente."""
        return (
            not self.is_permanently_blocked
            and self.runnable
            and self.rom_status in STATUS_OK
        )

    @property
    def is_selectable(self) -> bool:
        """Vero se la voce puo' essere avviata dalla lista, tenendo conto
        sia del giudizio di MAME sia della forzatura manuale."""
        if self.is_permanently_blocked:
            return False
        if self.override is not None:
            return not self.override
        return self.is_playable

    @property
    def is_forced(self) -> bool:
        """Vero se lo stato attuale deriva da una forzatura manuale che
        contraddice il giudizio di MAME (utile da segnalare in lista)."""
        if self.override is None or self.is_permanently_blocked:
            return False
        return self.override == self.is_playable

    @property
    def block_reason_auto(self) -> str:
        """Perche' la voce sarebbe esclusa SENZA forzature manuali, cioe'
        il giudizio della verifica. Serve quando la si sblocca a forza, per
        dire cosa si sta scavalcando."""
        if not self.runnable:
            return "non riconosciuto"
        if self.rom_status == "bad":
            return "incompleto o corrotto"
        if self.rom_status == "not supported":
            return "non supportato"
        return f"non utilizzabile ({self.rom_status})"

    @property
    def block_reason(self) -> str:
        """Spiegazione breve del perche' una voce non e' selezionabile,
        da mostrare all'utente. Stringa vuota se e' selezionabile."""
        if self.is_selectable:
            return ""
        if self.is_bios:
            return "e' un BIOS, non un gioco avviabile"
        if self.is_device:
            return "e' un device/slot, non un gioco avviabile"
        if self.override is True:
            return "bloccato a mano"
        if not self.runnable:
            return "non riconosciuto da questa versione di MAME"
        if self.rom_status == "bad":
            return "romset incompleto o corrotto"
        if self.rom_status == "not supported":
            return "non supportato da questa versione di MAME"
        return f"romset non utilizzabile ({self.rom_status})"

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


# Riconosce l'intestazione storica che MAME stampa nel proprio messaggio
# d'uso, es. "M.A.M.E. v0.78b (Sep  1 2003) - Multiple Arcade Machine
# Emulator" oppure semplicemente "MAME v0.106u5". Cattura il numero di
# versione (con l'eventuale data tra parentesi).
_BANNER_RE = re.compile(
    r"(?:M\.A\.M\.E\.|MAME)\s*v?\.?\s*(\d+\.\d+[\w]*(?:\s*\([^)\n]*\))?)",
    re.IGNORECASE,
)


def get_mame_version_via_banner() -> Optional[str]:
    """Ultimo fallback, usato solo se anche '-version' non ha funzionato
    (versioni molto vecchie, es. MAME 0.78b, che non riconoscono quel
    flag e non hanno l'attributo "build" su -listxml).

    Si procede in due tentativi, dal piu' sicuro al piu' invasivo:

    1. 'mame -help': stampa il messaggio d'uso, con la versione in testa,
       senza aprire nulla. Funziona sulla gran parte delle versioni.
    2. Solo su Windows, come ultima risorsa, si esegue mame.exe SENZA
       argomenti: le versioni DOS/Windows antiche stampano il banner e
       terminano subito. Non lo facciamo su Linux perche' li' MAME e'
       moderno e, senza romset, aprirebbe la propria interfaccia grafica
       a tutto schermo invece di scrivere sul terminale (e comunque su
       quelle versioni la versione l'abbiamo gia' ricavata prima).
    """
    out = _run_mame(["-help"])
    m = _BANNER_RE.search(out)
    if m:
        return m.group(1).strip()

    if os.name != "nt":
        return None

    try:
        proc = subprocess.run(
            [MAME_EXE],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=5,
        )
        out = proc.stdout + "\n" + proc.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log_debug("Chiamata a mame senza argomenti (banner)", [str(MAME_EXE)], f"Fallita: {exc}")
        return None

    _log_debug("Chiamata a mame senza argomenti (banner)", [str(MAME_EXE)], out)
    m = _BANNER_RE.search(out)
    if m:
        return m.group(1).strip()
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


# --------------------------------------------------------------------------
# Verifica tramite file DAT (usata con RetroArch + MAME 2003-Plus)
# --------------------------------------------------------------------------

@dataclass
class DatRom:
    name: str
    crc: Optional[int]      # None se il DAT non riporta il CRC
    merge: Optional[str]    # nome nel set padre, se la ROM e' condivisa
    nodump: bool            # ROM mai estratta: non va cercata


@dataclass
class DatGame:
    game: Game
    romof: Optional[str]    # set da cui eredita ROM (padre o BIOS)
    roms: List[DatRom] = field(default_factory=list)


def load_dat(path: str) -> Tuple[Dict[str, DatGame], Optional[str]]:
    """Legge il DAT XML di MAME 2003-Plus. Ritorna (giochi, build).

    Il formato e' quello di -listxml (elementi <game> o <machine>, con le
    <rom> e i loro CRC), quindi riusiamo la stessa tolleranza verso gli
    '&' non escapati gia' necessaria per MAME 0.78b.
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        testo = fh.read()

    m = _BUILD_RE.search(testo[:2000])
    build = m.group(1).strip() if m else None

    giochi: Dict[str, DatGame] = {}
    for blocco in _ELEMENT_RE.finditer(testo):
        try:
            el = ET.fromstring(_sanitize_entities(blocco.group(0)))
        except ET.ParseError:
            continue
        nome = el.get("name")
        if not nome:
            continue
        desc_el = el.find("description")
        g = Game(
            name=nome,
            description=(desc_el.text or "").strip() if desc_el is not None else "",
            is_bios=el.get("isbios", "no").lower() == "yes",
            is_device=el.get("isdevice", "no").lower() == "yes",
            runnable=el.get("runnable", "yes").lower() != "no",
        )
        roms = []
        for r in el.findall("rom"):
            crc_txt = r.get("crc")
            try:
                crc = int(crc_txt, 16) if crc_txt else None
            except ValueError:
                crc = None
            stato = (r.get("status") or "").lower()
            roms.append(
                DatRom(
                    name=r.get("name", ""),
                    crc=crc,
                    merge=r.get("merge"),
                    nodump=(stato == "nodump"),
                )
            )
        giochi[nome] = DatGame(game=g, romof=el.get("romof"), roms=roms)

    return giochi, build


def _crc_nello_zip(path: str) -> Optional[set]:
    """Insieme dei CRC dei file contenuti in uno zip, letti dalla directory
    centrale dell'archivio: non serve decomprimere nulla, quindi e' molto
    veloce anche su collezioni grandi. Ritorna None se l'archivio non e'
    leggibile (corrotto, o in un formato che zipfile non gestisce)."""
    try:
        with zipfile.ZipFile(path) as zf:
            return {info.CRC for info in zf.infolist() if not info.is_dir()}
    except (zipfile.BadZipFile, OSError, NotImplementedError):
        return None


def verify_with_dat(
    rom_names: List[str],
    roms_dir: str,
    dat: Dict[str, DatGame],
    progress_cb=None,
) -> Dict[str, str]:
    """Verifica ogni romset confrontando i CRC richiesti dal DAT con quelli
    effettivamente presenti negli zip.

    Gestisce i set "split" e quelli con BIOS: una ROM puo' stare nello zip
    del gioco stesso oppure, se condivisa, in quello del padre o del BIOS
    (catena romof). Si cerca quindi lungo tutta la catena, come fa MAME.

    Stati restituiti: "good", "bad" (manca almeno una ROM o l'archivio e'
    illeggibile), STATUS_UNVERIFIED (archivio .7z, non apribile con la
    libreria standard), "sconosciuto" (nome assente dal DAT).
    """
    cache_crc: Dict[str, Optional[set]] = {}

    def crc_di(nome_set: str) -> Optional[set]:
        if nome_set not in cache_crc:
            percorso = rom_file_path(roms_dir, nome_set)
            if percorso is None or not percorso.lower().endswith(".zip"):
                cache_crc[nome_set] = None
            else:
                cache_crc[nome_set] = _crc_nello_zip(percorso)
        return cache_crc[nome_set]

    stati: Dict[str, str] = {}
    totale = len(rom_names)
    for i, nome in enumerate(rom_names, 1):
        if progress_cb:
            progress_cb(f"Verifica ROM (DAT): {nome} ({i}/{totale})")

        if nome not in dat:
            stati[nome] = "sconosciuto"
            continue

        percorso = rom_file_path(roms_dir, nome)
        if percorso and percorso.lower().endswith(".7z"):
            stati[nome] = STATUS_UNVERIFIED
            continue

        propri = crc_di(nome)
        if propri is None:
            stati[nome] = "bad"
            continue

        # Catena dei set da cui si possono ereditare ROM (padre, BIOS...),
        # con protezione contro eventuali cicli in un DAT malformato.
        catena = []
        visti = {nome}
        corrente = dat[nome].romof
        while corrente and corrente not in visti and corrente in dat:
            catena.append(corrente)
            visti.add(corrente)
            corrente = dat[corrente].romof

        completo = True
        for rom in dat[nome].roms:
            if rom.nodump or rom.crc is None:
                continue
            if rom.crc in propri:
                continue
            if any(rom.crc in (crc_di(a) or set()) for a in catena):
                continue
            completo = False
            break
        stati[nome] = "good" if completo else "bad"

    return stati


def build_game_list_dat(
    rom_names: List[str], roms_dir: str, dat_path: str, progress_cb=None
) -> Tuple[List[Game], Optional[str]]:
    """Come build_game_list, ma con il DAT al posto di mame.exe."""
    reset_debug_log()
    if progress_cb:
        progress_cb("Lettura del file DAT...")
    dat, build = load_dat(dat_path)
    _log_debug(
        "DAT caricato",
        [dat_path],
        f"Voci nel DAT: {len(dat)}, build: {build}\nROM nella cartella: {len(rom_names)}",
    )

    stati = verify_with_dat(rom_names, roms_dir, dat, progress_cb)

    giochi = []
    for nome in rom_names:
        if nome in dat:
            g = dat[nome].game
        else:
            # File presente ma sconosciuto al DAT: probabilmente un romset di
            # un'altra versione di MAME. Resta in lista, non avviabile.
            g = Game(name=nome, description="", runnable=False)
        g.rom_status = stati.get(nome, "sconosciuto")
        giochi.append(g)

    _log_debug(
        "Riepilogo finale (DAT)",
        ["(riepilogo)"],
        f"Voci: {len(giochi)}, selezionabili: {sum(1 for g in giochi if g.is_selectable)}",
    )
    giochi.sort(key=lambda g: g.display_name.lower())
    return giochi, build


def build_game_list_unverified(rom_names: List[str]) -> List[Game]:
    """Ultima risorsa: nessun DAT e nessun mame.exe. Si elencano i file con
    il loro nome, tutti avviabili ma segnati come non verificati. Meglio un
    elenco grezzo che funziona di uno schermo vuoto."""
    giochi = [Game(name=n, description="", rom_status=STATUS_UNVERIFIED) for n in rom_names]
    giochi.sort(key=lambda g: g.display_name.lower())
    return giochi


def build_game_list_for(
    engine: Engine, rom_names: List[str], roms_dir: str, progress_cb=None
) -> Tuple[List[Game], str, str]:
    """Sceglie la fonte delle informazioni in base al motore e ritorna
    (giochi, etichetta_versione, fonte).

    Con RetroArch l'ordine di preferenza e':
      1. il DAT di MAME 2003-Plus: e' la fonte esatta per quel core;
      2. mame.exe, se presente: MAME 2003-Plus deriva da MAME 0.78, quindi
         i giudizi di mame.exe sono un'approssimazione buona ma non
         perfetta (alcuni romset sono stati aggiornati o aggiunti);
      3. nessuna verifica, solo l'elenco dei file.
    """
    if engine.kind == "mame":
        giochi, versione = build_game_list(rom_names, progress_cb)
        return giochi, (versione or "sconosciuta"), "mame"

    dat_path = find_dat(engine, roms_dir)
    if dat_path:
        giochi, build = build_game_list_dat(rom_names, roms_dir, dat_path, progress_cb)
        etichetta = "2003-Plus (RetroArch)"
        return giochi, etichetta, "dat"

    if MAME_EXE:
        giochi, versione = build_game_list(rom_names, progress_cb)
        etichetta = "2003-Plus (RetroArch, verifica con MAME " + (versione or "?") + ")"
        return giochi, etichetta, "mame"

    return build_game_list_unverified(rom_names), "2003-Plus (RetroArch, ROM non verificate)", "nessuna"


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
        # Non usciamo piu' qui: anche se nessun romset e' integro, mostriamo
        # comunque l'elenco (tutto non selezionabile). E' molto piu' utile
        # di una schermata vuota, perche' si vede subito quali ROM ci sono
        # e perche' non sono utilizzabili.

    # Chiediamo il titolo a MAME per TUTTE le ROM, non solo per quelle
    # integre: le voci difettose restano visibili in grigio e devono
    # mostrare il nome completo del gioco, non solo il nome del file.
    infos, mame_version = fetch_machine_info(rom_names, progress_cb)
    if not mame_version:
        mame_version = get_mame_version_via_cli()
    if not mame_version:
        mame_version = get_mame_version_via_banner()
    _log_debug(
        "Riepilogo -listxml",
        ["(riepilogo)"],
        f"Romset con info recuperate da -listxml: {len(infos)} su {len(rom_names)} attesi.",
    )

    games = []
    for name in rom_names:
        game = infos.get(name)
        if game is None:
            # MAME non conosce questo nome: la ROM esiste come file ma non
            # corrisponde a nessun romset di questa versione. La teniamo in
            # lista, non selezionabile, col nome del file come titolo.
            game = Game(name=name, description="", runnable=False)
        game.rom_status = statuses.get(name, "sconosciuto")
        # BIOS e device restano in lista, ma bloccati in modo permanente:
        # vederli elencati chiarisce che il file c'e' ed e' stato
        # riconosciuto, evitando di cercarlo invano tra i giochi.
        games.append(game)

    selezionabili = sum(1 for g in games if g.is_selectable)
    bios = sum(1 for g in games if g.is_permanently_blocked)
    _log_debug(
        "Riepilogo finale",
        ["(riepilogo)"],
        f"Voci in lista: {len(games)}, "
        f"di cui selezionabili: {selezionabili}, "
        f"BIOS/device (blocco permanente): {bios}, "
        f"altre non selezionabili: {len(games) - selezionabili - bios}",
    )

    games.sort(key=lambda g: g.display_name.lower())
    return games, mame_version


# --------------------------------------------------------------------------
# Cache su SQLite (MameCommander.db, nella cartella dell'eseguibile)
# --------------------------------------------------------------------------

# Struttura del database (schema 3):
#
#   meta(key, value)        impostazioni globali e dati per motore:
#                             show_blocked           preferenza F8
#                             selected_engine        motore scelto con F9
#                             version.<motore>       versione rilevata
#                             sig.<motore>           firma della fonte
#                             updated_at.<motore>    data dell'ultima scansione
#   games_mame              cache dei giochi verificati con mame.exe
#   games_retroarch         cache dei giochi per RetroArch + MAME 2003-Plus
#   overrides(engine, name, override)  forzature manuali F7, PER MOTORE
#
# Una cache per motore evita di dover riscansionare tutto a ogni cambio
# con F9 (con MAME 0.78b, che va interrogato una ROM alla volta, sarebbero
# minuti). Anche le forzature F7 sono per motore: lo stesso romset puo'
# funzionare con un emulatore e non con l'altro (per esempio un set
# aggiornato da MAME 2003-Plus che MAME 0.78b non riconosce piu'), quindi
# sbloccarlo o bloccarlo per uno non deve toccare l'altro.

ENGINE_KINDS = ("mame", "retroarch")
_SCHEMA = "4"


def _tabella_giochi(kind: str) -> str:
    if kind not in ENGINE_KINDS:
        raise ValueError(f"motore sconosciuto: {kind}")
    return f"games_{kind}"


def _migra_schema_vecchio(conn: sqlite3.Connection) -> None:
    """Converte un database delle versioni 1.0/1.1 (un'unica tabella
    "games" con le forzature dentro) nello schema per motore, senza perdere
    ne' la cache ne' le scelte fatte con F7."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(games)")
    colonne = {r[1] for r in cur.fetchall()}
    if not colonne:
        return

    meta = dict(cur.execute("SELECT key, value FROM meta").fetchall())
    # In 1.1 "engine" conteneva la firma (es. "retroarch:dat"); in 1.0 non
    # c'era, e la cache era sempre calcolata con mame.exe.
    firma = meta.get("engine") or "mame:mame"
    kind = firma.split(":", 1)[0] if firma.split(":", 1)[0] in ENGINE_KINDS else "mame"

    def col(nome, predefinito):
        return nome if nome in colonne else predefinito

    QUOTED_GOOD = "'good'"   # valore SQL letterale per i DB senza rom_status

    righe = cur.execute(
        f"SELECT name, description, {col('rom_status', QUOTED_GOOD)}, "
        f"{col('runnable', '1')}, {col('is_bios', '0')}, {col('is_device', '0')} FROM games"
    ).fetchall()
    cur.executemany(
        f"INSERT OR REPLACE INTO {_tabella_giochi(kind)} "
        "(name, description, rom_status, runnable, is_bios, is_device) VALUES (?, ?, ?, ?, ?, ?)",
        righe,
    )

    if "override" in colonne:
        forz = cur.execute("SELECT name, override FROM games WHERE override IS NOT NULL").fetchall()
    elif "blocked" in colonne:
        forz = [(n, 1) for (n,) in cur.execute("SELECT name FROM games WHERE blocked = 1").fetchall()]
    else:
        forz = []
    # Nelle versioni precedenti le forzature valevano per qualunque motore:
    # le copiamo su entrambi, cosi' dopo l'aggiornamento non cambia nulla.
    # Da qui in avanti ciascuna si potra' modificare indipendentemente.
    cur.executemany(
        "INSERT OR REPLACE INTO overrides (engine, name, override) VALUES (?, ?, ?)",
        [(k, n, o) for k in ENGINE_KINDS for n, o in forz],
    )

    for chiave, valore in (
        (f"version.{kind}", meta.get("mame_version")),
        (f"sig.{kind}", firma),
        (f"updated_at.{kind}", meta.get("updated_at")),
    ):
        if valore:
            cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (chiave, valore))
    cur.execute("DELETE FROM meta WHERE key IN ('mame_version', 'updated_at', 'engine')")
    cur.execute("DROP TABLE games")


def _apri_db(db_path: str) -> sqlite3.Connection:
    """Apre il database creando le tabelle mancanti e migrando, se serve,
    quello di una versione precedente."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    for kind in ENGINE_KINDS:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {_tabella_giochi(kind)} ("
            "name TEXT PRIMARY KEY, description TEXT NOT NULL, "
            "rom_status TEXT NOT NULL DEFAULT 'good', runnable INTEGER NOT NULL DEFAULT 1, "
            "is_bios INTEGER NOT NULL DEFAULT 0, is_device INTEGER NOT NULL DEFAULT 0)"
        )
    colonne_forz = {r[1] for r in cur.execute("PRAGMA table_info(overrides)").fetchall()}
    if colonne_forz and "engine" not in colonne_forz:
        # Schema 3 (versione 1.2): forzature comuni a tutti i motori.
        # Stessa logica della migrazione piu' vecchia: si copiano su entrambi.
        cur.execute("ALTER TABLE overrides RENAME TO overrides_condivise")
        colonne_forz = set()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS overrides ("
        "engine TEXT NOT NULL, name TEXT NOT NULL, override INTEGER NOT NULL, "
        "PRIMARY KEY (engine, name))"
    )
    if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='overrides_condivise'").fetchone():
        vecchie = cur.execute("SELECT name, override FROM overrides_condivise").fetchall()
        cur.executemany(
            "INSERT OR REPLACE INTO overrides (engine, name, override) VALUES (?, ?, ?)",
            [(k, n, o) for k in ENGINE_KINDS for n, o in vecchie],
        )
        cur.execute("DROP TABLE overrides_condivise")
    if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='games'").fetchone():
        _migra_schema_vecchio(conn)
    cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)", (_SCHEMA,))
    conn.commit()
    return conn


def _get_meta(db_path: str, chiave: str) -> Optional[str]:
    if not os.path.isfile(db_path):
        return None
    try:
        conn = _apri_db(db_path)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (chiave,)).fetchone()
            return row[0] if row and row[0] is not None else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _set_meta(db_path: str, chiave: str, valore: str) -> bool:
    try:
        conn = _apri_db(db_path)
        try:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (chiave, valore))
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _carica_forzature(conn: sqlite3.Connection, kind: str) -> Dict[str, bool]:
    return {
        n: bool(o)
        for n, o in conn.execute("SELECT name, override FROM overrides WHERE engine = ?", (kind,)).fetchall()
    }


def apply_overrides(db_path: str, games: List[Game], kind: str) -> None:
    """Applica ai giochi le forzature F7 salvate. Si usa dopo ogni
    scansione: i giochi appena verificati non sanno nulla delle scelte
    dell'utente, che stanno in una tabella a parte."""
    if not os.path.isfile(db_path):
        return
    try:
        conn = _apri_db(db_path)
        try:
            forz = _carica_forzature(conn, kind)
        finally:
            conn.close()
    except sqlite3.Error:
        return
    for g in games:
        if g.name in forz:
            g.override = forz[g.name]


def load_cache_from_db(db_path: str, kind: str) -> Optional[Tuple[List[Game], str, Optional[str]]]:
    """Cache del motore indicato: (giochi, versione, firma della fonte),
    con le forzature F7 gia' applicate. None se non c'e' nulla di usabile."""
    if not os.path.isfile(db_path):
        return None
    try:
        conn = _apri_db(db_path)
        try:
            righe = conn.execute(
                "SELECT name, description, rom_status, runnable, is_bios, is_device "
                f"FROM {_tabella_giochi(kind)} ORDER BY description COLLATE NOCASE"
            ).fetchall()
            if not righe:
                return None
            forz = _carica_forzature(conn, kind)
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    giochi = [
        Game(
            name=n, description=d, rom_status=st, runnable=bool(ru),
            is_bios=bool(bi), is_device=bool(de), override=forz.get(n),
        )
        for n, d, st, ru, bi, de in righe
    ]
    return giochi, meta.get(f"version.{kind}") or "sconosciuta", meta.get(f"sig.{kind}")


def save_cache_to_db(db_path: str, kind: str, games: List[Game], version: str, sig: str) -> bool:
    """Riscrive la cache del SOLO motore indicato. La cache dell'altro
    motore, le forzature F7 e le preferenze restano intatte."""
    try:
        conn = _apri_db(db_path)
        try:
            tab = _tabella_giochi(kind)
            conn.execute(f"DELETE FROM {tab}")
            conn.executemany(
                f"INSERT INTO {tab} (name, description, rom_status, runnable, is_bios, is_device) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(g.name, g.description, g.rom_status, int(g.runnable), int(g.is_bios), int(g.is_device))
                 for g in games],
            )
            for chiave, valore in (
                (f"version.{kind}", version or "sconosciuta"),
                (f"sig.{kind}", sig),
                (f"updated_at.{kind}", time.strftime("%Y-%m-%d %H:%M:%S")),
            ):
                conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (chiave, valore))
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False  # la cache e' un extra: se fallisce, l'app continua a funzionare


def get_show_blocked(db_path: str, default: bool = True) -> bool:
    """Preferenza F8. Predefinito: mostrare tutto, l'impostazione meno
    sorprendente al primo avvio."""
    v = _get_meta(db_path, "show_blocked")
    return default if v is None else v == "1"


def set_show_blocked_in_db(db_path: str, show_blocked: bool) -> bool:
    return _set_meta(db_path, "show_blocked", "1" if show_blocked else "0")


def get_selected_engine(db_path: str) -> Optional[str]:
    """Motore scelto l'ultima volta con F9 (o alla prima richiesta)."""
    v = _get_meta(db_path, "selected_engine")
    return v if v in ENGINE_KINDS else None


def set_selected_engine(db_path: str, kind: str) -> bool:
    return _set_meta(db_path, "selected_engine", kind)


def set_override_in_db(db_path: str, kind: str, name: str, override: Optional[bool]) -> bool:
    """Salva la forzatura F7 di un gioco per il SOLO motore indicato.
    None la rimuove (si torna al giudizio automatico di quel motore)."""
    try:
        conn = _apri_db(db_path)
        try:
            if override is None:
                conn.execute("DELETE FROM overrides WHERE engine = ? AND name = ?", (kind, name))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO overrides (engine, name, override) VALUES (?, ?, ?)",
                    (kind, name, int(override)),
                )
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------
# Interfaccia testuale stile Norton Commander
# --------------------------------------------------------------------------

COLOR_NORMAL = 1
COLOR_SELECTED = 2
COLOR_TITLE = 3
COLOR_ERROR = 4
COLOR_FUNCKEYS = 5
# Voci non selezionabili: stesso sfondo, testo attenuato.
COLOR_DIMMED = 6
# Voce non selezionabile ma sotto il cursore: deve restare distinguibile
# sia dalle voci normali sia dalle selezionabili sotto il cursore.
COLOR_DIMMED_SELECTED = 7


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_NORMAL, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COLOR_TITLE, curses.COLOR_YELLOW, curses.COLOR_BLUE)
    curses.init_pair(COLOR_ERROR, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(COLOR_FUNCKEYS, curses.COLOR_BLACK, curses.COLOR_CYAN)
    # Le voci non selezionabili usano il ciano su blu invece del bianco:
    # sullo stesso sfondo risulta nettamente piu' spento, senza diventare
    # illeggibile. Il grigio "vero" (COLOR_BLACK + A_BOLD) su blu risulta
    # troppo scuro su parecchi terminali, quindi si preferisce questo.
    curses.init_pair(COLOR_DIMMED, curses.COLOR_CYAN, curses.COLOR_BLUE)
    curses.init_pair(COLOR_DIMMED_SELECTED, curses.COLOR_BLUE, curses.COLOR_CYAN)


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
    def __init__(
        self,
        stdscr,
        games: List[Game],
        mame_version: str = "sconosciuta",
        show_blocked: bool = True,
        engine: Optional[Engine] = None,
        roms_dir: Optional[str] = None,
        engine_lock: str = "",
    ):
        self.stdscr = stdscr
        self.games = games
        self.mame_version = mame_version
        self.engine = engine or Engine(kind="mame", exe=MAME_EXE or "mame", workdir=APP_DIR)
        self.roms_dir = roms_dir
        # Se non vuoto, il motore e' imposto dall'esterno e F9 mostra questo
        # messaggio invece di aprire la scelta.
        self.engine_lock = engine_lock
        # Se mostrare anche le voci non selezionabili (BIOS, ROM difettose,
        # voci bloccate a mano). Si commuta con F8 e viene salvato nel
        # database, cosi' l'elenco si ripresenta come lo si e' lasciato.
        self.show_blocked = show_blocked
        self.filtered: List[Game] = []
        self.selected = 0
        self.top = 0
        self.search = ""
        self.search_time = 0.0
        # Messaggio temporaneo mostrato nella barra di stato (esito di F7,
        # motivo per cui una voce non parte, ecc.). Si azzera al tasto dopo.
        self.message = ""
        self.apply_search()

    # -- disegno -----------------------------------------------------------

    def draw(self):
        stdscr = self.stdscr
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))

        # Titolo: distinguiamo i giochi avviabili dal totale delle voci,
        # altrimenti il conteggio diventerebbe fuorviante ora che in lista
        # compaiono anche quelle non selezionabili.
        avviabili = sum(1 for g in self.filtered if g.is_selectable)
        non_sel = len(self.games) - sum(1 for g in self.games if g.is_selectable)
        if not non_sel:
            conteggio = f"{avviabili} giochi disponibili"
        elif self.show_blocked:
            conteggio = f"{avviabili} avviabili, {non_sel} non selezionabili"
        else:
            conteggio = f"{avviabili} avviabili ({non_sel} nascosti)"
        title = f" {APP_NAME} {APP_VERSION} - MAME {self.mame_version} - {conteggio} "
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

            # Marcatore a inizio riga: uno sguardo basta a capire lo stato
            # senza dover interpretare le sfumature di colore, che su alcuni
            # terminali si distinguono male.
            if game.is_permanently_blocked:
                marker = "B"          # BIOS o device: mai avviabile
            elif game.override is True:
                marker = "x"          # bloccato a mano
            elif game.override is False:
                marker = "+"          # sbloccato a mano (forzatura)
            elif not game.is_playable:
                marker = "!"          # difettoso secondo MAME
            elif game.rom_status == STATUS_UNVERIFIED:
                marker = "?"          # avviabile, ma non e' stato possibile verificarlo
            else:
                marker = " "
            # Nome del romset fra parentesi QUADRE: moltissimi titoli MAME
            # contengono gia' parentesi tonde (regione, versione, set), e
            # usarle anche qui renderebbe difficile capire dove finisce il
            # titolo e dove inizia il nome del file.
            text = f" {marker} {game.display_name} [{game.name}]"
            text = text.ljust(w - 1)[: w - 1]

            if game.is_selectable:
                attr = (
                    curses.color_pair(COLOR_SELECTED)
                    if idx == self.selected
                    else curses.color_pair(COLOR_NORMAL)
                )
            else:
                attr = (
                    curses.color_pair(COLOR_DIMMED_SELECTED)
                    if idx == self.selected
                    else curses.color_pair(COLOR_DIMMED)
                )
            stdscr.addstr(y, 0, text, attr)

        # Barra di stato
        if self.message:
            status = f" {self.message}"
        elif self.search:
            status = f" Cerca: {self.search}"
        else:
            vista = "visibili" if self.show_blocked else "nascosti"
            status = f" Digita per cercare  |  non selezionabili: {vista} (F8)"
        stdscr.addstr(h - 2, 0, status.ljust(w)[: w - 1], curses.color_pair(COLOR_NORMAL))

        # Barra tasti funzione
        funckeys = (
            " F1 Aiuto F5 Nuovi F6 Ricostr F7 Blocca F8 Nascondi F9 Motore F10 Esci "
        )
        stdscr.addstr(h - 1, 0, funckeys.ljust(w)[: w - 1], curses.color_pair(COLOR_FUNCKEYS))

        stdscr.refresh()

    # -- ricerca incrementale ------------------------------------------------

    def apply_search(self):
        """Ricostruisce la lista visibile applicando, nell'ordine: il filtro
        mostra/nascondi non selezionabili (F8) e il testo cercato."""
        base = self.games if self.show_blocked else [g for g in self.games if g.is_selectable]
        if not self.search:
            self.filtered = base
        else:
            s = self.search.lower()
            self.filtered = [g for g in base if s in g.display_name.lower() or s in g.name.lower()]
        self.selected = 0
        self.top = 0

    def refresh_view(self, keep_game: Optional[Game] = None):
        """Come apply_search, ma cerca di mantenere il cursore sullo stesso
        gioco. Serve dopo F7/F8, dove la lista puo' cambiare sotto i piedi e
        far saltare la selezione all'inizio sarebbe fastidioso."""
        self.apply_search()
        if keep_game is not None:
            for i, g in enumerate(self.filtered):
                if g.name == keep_game.name:
                    self.selected = i
                    break

    # -- azioni --------------------------------------------------------------

    def toggle_blocked(self):
        """F7: forza a mano lo stato del gioco selezionato.

        Se e' selezionabile lo blocca; se non lo e' lo sblocca, anche
        quando e' MAME a considerarlo difettoso: la forzatura vale in
        entrambe le direzioni, cosi' si puo' comunque tentare l'avvio di
        un romset che MAME giudica incompleto (a volte parte lo stesso).

        Unica eccezione: BIOS e device, che non sono giochi e non si
        avviano in nessun caso. Li' il tasto rifiuta e lo spiega.
        """
        if not self.filtered:
            return
        game = self.filtered[self.selected]

        if game.is_permanently_blocked:
            cosa = "un BIOS" if game.is_bios else "un device/slot"
            self.message = f"'{game.display_name}' e' {cosa}: non e' sbloccabile."
            return

        vuole_bloccare = game.is_selectable
        stato_voluto = not vuole_bloccare  # True = deve diventare selezionabile

        # Se lo stato voluto coincide gia' con il giudizio della verifica non serve
        # memorizzare nessuna forzatura: si torna allo stato automatico,
        # cosi' una futura riscansione potra' aggiornarlo liberamente.
        if stato_voluto == game.is_playable:
            game.override = None
        else:
            game.override = not stato_voluto

        salvato = set_override_in_db(DB_PATH, self.engine.kind, game.name, game.override)

        # Si specifica sempre il motore: la stessa voce con l'altro motore
        # resta com'era, e senza dirlo sembrerebbe un comportamento
        # incoerente passando da uno all'altro con F9.
        motore = "MAME" if self.engine.kind == "mame" else "RetroArch"
        if vuole_bloccare:
            esito = f"bloccato per {motore}"
        elif not game.is_playable:
            # Il giudizio "difettoso" puo' venire da mame.exe o dal DAT di
            # MAME 2003-Plus: non si nomina la fonte, si dice cosa comporta.
            esito = f"sbloccato a forza per {motore}: risulta {game.block_reason_auto}, l'avvio potrebbe fallire"
        else:
            esito = f"sbloccato per {motore}"

        if salvato:
            self.message = f"'{game.display_name}' {esito}."
        else:
            # Onesti sull'esito: se il database non e' scrivibile la scelta
            # vale solo finche' l'app resta aperta, ed e' bene saperlo.
            self.message = f"'{game.display_name}' {esito} - solo per questa sessione, database non aggiornabile."

        # Se la voce non deve piu' essere visibile, la lista si accorcia:
        # teniamo il cursore in una posizione valida.
        if not game.is_selectable and not self.show_blocked:
            posizione = self.selected
            self.apply_search()
            self.selected = min(posizione, max(0, len(self.filtered) - 1))
        else:
            self.refresh_view(keep_game=game)

    def toggle_show_blocked(self):
        """F8: mostra o nasconde le voci non selezionabili."""
        corrente = self.filtered[self.selected] if self.filtered else None
        self.show_blocked = not self.show_blocked
        self.refresh_view(keep_game=corrente)
        salvato = set_show_blocked_in_db(DB_PATH, self.show_blocked)
        nascosti = sum(1 for g in self.games if not g.is_selectable)
        stato = "mostrate" if self.show_blocked else "nascoste"
        if salvato:
            self.message = f"Voci non selezionabili {stato} ({nascosti})."
        else:
            self.message = (
                f"Voci non selezionabili {stato} ({nascosti}) "
                f"- solo per questa sessione: database non aggiornabile."
            )

    def launch_selected(self):
        if not self.filtered:
            return
        game = self.filtered[self.selected]

        # Voce non selezionabile: spieghiamo il motivo invece di limitarci
        # a ignorare il tasto, altrimenti sembrerebbe che l'app sia bloccata.
        if not game.is_selectable:
            if game.is_permanently_blocked:
                # Qui F7 non aiuterebbe: meglio non suggerirlo.
                self.message = f"'{game.display_name}' non avviabile: {game.block_reason}."
            else:
                self.message = (
                    f"'{game.display_name}' non avviabile: {game.block_reason}. "
                    f"F7 per sbloccarlo comunque."
                )
            return

        curses.def_prog_mode()
        curses.endwin()
        # Sovrascriviamo il testo residuo sulla console originale (es. il
        # messaggio "Avvio MameCommander..." di run.cmd/run_ps.ps1) con
        # un messaggio esplicito: resta visibile finche' il gioco e' aperto,
        # cosi' e' chiaro cosa sta girando e si evita di rilanciarne un altro
        # per errore mentre si e' ancora dentro la partita.
        print(f"{APP_NAME}: lancio ROM '{game.name}'...")
        try:
            # MAME viene avviato NELLA STESSA console del frontend.
            #
            # In precedenza si apriva una console separata
            # (CREATE_NEW_CONSOLE) per tentare di evitare il messaggio di
            # MAME 0.78b:
            #   "Unable to open the keyboard device. (error 32)"
            # Alla prova dei fatti quel messaggio compare lo stesso e i
            # giochi funzionano comunque, quindi la finestra in piu' non
            # risolveva nulla: aggiungeva solo un processo, una finestra
            # che appare e sparisce, e la possibilita' di perdere il fuoco
            # della tastiera fra le due console. Meglio farne a meno.
            #
            # Chi preferisse il vecchio comportamento (per esempio per
            # tenere separato l'output di MAME) puo' avviare il frontend
            # con il parametro -newconsole.
            creationflags = (
                subprocess.CREATE_NEW_CONSOLE
                if (os.name == "nt" and NEW_CONSOLE)
                else 0
            )
            percorso = rom_file_path(self.roms_dir, game.name) if self.roms_dir else None
            comando = self.engine.command_for(game.name, percorso)
            _log_debug("Avvio gioco", comando, "")
            proc = subprocess.Popen(comando, cwd=self.engine.workdir, creationflags=creationflags)
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
            "F7: blocca / sblocca a mano la voce (solo per il motore in uso)",
            "F8: mostra o nasconde le voci non selezionabili",
            "F9: sceglie il motore (MAME oppure RetroArch + MAME 2003-Plus)",
            "F10 / Esc: esci",
            "",
            "Marcatori a inizio riga:",
            "     avviabile",
            "  !  difettoso secondo MAME (F7 lo sblocca comunque)",
            "  x  bloccato a mano con F7",
            "  +  sbloccato a mano nonostante MAME lo dia difettoso",
            "  B  BIOS o device: non e' un gioco, NON sbloccabile",
            "  ?  avviabile ma non verificato (manca il DAT, o archivio .7z)",
            "",
            "Le voci non selezionabili restano visibili in colore",
            "attenuato: il cursore ci passa sopra (serve per F7),",
            "ma Invio non le avvia.",
            "",
            f"Versione MAME rilevata: {self.mame_version}",
            f"Motore in uso: {self.engine.label}",
            "Con -engine mame|retroarch il motore e' imposto e F9 non lo cambia",
            "Avvia con il parametro -debug per generare un log dettagliato",
            "Avvia con -newconsole per aprire MAME in una finestra separata",
            "",
            "MameCommander e' solo un programma di utilita': elenca i romset",
            "e richiama MAME. Non e' affiliato al progetto MAME.",
            "Ogni merito dell'emulazione va al team di sviluppo di MAME.",
        ]

        # L'aiuto e' piu' lungo di uno schermo da 24 righe, quindi va
        # impaginato: scrivere oltre l'ultima riga farebbe fallire addstr
        # e il tasto F1 andrebbe in errore invece di mostrare l'aiuto.
        # Le righe vengono anche troncate in larghezza, per lo stesso
        # motivo su finestre strette.
        margine_alto = 2
        margine_sx = 4
        righe_utili = max(1, h - margine_alto - 2)
        pagine = [lines[i:i + righe_utili] for i in range(0, len(lines), righe_utili)] or [[]]

        pagina = 0
        while True:
            stdscr.erase()
            stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))
            for i, line in enumerate(pagine[pagina]):
                stdscr.addstr(
                    margine_alto + i,
                    margine_sx,
                    line[: max(0, w - margine_sx - 1)],
                    curses.color_pair(COLOR_NORMAL),
                )
            if len(pagine) > 1:
                piede = f"Pagina {pagina + 1} di {len(pagine)} - un tasto per continuare, Esc per tornare"
            else:
                piede = "Premi un tasto per tornare..."
            stdscr.addstr(h - 1, margine_sx, piede[: max(0, w - margine_sx - 1)],
                          curses.color_pair(COLOR_FUNCKEYS))
            stdscr.refresh()

            ch = stdscr.getch()
            if ch == 27 or len(pagine) == 1:   # Esc, o aiuto di una sola pagina
                return
            pagina += 1
            if pagina >= len(pagine):
                return

    # -- loop principale -------------------------------------------------

    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.apply_search()
        while True:
            self.draw()
            ch = self.stdscr.getch()

            # Il messaggio di stato dura fino al tasto successivo: cosi' si
            # legge, ma non resta li' a sporcare la barra per sempre.
            self.message = ""

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
            elif ch == curses.KEY_F7:
                self.toggle_blocked()
            elif ch == curses.KEY_F8:
                self.toggle_show_blocked()
            elif ch == curses.KEY_F9:
                if self.engine_lock:
                    # Motore imposto da parametro o da MameCommander.ini:
                    # lo si dice, invece di ignorare il tasto in silenzio.
                    self.message = self.engine_lock
                else:
                    return "switch_engine"
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

def choose_engine(stdscr, engines: Dict[str, Optional[Engine]], current: Optional[str]) -> Optional[str]:
    """Schermata di scelta del motore (F9, e al primo avvio se ce ne sono
    piu' d'uno). Elenca TUTTI i motori, anche quelli non trovati, con il
    motivo: cosi' si capisce subito cosa manca invece di chiedersi perche'
    una voce non compare. Ritorna il motore scelto, o None con Esc."""
    voci = list(ENGINE_KINDS)
    disponibili = [k for k in voci if engines.get(k)]
    sel = voci.index(current) if current in voci else voci.index(disponibili[0]) if disponibili else 0

    while True:
        stdscr.erase()
        stdscr.bkgd(" ", curses.color_pair(COLOR_NORMAL))
        h, w = stdscr.getmaxyx()

        def scrivi(y, x, testo, attr):
            if 0 <= y < h and x < w - 1:
                stdscr.addstr(y, x, testo[: max(0, w - x - 1)], attr)

        scrivi(0, 0, f" {APP_NAME} {APP_VERSION} - Scelta del motore di emulazione ".ljust(w),
               curses.color_pair(COLOR_TITLE) | curses.A_BOLD)
        scrivi(2, 2, "Con quale programma vuoi avviare i giochi?", curses.color_pair(COLOR_NORMAL))

        y = 4
        for i, kind in enumerate(voci):
            eng = engines.get(kind)
            attivo = " (in uso)" if kind == current else ""
            riga = f" {ENGINE_DESCRIPTIONS[kind]}{attivo}"
            if eng:
                dettaglio = eng.exe if kind == "mame" else f"{eng.exe}  +  {os.path.basename(eng.core)}"
                attr = curses.color_pair(COLOR_SELECTED if i == sel else COLOR_NORMAL)
            else:
                dettaglio = engine_missing_reason(kind)
                attr = curses.color_pair(COLOR_DIMMED_SELECTED if i == sel else COLOR_DIMMED)
            scrivi(y, 2, riga.ljust(max(0, w - 5)), attr)
            scrivi(y + 1, 6, dettaglio, curses.color_pair(COLOR_DIMMED))
            y += 3

        scrivi(y, 2, "Ogni motore ha la sua cache: cambiare non obbliga a riscansionare.",
               curses.color_pair(COLOR_NORMAL))
        scrivi(y + 1, 2, "I blocchi F7 valgono solo per il motore in cui li imposti.",
               curses.color_pair(COLOR_NORMAL))
        scrivi(h - 1, 0, " Frecce Scegli  Invio Conferma  Esc Annulla ".ljust(w),
               curses.color_pair(COLOR_FUNCKEYS))
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == curses.KEY_UP:
            sel = (sel - 1) % len(voci)
        elif ch == curses.KEY_DOWN:
            sel = (sel + 1) % len(voci)
        elif ch in (10, 13, curses.KEY_ENTER):
            if engines.get(voci[sel]):
                return voci[sel]
            # Voce non disponibile: si resta nella schermata, il motivo e'
            # gia' scritto sotto la voce.
        elif ch == 27:
            return None


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


def scan_and_cache(stdscr, roms_dir: str, engine: Engine) -> Tuple[List[Game], str]:
    """RICOSTRUZIONE COMPLETA (tasto F6): rifa' la scansione via mame.exe
    di TUTTE le ROM presenti in ROMS e riscrive da zero la cache
    MameCommander.db. Ritorna (giochi, versione_mame).

    Riguarda solo la cache del motore in uso: quella dell'altro motore
    resta intatta. Le forzature F7 sono conservate, perche' stanno in una
    tabella separata e vengono riapplicate dopo la scansione.
    """
    def progress_cb(msg):
        draw_progress(stdscr, msg)

    draw_progress(stdscr, "Scansione completa cartella ROMS...")
    rom_names = scan_rom_files(roms_dir)
    if not rom_names:
        return [], "sconosciuta"

    games, mame_version, fonte = build_game_list_for(engine, rom_names, roms_dir, progress_cb)

    # Le forzature F7 di questo motore stanno in una tabella a parte: si
    # riapplicano qui ai giochi appena verificati.
    apply_overrides(DB_PATH, games, engine.kind)

    if games:
        # Non salviamo una scansione vuota: meglio ritentare al prossimo
        # avvio piuttosto che bloccare l'utente su una cache vuota.
        draw_progress(stdscr, "Aggiornamento database...")
        save_cache_to_db(DB_PATH, engine.kind, games, mame_version, engine_signature(engine, fonte))
    return games, mame_version


def scan_new_only(
    stdscr,
    roms_dir: str,
    engine: Engine,
    existing_games: List[Game],
    existing_version: str,
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

    new_games, mame_version, fonte = build_game_list_for(engine, new_names, roms_dir, progress_cb)
    mame_version = mame_version or existing_version or "sconosciuta"

    if not new_games:
        return existing_games, existing_version, 0

    apply_overrides(DB_PATH, new_games, engine.kind)
    merged = existing_games + new_games
    merged.sort(key=lambda g: g.display_name.lower())
    draw_progress(stdscr, "Aggiornamento database...")
    save_cache_to_db(DB_PATH, engine.kind, merged, mame_version, engine_signature(engine, fonte))
    return merged, mame_version, len(new_games)


def info_source(engine: Engine, roms_dir: Optional[str]) -> str:
    """Quale fonte verra' usata per titoli e stato dei romset, senza fare
    ancora nessuna scansione (serve per decidere se la cache e' valida)."""
    if engine.kind == "mame":
        return "mame"
    if find_dat(engine, roms_dir):
        return "dat"
    return "mame" if MAME_EXE else "nessuna"


def engine_signature(engine: Engine, fonte: str) -> str:
    """Identifica motore + fonte delle informazioni. Viene salvata nella
    cache: se all'avvio non corrisponde (si e' passati da MAME a RetroArch,
    o e' stato aggiunto il DAT), la cache e' stata calcolata con criteri
    diversi e va ricostruita."""
    return f"{engine.kind}:{fonte}"


def main(stdscr):
    init_colors()
    curses.curs_set(0)

    # 1. cartella delle ROM
    roms_dir = find_roms_dir()
    if roms_dir is None:
        draw_error_screen(
            stdscr,
            [
                "ERRORE: cartella delle ROM non trovata.",
                f"Cercata in: {APP_DIR} (nomi provati: roms, ROMS, ROM, rom)",
                "...nel 'rompath' indicato in mame.ini, e in ~/.mame/roms",
                "",
                "Crea una cartella ROMS accanto a questo programma e",
                "mettici i romset, oppure configura il rompath in mame.ini,",
                f"oppure indicala con la voce roms= in {APP_NAME}.ini.",
            ],
        )
        return

    # 2. motore di emulazione. NESSUNA precedenza automatica fra MAME e
    #    RetroArch: si usa quello imposto (-engine o MameCommander.ini), o
    #    altrimenti quello scelto l'ultima volta con F9. Se non c'e' ancora
    #    una scelta e i motori disponibili sono due, lo si chiede.
    engines = available_engines()
    imposto, errore = forced_engine_kind()
    if errore:
        draw_error_screen(stdscr, [f"ERRORE: {errore}."])
        return

    if imposto:
        if engines[imposto] is None:
            draw_error_screen(
                stdscr,
                [
                    f"ERRORE: e' stato imposto il motore '{imposto}',",
                    f"ma {ENGINE_DESCRIPTIONS[imposto]} risulta {engine_missing_reason(imposto)}.",
                    "",
                    f"Controlla il parametro -engine o la voce engine= in {APP_NAME}.ini.",
                ],
            )
            return
        kind = imposto
        lock = f"Motore imposto da -engine o {APP_NAME}.ini: F9 non lo cambia."
    else:
        lock = ""
        disponibili = [k for k in ENGINE_KINDS if engines[k]]
        if not disponibili:
            draw_error_screen(
                stdscr,
                [
                    "ERRORE: non e' stato trovato nessun motore di emulazione.",
                    "",
                    "Servono UNO dei due:",
                    f"  - MAME: {' o '.join(MAME_EXE_CANDIDATES)}, accanto a questo",
                    "    programma oppure raggiungibile dal PATH;",
                    f"  - RetroArch con il core {CORE_FILE_NAME}",
                    "    (nella sottocartella cores di RetroArch).",
                    "",
                    f"Cartella del programma: {APP_DIR}",
                    "RetroArch viene cercato qui, in una sottocartella RetroArch",
                    "e in una cartella RetroArch allo stesso livello.",
                    "",
                    f"Per percorsi diversi crea {APP_NAME}.ini (vedi il file",
                    f"{APP_NAME}.ini.example incluso nel progetto).",
                ],
            )
            return
        salvato = get_selected_engine(DB_PATH)
        if salvato in disponibili:
            kind = salvato
        elif len(disponibili) == 1:
            kind = disponibili[0]
        else:
            kind = choose_engine(stdscr, engines, None)
            if kind is None:
                return  # Esc alla prima scelta: si esce senza toccare nulla
        set_selected_engine(DB_PATH, kind)

    show_blocked = get_show_blocked(DB_PATH)
    da_caricare = True

    while True:
        engine = engines[kind]

        if da_caricare:
            draw_progress(stdscr, "Verifica database...")
            # La cache di questo motore vale solo se calcolata con la stessa
            # fonte di adesso (es. e' stato aggiunto il DAT nel frattempo).
            firma = engine_signature(engine, info_source(engine, roms_dir))
            cached = load_cache_from_db(DB_PATH, kind)
            if cached is not None and cached[2] == firma:
                games, mame_version = cached[0], cached[1]
            else:
                games, mame_version = scan_and_cache(stdscr, roms_dir, engine)
            da_caricare = False

        if not games:
            draw_error_screen(
                stdscr,
                [
                    "Nessuna ROM utilizzabile trovata.",
                    "",
                    "Le ROM difettose resterebbero comunque in lista, in",
                    "colore attenuato: se la lista e' del tutto vuota vuol dire",
                    "che nella cartella non c'e' nessun file .zip/.7z.",
                    "",
                    "Avvia con -debug per un log dettagliato della scansione.",
                ],
            )
            return

        app = App(stdscr, games, mame_version, show_blocked=show_blocked,
                  engine=engine, roms_dir=roms_dir, engine_lock=lock)
        action = app.run()
        # F8 e' gia' stato salvato da App; teniamo allineata la copia locale.
        show_blocked = app.show_blocked

        if action == "quit":
            return

        elif action == "switch_engine":
            nuovo = choose_engine(stdscr, engines, kind)
            if nuovo and nuovo != kind:
                kind = nuovo
                set_selected_engine(DB_PATH, kind)
                da_caricare = True

        elif action == "refresh_new":
            games, mame_version, new_count = scan_new_only(stdscr, roms_dir, engine, games, mame_version)
            if new_count > 0:
                draw_info_screen(
                    stdscr,
                    [
                        f"Trovati {new_count} nuovi giochi.",
                        "Database aggiornato (le voci gia' presenti non sono state ritoccate).",
                    ],
                )
            else:
                draw_info_screen(stdscr, ["Nessun nuovo gioco trovato.", "La lista era gia' aggiornata."])

        elif action == "refresh_full":
            games, mame_version = scan_and_cache(stdscr, roms_dir, engine)


if __name__ == "__main__":
    curses.wrapper(main)
