# MameCommander 1.0

Frontend testuale per MAME, in stile Norton Commander.

**Funziona su Windows e su Linux con lo stesso identico sorgente.**
Su Windows si distribuisce come eseguibile monolitico unico (nessuna
installazione, nessuna DLL esterna); su Linux si esegue direttamente,
senza compilare e senza installare nulla.

## Cosa fa

1. Individua l'eseguibile di MAME (`mame.exe` su Windows, `mame` su
   Linux), cercandolo prima nella propria cartella e poi nel `PATH` di
   sistema (caso tipico quando MAME e' installato dalla distribuzione).
2. Individua la cartella delle ROM e trova tutti i file `.zip` / `.7z`.
   La cerca, nell'ordine: accanto al programma (`roms`, `ROMS`, `ROM`,
   `rom`), nel `rompath` dichiarato in `mame.ini` (locale o in
   `~/.mame/`), infine nel percorso predefinito `~/.mame/roms`.
3. Chiede a MAME stesso, tramite `-verifyroms`, quali romset sono
   integri.
4. Chiede a MAME, tramite `-listxml`, nome completo, se e' un BIOS e
   se e' realmente eseguibile (esclude BIOS e slot/device), e rileva la
   versione di MAME installata.
5. Mostra solo i giochi realmente avviabili, con il nome completo e la
   versione di MAME nella barra del titolo, in una lista navigabile con
   le frecce, ricerca digitando, avvio con Invio.
6. Salva il risultato in un database SQLite (`MameCommander.db`, nella
   stessa cartella del programma): agli avvii successivi lo usa
   direttamente, senza richiamare MAME (avvio istantaneo). Se il
   file non esiste, viene creato automaticamente dopo la prima scansione.
   Da dentro l'app sono disponibili due modalita' di aggiornamento:
   - **F5 — Nuovi giochi**: cerca solo le ROM non ancora presenti nel
     database e le aggiunge, senza ritoccare quelle gia' verificate.
     Molto piu' veloce, ideale dopo aver aggiunto poche ROM. Non si
     accorge delle ROM rimosse dalla cartella (restano in lista finche'
     non si fa una ricostruzione completa).
   - **F6 — Ricostruisci**: rifa' la scansione completa di tutte le ROM
     e riscrive il database da zero (anche le ROM rimosse spariscono
     dalla lista).

## Installazione su Linux

Il modo piu' semplice e' lo script `install.sh` incluso. Non compila
nulla: copia i file al posto giusto e crea il comando `mamecommander`.

```sh
sh install.sh                # installa solo per l'utente corrente
```

Si invoca con `sh install.sh` e non `./install.sh`: cosi' funziona anche
quando il permesso di esecuzione manca — cosa che succede **sempre** se il
progetto e' passato per Windows, perche' il filesystem di Windows non
conserva i permessi Unix. Non serve dare `chmod` a mano: ci pensa lo
script.

Da quel momento il comando e' disponibile ovunque:

```sh
mamecommander                # avvio normale
mamecommander -debug         # avvio con log di debug
```

### Opzioni disponibili

| Comando | Effetto |
|---|---|
| `sh install.sh` | Installa in `~/.local` (solo utente corrente, nessun privilegio richiesto) |
| `sudo sh install.sh --system` | Installa in `/usr/local` per tutti gli utenti |
| `sh install.sh --uninstall` | Rimuove l'installazione utente |
| `sudo sh install.sh --uninstall --system` | Rimuove l'installazione di sistema |
| `sh install.sh --help` | Mostra la guida |

### Cosa viene scritto sul sistema

Installazione utente (`--system` usa gli equivalenti sotto `/usr/local`):

| Percorso | Contenuto |
|---|---|
| `~/.local/lib/mamecommander/` | `MameCommander.py` e il lanciatore |
| `~/.local/bin/mamecommander` | Il comando vero e proprio |
| `~/.local/share/applications/mamecommander.desktop` | Voce nel menu applicazioni |

Nient'altro viene toccato, e `--uninstall` rimuove esattamente queste tre
voci. Le ROM, `mame.ini` e il database restano dove sono.

Lo script controlla in anticipo che Python 3 ci sia e che disponga
davvero di `curses` e `sqlite3`, avvisa se MAME non e' installato, e
segnala il caso — frequente su Debian e derivate — in cui `~/.local/bin`
non e' incluso nel `PATH`, indicando come rimediare.

### Se lavori su Windows e trasferisci il progetto su Linux

