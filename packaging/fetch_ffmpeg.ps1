# Fetch a pinned static ffmpeg (gyan.dev "essentials" build: x264/x265/nvenc,
# enough for our merge / cut / probe / transcode uses) into desktop/resources/
# for bundling into the installer (packaging-design.md §6).
#
# ffmpeg is a STABLE, infrequently-updated dependency — unlike yt-dlp it does
# not chase YouTube. Bump $Version deliberately (a few times a year at most),
# NOT per release. See ADR-0009 / packaging-design.md §10.
#
# Idempotent: skips the download when the pinned version is already present.
#
# Usage:  ./packaging/fetch_ffmpeg.ps1   (run before pnpm build:win)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# gyan.dev publishes versioned, immutable release builds on GitHub.
$Version = "7.1.1"
$dest = Join-Path $repo "desktop\resources"
$marker = Join-Path $dest "ffmpeg.version"
$ffmpeg = Join-Path $dest "ffmpeg.exe"
$ffprobe = Join-Path $dest "ffprobe.exe"

if ((Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $Version) `
        -and (Test-Path $ffmpeg) -and (Test-Path $ffprobe)) {
    Write-Host "[ffmpeg] $Version already present in $dest — skip." -ForegroundColor Green
    return
}

$url = "https://github.com/GyanD/codexffmpeg/releases/download/$Version/ffmpeg-$Version-essentials_build.zip"
$tmpZip = Join-Path $env:TEMP "ffmpeg-$Version-essentials.zip"
$tmpDir = Join-Path $env:TEMP "ffmpeg-$Version-essentials"

Write-Host "[ffmpeg] downloading $url ..." -ForegroundColor Cyan
# IWR's progress bar throttles large downloads dramatically — silence it.
$ProgressPreference = "SilentlyContinue"
Invoke-WebRequest -Uri $url -OutFile $tmpZip

Write-Host "[ffmpeg] extracting ffmpeg.exe + ffprobe.exe ..." -ForegroundColor Cyan
if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
Expand-Archive -Path $tmpZip -DestinationPath $tmpDir
$bin = Join-Path $tmpDir "ffmpeg-$Version-essentials_build\bin"

New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $bin "ffmpeg.exe") $ffmpeg -Force
Copy-Item (Join-Path $bin "ffprobe.exe") $ffprobe -Force   # ffplay.exe skipped (unused, ~saves a 3rd binary)
Set-Content -Path $marker -Value $Version -NoNewline

Remove-Item -Force $tmpZip
Remove-Item -Recurse -Force $tmpDir
$mb = [math]::Round(((Get-Item $ffmpeg).Length + (Get-Item $ffprobe).Length) / 1MB)
Write-Host "[ffmpeg] done -> $dest (ffmpeg.exe + ffprobe.exe, $Version, ${mb}MB)" -ForegroundColor Green
