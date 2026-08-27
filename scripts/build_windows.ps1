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
    --hidden-import markdownify `
    --hidden-import pypdf `
    --hidden-import pptx `
    --collect-all selenium `
    --add-data "tools/prepare_ai_course.py;tools" `
    "app.py"

$Exe = Join-Path $RepoRoot "dist\BK-LMS-Downloader.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but EXE was not found: $Exe"
}

$SelfTest = Start-Process `
    -FilePath $Exe `
    -ArgumentList "--self-test-ai" `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
if ($SelfTest.ExitCode -ne 0) {
    if (Test-Path "ai-self-test-error.log") {
        Get-Content "ai-self-test-error.log"
    }
    throw "Packaged AI runtime smoke failed."
}

Write-Host "" 
Write-Host "Build OK:" -ForegroundColor Green
Write-Host $Exe
