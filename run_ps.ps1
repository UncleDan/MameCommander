# MameCommander launcher per PowerShell
# Esecuzione: .\run_ps.ps1

# Nota: se ricevi errore "non autorizzato a eseguire script",
# esegui questo comando UNA VOLTA in PowerShell (come admin):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

$ErrorActionPreference = "Stop"

Write-Host "MameCommander - Avvio..." -ForegroundColor Cyan

# Ottieni la cartella dello script
$scriptDir = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Controlla se Python è disponibile
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Errore: Python non trovato nel PATH." -ForegroundColor Red
    Write-Host "Scarica e installa Python da https://www.python.org" -ForegroundColor Yellow
    Write-Host "Assicurati di spuntare 'Add Python to PATH' durante l'installazione." -ForegroundColor Yellow
    Read-Host "Premi Invio per uscire"
    exit 1
}

# Avvia lo script
try {
    python MameCommander.py
} catch {
    Write-Host "Errore durante l'esecuzione: $_" -ForegroundColor Red
    Read-Host "Premi Invio per uscire"
    exit 1
}
