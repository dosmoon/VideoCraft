"""Opt-in heavy Python extras, installed into a writable py-extra dir (P3 §5.3).

Why this exists
---------------
The frozen sidecar (PyInstaller onedir) has two properties that break the naive
``sys.executable -m pip install`` used by dev installers:

  1. Its own site-packages are sealed / read-only — runtime pip can't write there.
  2. ``sys.executable`` is the frozen ``core_rpc.exe``, NOT a Python with pip. It
     ignores ``-m pip`` and just starts a second stdio sidecar that blocks on
     stdin forever — the "安装中…" hang the user hit on a real machine.

So all opt-in heavy extras — the CUDA runtime wheels (``core.gpu_install``) and
the embedded-AI runtimes faster-whisper / llama-cpp-python (``core.embedded_ai_install``)
— are installed with ``pip --target <user_data>/runtimes/py-extra`` and that dir
is prepended to ``sys.path`` at sidecar startup (``ensure_on_sys_path``).

pip itself is bundled into the freeze; we reach it without the deadlock via a
self-spawn the entry wrapper understands (``packaging/sidecar_entry.py``):

  - dev    : ``[sys.executable, "-m", "pip", ...]``           (real venv python)
  - frozen : ``[sys.executable, "--vc-pip", ...]``            (core_rpc.exe runs pip)

py-extra is used in dev too (parity — the packaged code path is exercised in dev,
no packaged-only blind spot — and it keeps the dev venv clean of opt-in extras).
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from typing import Callable, Iterable, Optional

from core.user_data import path as _ud_path

# All extras resolve as wheels only: an sdist build would invoke a PEP 517 build
# backend in a child interpreter, and under freeze that child is core_rpc.exe (no
# build tooling) — so force wheels. Every extra we ship (nvidia-*-cu12,
# ctranslate2, faster-whisper, llama-cpp-python CPU) publishes wheels.
_ONLY_BINARY = ("--only-binary", ":all:")


def py_extra_dir() -> str:
    """``<user_data>/runtimes/py-extra``, created on demand.

    The single writable site for opt-in heavy extras. Sits beside models/ and
    runtimes/node so it travels with the install ([[feedback_portable_data]]).
    """
    p = _ud_path("runtimes", "py-extra")
    os.makedirs(p, exist_ok=True)
    return p


_ON_PATH = False


def ensure_on_sys_path() -> None:
    """Prepend py-extra to ``sys.path`` so runtime-installed extras import.

    Idempotent. Safe to call before anything is installed there — in dev the
    empty dir is a no-op and imports fall back to the venv. Also registers the
    dir as a DLL search root for wheels that drop DLLs at the top level.
    """
    global _ON_PATH
    if _ON_PATH:
        return
    _ON_PATH = True
    d = py_extra_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    if sys.platform == "win32":
        try:
            os.add_dll_directory(d)
        except (FileNotFoundError, OSError):
            pass


def pip_command(args: list[str]) -> list[str]:
    """Build the argv to invoke bundled pip — frozen self-spawn vs dev ``-m pip``.

    Frozen: ``core_rpc.exe --vc-pip <args>`` — the entry wrapper runs pip in the
    frozen interpreter and exits, instead of starting the stdio server.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--vc-pip", *args]
    return [sys.executable, "-m", "pip", *args]


def install(packages: Iterable[str],
            on_line: Optional[Callable[[str], None]] = None,
            cancel_token=None,
            extra_args: Optional[list[str]] = None) -> int:
    """``pip install --target <py-extra> --upgrade --only-binary :all: <packages>``.

    Streams pip's combined stdout/stderr to ``on_line``; honours ``cancel_token``
    (an object with a ``.cancelled`` attribute) between lines. Returns pip's exit
    code (0 on success).
    """
    pkgs = list(packages)
    args = [
        "install",
        "--target", py_extra_dir(),
        "--upgrade",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        *_ONLY_BINARY,
        *(extra_args or []),
        *pkgs,
    ]
    rc = _stream(pip_command(args), on_line, cancel_token)
    if rc == 0:
        # py-extra is already on sys.path (ensure_on_sys_path at startup), but the
        # import system caches directory listings — a finder that scanned the dir
        # while it was empty won't see the just-written package. Invalidate so the
        # freshly installed extra is importable in THIS running sidecar, no restart.
        importlib.invalidate_caches()
    return rc