E' il caso piu' insidioso, perche' produce errori dall'aspetto
incomprensibile. Lo script di installazione li previene entrambi:

- **Permessi persi.** Il filesystem di Windows non conserva il bit di
  esecuzione Unix. Lo script lo rimette sia ai file che installa sia a
  quelli originali del progetto, cosi' dopo l'installazione funziona
  anche `./mamecommander` dalla cartella scompattata.
- **Fine-riga CRLF.** Se i file vengono aperti o salvati da un editor
  Windows prendono i terminatori `\r\n`. Su Linux questo e' fatale per
  uno script: il sistema legge `#!/bin/sh\r` e cerca un interprete
  chiamato `sh\r`, che non esiste, restituendo un errore fuorviante come
  `bad interpreter` o `not found`. Lo script rileva e converte i file
  interessati, segnalando quali ha corretto.

L'unico caso che lo script non puo' sistemare da solo e' quando ad avere
i CRLF e' `install.sh` stesso: non riuscirebbe nemmeno ad avviarsi. In
quel caso correggilo una volta e rilancia:

```sh
sed -i 's/\r$//' install.sh     # oppure: dos2unix install.sh
sh install.sh
```

### Senza installare nulla

Se preferisci tenerlo in una cartella qualsiasi, funziona lo stesso:

```sh
chmod +x mamecommander
./mamecommander
```

## Uso su Linux (senza compilare)

Non serve installare nulla: `curses` e `sqlite3` fanno gia' parte della
libreria standard di Python 3.

```sh
chmod +x mamecommander          # una volta sola, dopo aver scompattato
./mamecommander                 # avvio normale
./mamecommander -debug          # avvio con log di debug
```

Lo script `mamecommander` (senza estensione) e' un piccolo lanciatore
che richiama `MameCommander.py` con l'interprete Python disponibile.
Se preferisci averlo tra i comandi di sistema, puoi creare un
collegamento simbolico — il lanciatore risolve il link e trova comunque
la propria cartella:

```sh
ln -s "$PWD/mamecommander" ~/.local/bin/mamecommander
```

In alternativa si puo' invocare direttamente lo script Python:

```sh
python3 MameCommander.py
```

## Uso su Windows (senza compilare)

Qui serve il pacchetto `windows-curses` (Python non include `curses` su
Windows).

### In cmd.exe (prompt MS-DOS)

```batch
pip install -r requirements.txt
python MameCommander.py
```

Oppure, semplicemente, raddoppia il file `run_cmd.bat` incluso nel progetto.

### In PowerShell

```powershell
pip install -r requirements.txt
python MameCommander.py
```

Oppure, esegui lo script PowerShell incluso:

```powershell
.\run_ps.ps1
```

**Nota:** Se ricevi errore "non autorizzato a eseguire script", esegui UNA VOLTA
in PowerShell (come amministratore):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Modo rapido (entrambi)

Se hai Python nel PATH, basta:

- **cmd.exe**: raddoppia `run_cmd.bat`
- **PowerShell**: esegui `.\run_ps.ps1`

## Compilazione manuale in eseguibile unico

### Modo rapido: `build.bat`

Raddoppia `build.bat` (o eseguilo da cmd.exe/PowerShell): installa le
dipendenze, pulisce build precedenti e compila `dist\MameCommander.exe`
in automatico.

### Modo manuale

```bash
pip install -r requirements.txt
pyinstaller --onefile --console --name MameCommander MameCommander.py
```

L'eseguibile risultante sara' in `dist/MameCommander.exe`: va copiato nella
stessa cartella di `mame.exe`.

## Compilazione automatica (GitHub Actions)

Il workflow `.github/workflows/build.yml`:

- Si attiva su push su `main`, su tag `v*` (es. `v1.0`), oppure manualmente
  da tab "Actions" -> "Run workflow".
- Compila su `windows-latest` (necessario per `windows-curses` e per
  produrre un `.exe` nativo Windows).
- Carica `MameCommander.exe` e `MameCommander-1.0.exe` come artefatto
  scaricabile dalla pagina della run.
- Se il push e' un tag `v*`, crea anche una GitHub Release allegando
  l'eseguibile.

Per pubblicare una release:

```bash
git tag v1.0
git push origin v1.0
```

## Distribuzione (eseguibile compilato)

Una volta compilato, avrai `MameCommander.exe`: basta raddoppiarlo da Esplora
risorse (Windows), o da PowerShell con:

```powershell
.\MameCommander.exe
```

O da cmd.exe con:

