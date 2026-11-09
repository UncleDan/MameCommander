@REM run.cmd by Daniele Lolli (UncleDan) feat. Claude AI - Release 1.1 - 2026-11-08 23-02-40
@echo off
REM
REM  MameCommander - Copyright (c) 2026 Daniele Lolli
REM  Licenza MIT: vedi il file LICENSE.
REM  SPDX-License-Identifier: MIT
REM
REM ===========================================================================
REM  MameCommander - avvio da cmd.exe senza compilare
REM ===========================================================================
REM  Basta raddoppiare questo file.
REM
REM  Come build.cmd, evita i blocchi "if ... ( ... )" con variabili dentro:
REM  cmd.exe li analizza espandendo le variabili in anticipo, quindi un
REM  percorso contenente parentesi (es. "\(local)\") romperebbe lo script.
REM ===========================================================================

setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "MameCommander.py" goto :no_source

REM Controlla se Python e' disponibile
python --version >nul 2>&1
if errorlevel 1 goto :no_python

echo Avvio MameCommander...
python "MameCommander.py" %*
if errorlevel 1 goto :run_failed
exit /b 0

REM ---------------------------------------------------------------------------

:no_source
echo Errore: MameCommander.py non trovato in:
echo   "%SCRIPT_DIR%"
pause
exit /b 1

:no_python
echo Errore: Python non trovato nel PATH.
echo.
echo Scarica e installa Python da https://www.python.org
echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
echo.
echo Nota: serve anche il pacchetto windows-curses. Installalo con:
echo   pip install -r requirements.txt
pause
exit /b 1

:run_failed
echo.
echo Errore durante l'esecuzione.
pause
exit /b 1
