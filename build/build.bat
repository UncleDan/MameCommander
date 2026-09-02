@echo off
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
REM ===========================================================================

setlocal enabledelayedexpansion

REM %~dp0 e' la cartella di questo script; ".." porta alla radice del progetto
cd /d "%~dp0.."
set "PROJECT_DIR=%CD%"

echo ============================================================
echo  MameCommander - Build eseguibile monolitico
echo ============================================================
echo  Cartella progetto: %PROJECT_DIR%
echo.

if not exist "MameCommander.py" (
    echo Errore: MameCommander.py non trovato in %PROJECT_DIR%
    echo Questo script deve restare nella sottocartella "build" del progetto.
    pause
    exit /b 1
)

REM Controlla che Python sia disponibile
python --version >nul 2>&1
if errorlevel 1 (
    echo Errore: Python non trovato nel PATH.
    echo Scarica e installa Python da https://www.python.org
    echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    pause
    exit /b 1
)

echo [1/3] Installazione dipendenze...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo Errore durante l'installazione delle dipendenze.
    pause
    exit /b 1
)

echo.
echo [2/3] Pulizia build precedenti...
if exist ".pyi-work" rmdir /s /q ".pyi-work"
if exist "dist" rmdir /s /q "dist"
if exist "MameCommander.spec" del /q "MameCommander.spec"

echo.
echo [3/3] Compilazione con PyInstaller...
pyinstaller --onefile --console ^
    --name MameCommander ^
    --workpath ".pyi-work" ^
    --specpath ".pyi-work" ^
    --distpath "dist" ^
    MameCommander.py
if errorlevel 1 (
    echo.
    echo Errore durante la compilazione.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Fatto! Eseguibile creato in: dist\MameCommander.exe
echo.
echo  Copialo nella stessa cartella di mame.exe: cerca mame.exe,
echo  la cartella roms e il proprio database NELLA PROPRIA
echo  CARTELLA, non nella directory di lavoro.
echo ============================================================
pause
