# Build the VideoCraft core_rpc sidecar into a PyInstaller onedir (P3).
# packaging-design.md §2. Output: desktop/resources/sidecar/core_rpc.exe (+ _internal/).
#
# The freeze input is the locked BASE tier only — pyproject.toml [project.dependencies]
# + the `build` dependency-group (pyinstaller), installed FROM uv.lock for a
# byte-reproducible closure. NOT the polluted dev myenv. Embedded-AI / GPU runtimes
# (the `embedded-ai` / `gpu` extras) are excluded on purpose — they install at
# runtime into user_data/runtimes/py-extra (packaging-design.md §5.3). See
# docs/adr/0009-uv-project-dependency-management.md.
#
# Usage:  ./packaging/build_sidecar.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$venv = Join-Path $repo ".build\sidecar-venv"
$py = Join-Path $venv "Scripts\python.exe"

Write-Host "[sidecar] syncing locked base tier into clean build venv (uv) at $venv ..." -ForegroundColor Cyan
# Point uv's project environment at the dedicated build venv (not myenv / .venv),
# then sync EXACTLY the base closure from uv.lock:
#   --frozen              use uv.lock as-is, no re-resolution (reproducible)
#   --no-default-groups   drop the default `dev` group (pytest, …)
#   --group build         add only pyinstaller
#   (no --extra)          embedded-ai / gpu extras stay out of the freeze
# --clear on the venv guarantees a from-scratch env so no stale package survives.
$env:UV_PROJECT_ENVIRONMENT = $venv
uv venv $venv --python 3.12 --clear
if ($LASTEXITCODE -ne 0) { throw "uv venv failed (exit $LASTEXITCODE)" }
# NOTE: uv is a native exe — a non-zero exit does NOT trip $ErrorActionPreference,
# so guard $LASTEXITCODE explicitly or a half-synced venv silently feeds PyInstaller.
uv sync --frozen --no-default-groups --group build
if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)" }

Write-Host "[sidecar] running PyInstaller (onedir) ..." -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean (Join-Path $repo "packaging\core_rpc.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$out = Join-Path $repo "desktop\resources\sidecar"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
Copy-Item -Recurse (Join-Path $repo "dist\core_rpc") $out

Write-Host "[sidecar] done -> $out" -ForegroundColor Green

# Smoke test the frozen exe over its HTTP transport (ADR-0010): start it, read the
# VC_RPC_PORT stdout handshake, ping over POST /rpc, then shut it down. (The old
# test piped JSON to stdin — that hangs now: the server ignores stdin and serves.)
Write-Host "[sidecar] smoke test (HTTP):" -ForegroundColor Cyan
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = Join-Path $out "core_rpc.exe"
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$p = [System.Diagnostics.Process]::Start($psi)
try {
    $port = $null
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $line = $p.StandardOutput.ReadLine()   # blocks until a line or stream close
        if ($null -eq $line) { break }          # process exited without handshake
        if ($line -match '^VC_RPC_PORT (\d+)') { $port = [int]$Matches[1]; break }
    }
    if (-not $port) { throw "sidecar smoke: no VC_RPC_PORT handshake" }
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$port/rpc" -Method Post `
        -Body '{"jsonrpc":"2.0","method":"system.ping","params":{},"id":1}' `
        -ContentType "application/json" -TimeoutSec 10
    if (-not $resp.result.ok) { throw "sidecar smoke: ping failed: $($resp | ConvertTo-Json -Compress)" }
    Write-Host "[sidecar] smoke OK -> port $port, ping: $($resp.result | ConvertTo-Json -Compress)" -ForegroundColor Green
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$port/shutdown" -Method Post -Body '{}' `
            -ContentType "application/json" -TimeoutSec 3 | Out-Null
    } catch {}
} finally {
    if (-not $p.HasExited) { $p.Kill() }
}
