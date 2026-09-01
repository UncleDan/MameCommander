@echo off
REM MameCommander launcher per cmd.exe (MS-DOS)
REM Semplifica l'esecuzione: basta raddoppiare il file

setlocal enabledelayedexpansion

REM Ottieni la cartella dello script
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Controlla se Python è disponibile
python --version >nul 2>&1
if errorlevel 1 (
    echo Errore: Python non trovato nel PATH.
    echo Scarica e installa Python da https://www.python.org
    echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    pause
    exit /b 1
)

REM Avvia lo script
echo Avvio MameCommander...
python MameCommander.py
if errorlevel 1 (
    echo.
    echo Errore durante l'esecuzione.
    pause
)
