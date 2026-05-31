#!/usr/bin/env bash
# Clean restart for the VideoCraft Electron dev app (bash / Git-Bash).
# Mirror of dev.ps1 — see that file's header for the why.
#   1. unset ELECTRON_RUN_AS_NODE (else the main process boots as Node and crashes)
#   2. kill leftover electron + free port 5174 + clear node_modules/.vite
#      (HMR is unreliable here; full restart only). Python sidecar reloads only
#      on a full app restart.
# Usage:  cd desktop && ./dev.sh   (or: bash dev.sh)
set -u
cd "$(dirname "$0")"

echo "[dev] killing leftover electron ..."
taskkill //IM electron.exe //F >/dev/null 2>&1 || true

echo "[dev] freeing dev port 5174 ..."
# Best-effort: find the PID listening on 5174 and kill it.
pid=$(netstat -ano 2>/dev/null | grep -E "[:.]5174 .*LISTENING" | awk '{print $NF}' | head -1)
[ -n "${pid:-}" ] && taskkill //PID "$pid" //F >/dev/null 2>&1 || true

echo "[dev] clearing Vite cache (node_modules/.vite) ..."
rm -rf node_modules/.vite 2>/dev/null || true

echo "[dev] starting electron-vite (renderer on http://localhost:5174) ..."
echo "      Open a project, then a news_desk creation, to test the new workbench."
env -u ELECTRON_RUN_AS_NODE pnpm dev
