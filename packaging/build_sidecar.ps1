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
uv sync --frozen --no-default-groups --group build

Write-Host "[sidecar] running PyInstaller (onedir) ..." -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean (Join-Path $repo "packaging\core_rpc.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$out = Join-Path $repo "desktop\resources\sidecar"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
Copy-Item -Recurse (Join-Path $repo "dist\core_rpc") $out

Write-Host "[sidecar] done -> $out" -ForegroundColor Green
Write-Host "[sidecar] smoke test:" -ForegroundColor Cyan
$req = '{"jsonrpc":"2.0","method":"system.get_locale","params":{},"id":1}'
$req | & (Join-Path $out "core_rpc.exe")
