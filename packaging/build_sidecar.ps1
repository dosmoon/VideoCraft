# Build the VideoCraft core_rpc sidecar into a PyInstaller onedir (P3).
# packaging-design.md §2. Output: desktop/resources/sidecar/core_rpc.exe (+ _internal/).
#
# Uses a CLEAN uv venv built from requirements-base.txt — NOT the polluted 7GB dev
# myenv. Embedded-AI native deps (faster-whisper / llama-cpp-python) are excluded
# on purpose (opt-in at runtime, packaging-design.md §5.3).
#
# Usage:  ./packaging/build_sidecar.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$venv = Join-Path $repo ".build\sidecar-venv"
$py = Join-Path $venv "Scripts\python.exe"

Write-Host "[sidecar] creating clean build venv (uv, python 3.12) at $venv ..." -ForegroundColor Cyan
# --clear: always rebuild from scratch. Without it uv skips an existing venv, so a
# stale one (e.g. missing a newly-pinned dep like pip) silently survives — the
# freeze must reflect requirements-base.txt exactly.
uv venv $venv --python 3.12 --clear

Write-Host "[sidecar] installing base deps + pyinstaller ..." -ForegroundColor Cyan
uv pip install --python $py -r (Join-Path $repo "requirements-base.txt")
uv pip install --python $py "pyinstaller==6.16.0"

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
