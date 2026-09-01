@echo off
REM Compila MameCommander in un unico eseguibile monolitico con PyInstaller.
REM Uso: raddoppia questo file, oppure lancialo da cmd.exe / PowerShell.

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo  MameCommander - Build eseguibile monolitico
echo ============================================================
echo.

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
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist MameCommander.spec del /q MameCommander.spec

echo.
echo [3/3] Compilazione con PyInstaller...
pyinstaller --onefile --console --name MameCommander MameCommander.py
if errorlevel 1 (
    echo.
    echo Errore durante la compilazione.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Fatto! Eseguibile creato in: dist\MameCommander.exe
echo  Copialo nella stessa cartella di mame.exe per usarlo.
echo ============================================================
pause
