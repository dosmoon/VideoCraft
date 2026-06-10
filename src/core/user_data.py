"""User data hub — single source of truth for the user_data/ directory.

All cross-session user state (language, hub layout, recent projects, burn
presets, composer autosave) lives under `<repo>/user_data/`. Keeping it
inside the software root makes the build truly portable: zip the folder,
hand it to another machine, configs travel along.

Legacy location was `~/.videocraft/`. On first import this module migrates
the old files into the new layout (copy, not move — old files stay so
parallel installs / rollbacks keep working). Migration is idempotent and
only runs when a destination file is missing.
"""

from __future__ import annotations

import os
import shutil


def user_data_dir() -> str:
    """Return absolute path to the user_data/ root, creating it on demand.

    Resolution order:
      1. ``VC_USER_DATA`` env var — set by the Electron host (paths.ts) to the
         install-local user_data dir. REQUIRED in a packaged build: there the
         sidecar is a frozen exe whose ``__file__`` resolves under the (sealed,
         update-wiped) resources/ tree, so a relative guess would put models /
         settings / py-extra somewhere that vanishes on upgrade. The host knows
         the writable, install-local location and injects it.
      2. ``<repo>/user_data`` — the dev default (this file is src/core/, two up
         is the repo root), keeping a source checkout self-contained.
    """
    env_root = os.environ.get("VC_USER_DATA", "").strip()
    if env_root:
        path = os.path.abspath(env_root)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        # src/core -> src -> <repo root>
        root = os.path.normpath(os.path.join(here, "..", ".."))
        path = os.path.join(root, "user_data")
    os.makedirs(path, exist_ok=True)
    return path


def path(*parts: str) -> str:
    """Return <repo>/user_data/<parts...>. Parent directory NOT auto-created."""
    return os.path.join(user_data_dir(), *parts)


def keys_dir() -> str:
    """Return absolute path to the dir holding providers.json + provider .key files.

    Frozen (packaged): ``<user_data>/keys`` — beside the exe, preserved across
    updates by the NSIS customRemoveFiles macro. Deliberately NOT
    ``__file__``-relative: in a PyInstaller build that resolves inside the
    sealed, update-wiped resources/ tree.
    Dev: the repo's top-level ``keys/`` (this file is src/core/user_data.py; two
    up is the repo root).

    Single source for BOTH the writer (core.ai.config.save_config) and the
    reader (core.paths models_dir override). They were once two separate
    __file__-relative implementations that drifted: a fix moved the writer to
    user_data/keys but left the reader pointing at the sealed resources/keys, so
    in packaged builds the models-dir override was written but never read back.
    """
    import sys

    if getattr(sys, "frozen", False):
        return path("keys")
    here = os.path.dirname(os.path.abspath(__file__))
    # src/core -> src -> <repo root>
    return os.path.normpath(os.path.join(here, "..", "..", "keys"))


# ── Legacy migration ────────────────────────────────────────────────────────

_LEGACY_DIR = os.path.join(os.path.expanduser("~"), ".videocraft")

# (legacy_relpath, new_relpath, is_dir)
_MIGRATE_ITEMS = [
    ("settings.json",         "settings.json",         False),
    ("layout.json",           "layout.json",           False),
    ("recent.json",           "recent.json",           False),
    ("composer_project.json", "composer_project.json", False),
    ("presets",               "presets",               True),
]


def _migrate_legacy_home() -> None:
    """Copy ~/.videocraft/<file> → <repo>/user_data/<file> when destination
    is missing. Old files are kept intact. Errors are swallowed: a failed
    migration must not block app startup."""
    if not os.path.isdir(_LEGACY_DIR):
        return
    target = user_data_dir()
    for legacy_name, new_name, is_dir in _MIGRATE_ITEMS:
        src = os.path.join(_LEGACY_DIR, legacy_name)
        dst = os.path.join(target, new_name)
        if not os.path.exists(src) or os.path.exists(dst):
            continue
        try:
            if is_dir:
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except (OSError, shutil.Error):
            pass


# Run once at import. user_data is imported transitively by i18n/project and
# the core modules, all before any of them read state.
_migrate_legacy_home()
