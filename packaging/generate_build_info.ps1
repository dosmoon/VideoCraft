# Generate build-info.json — the per-BUILD identity that the release VERSION
# does not carry (docs/versioning.md):
#   build   = a monotonic counter (CI: $env:BUILD_NUMBER = github.run_number;
#             local fallback: git commit count)
#   commit  = short git SHA
#   builtAt = ISO-8601 UTC build timestamp
#
# `version` is deliberately NOT written here — the app reads it from
# package.json via app.getVersion() (single source, no drift).
#
# Run before `pnpm build:win`, alongside build_sidecar.ps1 / fetch_ffmpeg.ps1.
# CI runs it as an explicit step with BUILD_NUMBER set. The file is written to
# BOTH desktop/build/ (dev path, electron/paths.ts dev branch) and
# desktop/resources/ (shipped via electron-builder extraResources). When absent
# the app falls back to a "dev" build identity (electron/buildInfo.ts).
#
# Usage:  ./packaging/generate_build_info.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# Build number: CI injects BUILD_NUMBER (github.run_number). Locally fall back to
# the commit count — monotonic, and fits a Windows FileVersion uint16 segment for
# a long time. (CI shallow-clones, so the count is unreliable there; that's why
# CI sets BUILD_NUMBER and never hits this fallback.)
$build = $env:BUILD_NUMBER
if ([string]::IsNullOrWhiteSpace($build)) {
    $build = (git -C $repo rev-list --count HEAD).Trim()
}
$commit = (git -C $repo rev-parse --short HEAD).Trim()
$builtAt = [System.DateTime]::UtcNow.ToString("o")

$info = [ordered]@{
    build   = "$build"
    commit  = $commit
    builtAt = $builtAt
} | ConvertTo-Json -Compress

$buildDir = Join-Path $repo "desktop\build"      # dev: paths.ts reads here
$resDir = Join-Path $repo "desktop\resources"     # packaged: extraResources ships it
New-Item -ItemType Directory -Force -Path $buildDir, $resDir | Out-Null
Set-Content -Path (Join-Path $buildDir "build-info.json") -Value $info -NoNewline
Set-Content -Path (Join-Path $resDir "build-info.json") -Value $info -NoNewline

Write-Host "[build-info] build=$build commit=$commit builtAt=$builtAt" -ForegroundColor Green
