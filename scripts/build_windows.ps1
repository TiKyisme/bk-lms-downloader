param(
    [switch]$SkipTests
)

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

if (-not $SkipTests) {
    & $Python -m pytest
}

& $Python tools/build_desktop.py

$Exe = Join-Path $RepoRoot "dist\BK-LMS-Downloader.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but EXE was not found: $Exe"
}

& (Join-Path $RepoRoot "scripts\verify_windows_icon.ps1") `
    -ExePath $Exe `
    -SourcePngPath (Join-Path $RepoRoot "BK-LMS-Downloader-icon-blue.png")

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
    throw "Packaged AI Study Pack validation failed."
}

$SyncTest = Start-Process `
    -FilePath $Exe `
    -ArgumentList "--self-test-sync" `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
if ($SyncTest.ExitCode -ne 0) {
    if (Test-Path "sync-self-test-error.log") {
        Get-Content "sync-self-test-error.log"
    }
    throw "Packaged sync timeout recovery validation failed."
}

$ScrollTest = Start-Process `
    -FilePath $Exe `
    -ArgumentList "--self-test-scroll" `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
if ($ScrollTest.ExitCode -ne 0) {
    if (Test-Path "scroll-self-test-error.log") {
        Get-Content "scroll-self-test-error.log"
    }
    throw "Packaged GUI scroll/layout validation failed."
}

Write-Host "" 
Write-Host "Build OK:" -ForegroundColor Green
Write-Host $Exe