def is_installed(packages: Iterable[str]) -> bool:
    """True when every name in ``packages`` has a dist-info dir in py-extra.

    Checks py-extra specifically (not importability) so a copy living in the dev
    venv can't mask the fact that the opt-in extra was never installed here.
    """
    target = py_extra_dir()
    return all(_dist_info_dirs(target, pkg) for pkg in packages)


def uninstall(packages: Iterable[str],
              on_line: Optional[Callable[[str], None]] = None) -> int:
    """Remove ``packages`` from py-extra.

    pip's ``uninstall`` does not support ``--target``, so we delete each
    distribution's recorded files ourselves (the only reliable way to uninstall
    from a ``--target`` dir). Returns 0 always — a missing dist is a no-op.
    """
    target = py_extra_dir()
    for pkg in packages:
        _remove_distribution(target, pkg, on_line)
    return 0


# ── internals ────────────────────────────────────────────────────────────────

def _stream(cmd: list[str], on_line, cancel_token) -> int:
    """Run ``cmd``, streaming combined stdout/stderr line-by-line. Shared shape
    with core.gpu_install._stream (cancel between lines, kill on exit)."""
    if on_line is not None:
        on_line(f"$ {' '.join(cmd)}")
    env = None
    if getattr(sys, "frozen", False):
        # We are a frozen exe spawning another copy of the SAME frozen exe
        # (core_rpc.exe --vc-pip). PyInstaller's bootloader marks its context
        # with _PYI*/_MEIPASS2 env vars; if the child inherits them it thinks
        # it is already inside the parent's frozen bootstrap and stalls instead
        # of starting cleanly (the frozen-spawns-frozen pitfall — this is the
        # GUI-only install hang). Strip them so the child bootstraps fresh.
        env = {k: v for k, v in os.environ.items()
               if not (k.startswith("_PYI") or k == "_MEIPASS2")}
    proc = subprocess.Popen(
        cmd,
        # pip needs no input; never inherit the sidecar's JSON-RPC stdin.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        # Suppress a flashing console window on Windows.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=env,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_line is not None:
                try:
                    on_line(line.rstrip())
                except Exception:
                    pass
            if cancel_token is not None and getattr(cancel_token, "cancelled", False):
                proc.terminate()
                break
        return proc.wait()
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


def _dist_info_dirs(target: str, pkg: str) -> list[str]:
    """Find ``<dist>.dist-info`` dirs in ``target`` for project name ``pkg``.

    pip normalizes a project name to its dist-info prefix by lowercasing and
    replacing runs of ``-_.`` with ``_`` (PEP 503 / 427). e.g.
    ``nvidia-cublas-cu12`` → ``nvidia_cublas_cu12-<ver>.dist-info``.
    """
    norm = pkg.lower().replace("-", "_").replace(".", "_")
    out: list[str] = []
    if not os.path.isdir(target):
        return out
    for name in os.listdir(target):
        if not name.endswith(".dist-info"):
            continue
        stem = name[: -len(".dist-info")]
        proj = stem.rsplit("-", 1)[0]  # drop the version segment
        if proj.lower().replace("-", "_").replace(".", "_") == norm:
            out.append(os.path.join(target, name))
    return out


def _remove_distribution(target: str, pkg: str, on_line) -> None:
    """Delete every file a distribution recorded, then its dist-info."""
    def log(msg: str) -> None:
        if on_line is not None:
            try:
                on_line(msg)
            except Exception:
                pass

    info_dirs = _dist_info_dirs(target, pkg)
    if not info_dirs:
        log(f"[skip] {pkg}: not installed in py-extra")
        return
    for info in info_dirs:
        record = os.path.join(info, "RECORD")
        removed_dirs: set[str] = set()
        if os.path.isfile(record):
            with open(record, "r", encoding="utf-8") as f:
                for raw in f:
                    rel = raw.split(",", 1)[0].strip()
                    if not rel:
                        continue
                    abs_path = os.path.normpath(os.path.join(target, rel))
                    # Stay inside target — never follow a stray absolute/.. entry.
                    if not abs_path.startswith(os.path.abspath(target)):
                        continue
                    try:
                        if os.path.isfile(abs_path) or os.path.islink(abs_path):
                            os.remove(abs_path)
                            removed_dirs.add(os.path.dirname(abs_path))
                    except OSError:
                        pass
        # Best-effort prune of now-empty dirs (deepest first), then the dist-info.
        for d in sorted(removed_dirs, key=len, reverse=True):
            try:
                os.removedirs(d)
            except OSError:
                pass
        shutil.rmtree(info, ignore_errors=True)
        log(f"removed {os.path.basename(info)}")
