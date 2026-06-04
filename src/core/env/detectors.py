"""Detection functions for each environment component.

Each detect_* function returns a DetectResult. They must be safe to call
from the UI thread — no blocking network I/O, short subprocess timeouts.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from core.env.types import DetectResult


_TIMEOUT_SECS = 5


def _run_version(cmd: list[str]) -> str | None:
    """Run a `--version` command, returning the trimmed stdout or None."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, encoding="utf-8",
            errors="replace", timeout=_TIMEOUT_SECS,
        )
        if r.returncode == 0:
            return (r.stdout.strip() or r.stderr.strip()) or None
    except Exception:
        pass
    return None


def _parse_version_token(version_text: str) -> str:
    """Extract the version token from typical `--version` output.

    Strategies, in order:
      1. Token immediately following the word 'version' (covers ffmpeg / ffprobe
         which print 'ffmpeg version N-118776-...').
      2. First token starting with a digit (covers 'v22.11.0' style — strip the
         leading 'v' for cleaner display).
      3. First non-empty line as a fallback.
    """
    tokens = version_text.split()
    # Strategy 1: token after literal 'version' (case-insensitive)
    for i, tok in enumerate(tokens[:-1]):
        if tok.lower() == "version":
            return tokens[i + 1]
    # Strategy 2: first digit-led token
    for tok in tokens:
        if tok and (tok[0].isdigit() or (tok.startswith("v") and len(tok) > 1 and tok[1].isdigit())):
            return tok.lstrip("vV") if tok[0] in "vV" else tok
    # Strategy 3: first line
    return version_text.split("\n", 1)[0]


# ── Binary detectors ─────────────────────────────────────────────────────────


def _bin_source(path: str) -> str:
    """'bundled' when `path` lives inside the packaged resources dir
    (VC_BUNDLED_BIN, injected by the Electron launcher for the frozen build where
    ffmpeg/ffprobe ship beside the sidecar), else 'system'. Lets the env UI label
    a shipped binary as 内置 rather than 系统. No VC_BUNDLED_BIN (dev) → 'system'."""
    bundled = os.environ.get("VC_BUNDLED_BIN")
    if bundled and path:
        try:
            root = os.path.realpath(bundled)
            if os.path.commonpath([os.path.realpath(path), root]) == root:
                return "bundled"
        except (ValueError, OSError):
            pass
    return "system"


def detect_ffmpeg() -> DetectResult:
    path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if not path:
        return DetectResult(available=False)
    raw = _run_version([path, "-version"])
    version = _parse_version_token(raw) if raw else None
    return DetectResult(available=True, version=version, source=_bin_source(path), path=path)


def detect_ffprobe() -> DetectResult:
    path = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if not path:
        return DetectResult(available=False)
    raw = _run_version([path, "-version"])
    version = _parse_version_token(raw) if raw else None
    return DetectResult(available=True, version=version, source=_bin_source(path), path=path)


def detect_node() -> DetectResult:
    """Look up Node.js: managed install first, then system PATH."""
    from core.env import node_manager
    managed = node_manager.managed_node_path()
    if managed:
        version = _run_version([managed, "--version"])
        return DetectResult(available=True, version=version, source="managed", path=managed)
    system = shutil.which("node") or shutil.which("node.exe")
    if not system:
        return DetectResult(available=False)
    version = _run_version([system, "--version"])
    return DetectResult(available=True, version=version, source="system", path=system)


def detect_claude_cli() -> DetectResult:
    """Detect the local Claude CLI used by the ClaudeCode AI provider."""
    path = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if not path:
        return DetectResult(available=False)
    raw = _run_version([path, "--version"])
    version = _parse_version_token(raw) if raw else None
    return DetectResult(available=True, version=version, source="system", path=path)


# ── Python package detector factory ──────────────────────────────────────────


def detect_pip(package_name: str, import_name: str | None = None):
    """Return a detect function for a pip-installed package.

    Frozen-aware. The base bundle ships some of these (yt-dlp, openai, Pillow,
    google-genai, fish-audio-sdk) inside the PyInstaller archive WITHOUT dist-info
    metadata, so importlib.metadata can't see them and would falsely report "not
    installed". So we:
      1. make py-extra visible first (runtime upgrades install there),
      2. try metadata for an exact version (hits a py-extra upgrade if present),
      3. fall back to importability so a bundled-but-metadata-less copy still
         reports available (version unknown).
    `import_name` is the module to probe when it differs from the project name
    (e.g. Pillow→PIL, google-genai→google.genai).
    """
    mod = import_name or package_name.replace("-", "_")

    def _detect() -> DetectResult:
        try:
            from core.runtime_extras import ensure_on_sys_path
            ensure_on_sys_path()
        except Exception:
            pass
        from importlib.metadata import version, PackageNotFoundError
        try:
            v = version(package_name)
            return DetectResult(available=True, version=v, source="pip")
        except PackageNotFoundError:
            pass
        except Exception:
            pass
        # Bundled into the frozen base (no dist-info) → importability is the truth.
        import importlib.util
        try:
            if importlib.util.find_spec(mod) is not None:
                return DetectResult(available=True, version=None, source="bundled")
        except Exception:
            pass
        return DetectResult(available=False)

    return _detect
