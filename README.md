# MameCommander 1.0

Frontend testuale per MAME, in stile Norton Commander, distribuito come
eseguibile monolitico unico (nessuna installazione, nessuna DLL esterna).

## Cosa fa

1. Verifica che `mame.exe` sia presente nella stessa cartella dell'eseguibile.
2. Legge la cartella `ROMS` (o `roms`) accanto a `mame.exe` e trova tutti i
   file `.zip` / `.7z`.
3. Chiede a `mame.exe` stesso, tramite `-verifyroms`, quali romset sono
   integri.
4. Chiede a `mame.exe`, tramite `-listxml`, nome completo, se e' un BIOS e
   se e' realmente eseguibile (esclude BIOS e slot/device).
5. Mostra solo i giochi realmente avviabili, con il nome completo, in una
   lista navigabile con le frecce, ricerca digitando, avvio con Invio.

## Uso locale (senza compilare)

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
- Ad ogni scansione viene scritto `MameCommander_debug.log` nella stessa
  cartella dell'eseguibile, con il comando esatto e l'output grezzo di
  ogni chiamata a `mame.exe`. Utile per capire perche' una ROM non viene
  rilevata come avviabile. Il file viene sovrascritto ad ogni scansione
  (non serve cancellarlo a mano) ed e' escluso dal repository tramite
  `.gitignore`.
