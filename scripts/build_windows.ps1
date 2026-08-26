$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "== BK-LMS Downloader: Windows build ==" -ForegroundColor Cyan

$Venv = Join-Path $RepoRoot ".venv-build"
if (-not (Test-Path $Venv)) {
    py -3 -m venv $Venv
}

$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install -U pip
& $Python -m pip install ".[dev]"

& $Python -m pytest

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "BK-LMS-Downloader" `
    --paths "src" `
    --collect-submodules bklms_downloader `
    --collect-all customtkinter `
    --collect-all selenium `
    "app.py"

$Exe = Join-Path $RepoRoot "dist\BK-LMS-Downloader.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but EXE was not found: $Exe"
}

Write-Host "" 
Write-Host "Build OK:" -ForegroundColor Green
Write-Host $Exe
