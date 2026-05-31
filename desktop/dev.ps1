# Clean restart for the VideoCraft Electron dev app (PowerShell).
#
# Why a script: a plain `pnpm dev` is unreliable here for two reasons baked into
# this project's notes:
#   1. The agent/dev shell often carries ELECTRON_RUN_AS_NODE=1, which makes the
#      Electron main process boot as plain Node and crash. We must unset it.
#   2. Vite HMR in this environment hands back stale bundles; after a renderer or
#      Python change you must kill leftovers + clear node_modules/.vite and do a
#      full restart, not Ctrl+R.
#   Also: Python (the sidecar) changed, and the sidecar is spawned by the main
#   process — only a full app restart reloads it.
#
# Usage:  cd desktop ; ./dev.ps1
# Stop:   Ctrl+C in this window.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "[dev] killing leftover electron.exe ..." -ForegroundColor Cyan
Get-Process electron -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "[dev] freeing dev port 5174 ..." -ForegroundColor Cyan
try {
    Get-NetTCPConnection -LocalPort 5174 -ErrorAction Stop |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
} catch {
    # No listener on 5174 — nothing to free.
}

Write-Host "[dev] clearing Vite cache (node_modules/.vite) ..." -ForegroundColor Cyan
if (Test-Path "node_modules/.vite") {
    Remove-Item -Recurse -Force "node_modules/.vite" -ErrorAction SilentlyContinue
}

# The main process must NOT run as plain Node, or it boots wrong and crashes.
$env:ELECTRON_RUN_AS_NODE = $null
Remove-Item Env:\ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

Write-Host "[dev] starting electron-vite (renderer on http://localhost:5174) ..." -ForegroundColor Green
Write-Host "      Open a project, then a news_desk creation, to test the new workbench." -ForegroundColor DarkGray
& pnpm dev