```batch
MameCommander.exe
```

Non serve Python installato per usare l'eseguibile compilato — e' completamente
autonomo.

## Note

- Il formato di output di `-verifyroms` e `-listxml` varia tra le versioni
  di MAME (es. MAME 0.78b non stampa una riga per romset, ma un riepilogo
  a conteggio, e usa il tag XML `<game>` invece di `<machine>`).
  MameCommander gestisce automaticamente i formati piu' comuni.
- **Log di debug**: per diagnosticare problemi, avvia con il parametro
  `-debug` (es. `MameCommander.exe -debug`): verra' scritto
  `MameCommander_debug.log`, nella stessa cartella dell'eseguibile, con
  il comando esatto e l'output grezzo di ogni chiamata a `mame.exe`.
  Senza questo parametro nessun log viene creato. Il file viene
  sovrascritto ad ogni scansione ed e' escluso dal repository tramite
  `.gitignore`.
- **Database cache (`MameCommander.db`)**: viene cercato/creato nella
  stessa cartella dell'eseguibile. Se presente, viene usato direttamente
  per un avvio istantaneo (senza richiamare `mame.exe`); se assente,
  viene creato dopo la prima scansione completa. Da dentro l'app:
  **F5** cerca solo le ROM nuove (veloce, non ritocca le voci gia'
  presenti — non si accorge pero' delle ROM rimosse, che restano in
  lista); **F6** ricostruisce l'intero database da zero. Anche questo
  file e' escluso dal repository tramite `.gitignore`.

## Uso portable su Windows (winPenPack / X-Launcher)

Nella cartella `X-MameCommander/` c'e' il file `X-MameCommander.ini`, gia'
pronto per winPenPack X-Launcher 1.5.4: avvia il frontend dentro una
finestra `cmd.exe`, cosi' tutto (emulatore, ROM e cache) resta sulla
chiavetta senza toccare il PC ospite.

Struttura attesa sul supporto rimovibile:

```
X-MameCommander.exe          <- il launcher di X-Launcher, rinominato
X-MameCommander.ini          <- il file di configurazione incluso
Bin\
  MameCommander\
    MameCommander.exe        <- il frontend compilato
    MameCommander.db         <- cache, creata al primo avvio
    mame.exe                 <- MAME
    roms\                    <- i romset
```

Attenzione a un punto: `MameCommander.exe` cerca `mame.exe`, la cartella
`roms` e il proprio database **nella propria cartella**, non nella
directory di lavoro. Deve quindi stare dentro la stessa cartella di MAME
(`Bin\MameCommander`), non in una cartella separata.

Il file `.ini` e' commentato in ogni sua parte e contiene gia' le varianti
alternative: `/K` al posto di `/C` per lasciare la finestra aperta e
leggere eventuali errori, la riga per avviare con `-debug`, e quella per
cancellare la cache a ogni uscita invece di conservarla.

## File del progetto

| File | A cosa serve |
|---|---|
| `MameCommander.py` | Il programma: sorgente unico, gira su Linux e Windows |
| `mamecommander` | Lanciatore Linux senza estensione |
| `install.sh` | Installazione/disinstallazione su Linux |
| `run_cmd.bat` | Avvio su Windows da `cmd.exe`, senza compilare |
| `run_ps.ps1` | Avvio su Windows da PowerShell, senza compilare |
| `build.bat` | Compila l'eseguibile unico con PyInstaller |
| `.github/workflows/build.yml` | Compilazione automatica e release su GitHub |
| `X-MameCommander/X-MameCommander.ini` | Configurazione winPenPack X-Launcher |
| `requirements.txt` | Dipendenze Windows (`windows-curses`, `pyinstaller`) |

## Requisiti per piattaforma

| | Linux | Windows |
|---|---|---|
| Python | 3.8+ (di solito gia' presente) | 3.8+ |
| Dipendenze da installare | nessuna (`curses` e `sqlite3` sono nella stdlib) | `windows-curses` |
| Modo d'uso consigliato | eseguire direttamente `./mamecommander` | eseguibile compilato con PyInstaller |
| Dove cerca MAME | cartella del programma, poi `PATH` | cartella del programma, poi `PATH` |
| Dove cerca le ROM | `./roms`, `rompath` di `mame.ini`, `~/.mame/roms` | `./roms`, `rompath` di `mame.ini` |

Nota: su Linux il permesso di esecuzione puo' andare perso scompattando
l'archivio; in tal caso basta ridarlo una volta con
`chmod +x mamecommander`.
