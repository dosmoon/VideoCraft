"""Environment detection utilities.

Lightweight version checks for yt-dlp and Python SDKs. All public functions
return a version string on success, or None if the component is missing.
No side effects; safe to call from the UI thread.
"""

from __future__ import annotations

import shutil
import subprocess


def _run_version(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=5)
        if r.returncode == 0:
            return (r.stdout.strip() or r.stderr.strip()) or None
    except Exception:
        pass
    return None


def check_ytdlp() -> str | None:
    """Return yt-dlp version string or None."""
    try:
        from importlib.metadata import version
        return version("yt-dlp")
    except Exception:
        pass
    ytdlp = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    return _run_version([ytdlp, "--version"]) if ytdlp else None


def check_fish_audio_sdk() -> str | None:
    """Return fish-audio-sdk version or None."""
    try:
        from importlib.metadata import version
        return version("fish-audio-sdk")
    except Exception:
        return None


def check_openai_sdk() -> str | None:
    """Return openai package version or None."""
    try:
        from importlib.metadata import version
        return version("openai")
    except Exception:
        return None
