"""
hub_layout.py - Persistent Hub window layout.

Stores the Hub main window geometry, PanedWindow sash positions, and zoom
state across sessions. Uses the same ~/.videocraft/ convention as
project.py's recent.json.
"""

import json
import os
from typing import Any


LAYOUT_DIR = os.path.join(os.path.expanduser("~"), ".videocraft")
LAYOUT_FILE = os.path.join(LAYOUT_DIR, "layout.json")


DEFAULT_LAYOUT: dict = {
    "geometry":      "1280x800",   # first-run fallback, applied before zoom
    "zoomed":        True,         # start maximized by default
    "sidebar_width": 320,          # horizontal PanedWindow sash (sidebar width)
    "log_height":    90,           # bottom log panel height
    "sidebar_tab":   "project",    # selected sidebar tab — "project" | "resources"
}


def load_layout() -> dict:
    """Read layout from disk. Returns a copy of DEFAULT_LAYOUT on miss/corruption."""
    if not os.path.exists(LAYOUT_FILE):
        return dict(DEFAULT_LAYOUT)
    try:
        with open(LAYOUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_LAYOUT)

    if not isinstance(data, dict):
        return dict(DEFAULT_LAYOUT)

    # Fill in any missing keys with defaults so callers can rely on presence.
    merged = dict(DEFAULT_LAYOUT)
    for key in DEFAULT_LAYOUT:
        if key in data:
            merged[key] = data[key]
    return merged


def save_layout(layout: dict) -> None:
    """Persist layout to disk, creating the parent directory as needed."""
    os.makedirs(LAYOUT_DIR, exist_ok=True)
    # Only keep known keys to avoid leaking random state into the file.
    payload: dict[str, Any] = {k: layout.get(k, DEFAULT_LAYOUT[k]) for k in DEFAULT_LAYOUT}
    with open(LAYOUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
