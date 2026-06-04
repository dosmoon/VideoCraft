@echo off
REM ── VideoCraft dev launcher ──────────────────────────────────────────────
REM Double-click from Explorer, or run `dev` / `.\dev.cmd` from a terminal.
REM Delegates to desktop\dev.ps1, which does the clean restart this project
REM needs: kill leftover electron.exe, free port 5174, clear node_modules/.vite,
REM unset ELECTRON_RUN_AS_NODE (else the Electron main process boots as plain
REM Node and crashes), then `pnpm dev`. Sidecar runs from myenv (Python).
REM Stop with Ctrl+C.
REM ─────────────────────────────────────────────────────────────────────────
title VideoCraft dev
pwsh -ExecutionPolicy Bypass -File "%~dp0desktop\dev.ps1"
echo.
echo [dev] electron-vite exited. Press any key to close this window.
pause >nul
