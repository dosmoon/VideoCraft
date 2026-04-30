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
    """Return absolute path to <repo>/user_data/, creating it on demand."""
    here = os.path.dirname(os.path.abspath(__file__))
    # src/core -> src -> <repo root>
    root = os.path.normpath(os.path.join(here, "..", ".."))
    path = os.path.join(root, "user_data")
    os.makedirs(path, exist_ok=True)
    return path


def path(*parts: str) -> str:
    """Return <repo>/user_data/<parts...>. Parent directory NOT auto-created."""
    return os.path.join(user_data_dir(), *parts)


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


# Run once at import. user_data is imported transitively by i18n/hub_layout/
# burn_presets/project/composer, all before any of them read state.
_migrate_legacy_home()
