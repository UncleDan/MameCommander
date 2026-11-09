@REM build.cmd by Daniele Lolli (UncleDan) feat. Claude AI - Release 1.2 - 2026-11-08 23-15-30
@echo off
REM
REM  MameCommander - Copyright (c) 2026 Daniele Lolli
REM  Licenza MIT: vedi il file LICENSE.
REM  SPDX-License-Identifier: MIT
REM
REM ===========================================================================
REM  MameCommander - compilazione dell'eseguibile monolitico per Windows
REM ===========================================================================
REM  Uso: raddoppia questo file, oppure lancialo da cmd.exe / PowerShell.
REM
REM  Questo script sta nella sottocartella "build" ma lavora sulla cartella
REM  del progetto (quella superiore), dove si trova MameCommander.py.
REM
REM  I file temporanei di PyInstaller finiscono in ".pyi-work" e NON in
REM  "build": quest'ultima contiene gli script di compilazione veri e propri
REM  e va lasciata intatta.
REM
REM  NOTA TECNICA - perche' questo script non usa blocchi "if ... ( ... )":
REM  cmd.exe espande le variabili quando ANALIZZA un blocco tra parentesi,
REM  non quando lo esegue. Se il percorso del progetto contiene parentesi
REM  (es. C:\repos\(local)\MameCommander), la parentesi chiusa del percorso
REM  chiude il blocco in anticipo e la compilazione fallisce con un errore
REM  incomprensibile del tipo "\MameCommander non atteso", anche quando va
REM  tutto bene. Usare i salti a etichetta (goto) evita il problema alla
REM  radice, qualunque carattere contenga il percorso.
REM ===========================================================================

setlocal

REM %~dp0 e' la cartella di questo script; ".." porta alla radice del progetto
cd /d "%~dp0.."
set "PROJECT_DIR=%CD%"

echo ============================================================
echo  MameCommander - Build eseguibile monolitico
echo ============================================================
echo  Cartella progetto: "%PROJECT_DIR%"
echo.

if not exist "MameCommander.py" goto :no_source
if not exist "MameCommander.ico" goto :no_icon

REM Controlla che Python sia disponibile
python --version >nul 2>&1
if errorlevel 1 goto :no_python

echo [1/3] Installazione dipendenze...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 goto :deps_failed

echo.
echo [2/3] Pulizia build precedenti...
if exist ".pyi-work" rmdir /s /q ".pyi-work"
if exist "dist" rmdir /s /q "dist"
if exist "MameCommander.spec" del /q "MameCommander.spec"

echo.
echo [3/3] Compilazione con PyInstaller...
REM --icon incorpora l'icona nell'eseguibile: e' quella che si vede in
REM Esplora risorse, sulla barra delle applicazioni e nei collegamenti.
REM
REM IMPORTANTE: il percorso dell'icona va passato ASSOLUTO.
REM PyInstaller ancora i percorsi RELATIVI dell'icona alla cartella del
REM file .spec, non alla directory di lavoro. Siccome qui lo .spec viene
REM generato in ".pyi-work" (per non sporcare la cartella del progetto),
REM un "--icon MameCommander.ico" verrebbe cercato in
REM ".pyi-work\MameCommander.ico" e la compilazione fallirebbe con:
REM   FileNotFoundError: Icon input file ...\.pyi-work\MameCommander.ico
REM Il file .py invece funziona anche relativo, perche' PyInstaller lo
REM riscrive da solo rispetto allo .spec: il trattamento e' diverso.
pyinstaller --onefile --console ^
    --name MameCommander ^
    --icon "%PROJECT_DIR%\MameCommander.ico" ^
    --workpath ".pyi-work" ^
    --specpath ".pyi-work" ^
    --distpath "dist" ^
    "MameCommander.py"
if errorlevel 1 goto :build_failed

echo.
echo ============================================================
echo  Fatto! Eseguibile creato in:
echo    "%PROJECT_DIR%\dist\MameCommander.exe"
echo.
echo  Copialo nella stessa cartella di mame.exe: cerca mame.exe,
echo  la cartella roms e il proprio database NELLA PROPRIA
echo  CARTELLA, non nella directory di lavoro.
echo ============================================================
pause
exit /b 0

REM ---------------------------------------------------------------------------
REM  Gestione errori
REM ---------------------------------------------------------------------------

:no_source
echo Errore: MameCommander.py non trovato in:
echo   "%PROJECT_DIR%"
echo.
echo Questo script deve restare nella sottocartella "build" del progetto.
pause
exit /b 1

:no_icon
echo Errore: MameCommander.ico non trovato in:
echo   "%PROJECT_DIR%"
echo.
echo L'icona fa parte del progetto. Se manca, puoi rigenerarla con:
echo   python build\make_icon.py
echo (richiede il pacchetto Pillow: pip install pillow)
pause
exit /b 1

:no_python
echo Errore: Python non trovato nel PATH.
echo.
echo Scarica e installa Python da https://www.python.org
echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
pause
exit /b 1

:deps_failed
echo.
echo Errore durante l'installazione delle dipendenze.
echo Verifica la connessione a Internet e i permessi di scrittura.
pause
exit /b 1

:build_failed
echo.
echo Errore durante la compilazione.
pause
exit /b 1
