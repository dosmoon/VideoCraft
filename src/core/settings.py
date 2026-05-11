"""Tiny generic settings facade over <repo>/user_data/settings.json.

Used for cross-session flat key-value state. Existing keys: "language"
(via i18n.py). New keys (P2+): "link_disclaimer_accepted",
"last_parent_dir", "default_parent_dir".

Reads are tolerant — missing file, corrupt JSON, or non-dict content all
return the supplied default. Writes are atomic enough for a single
desktop user (write whole file each time). Concurrent writers from two
VideoCraft instances would race, but that's not a supported scenario.
"""

from __future__ import annotations

import json
import os
from typing import Any

from core import user_data


def _settings_path() -> str:
    return user_data.path("settings.json")


def _read_all() -> dict:
    path = _settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default: Any = None) -> Any:
    """Return settings[key] or default if missing/corrupt."""
    return _read_all().get(key, default)


def set_(key: str, value: Any) -> None:
    """Persist settings[key] = value, preserving existing keys."""
    path = _settings_path()
    data = _read_all()
    data[key] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Named differently than dict.set to avoid shadowing; export both forms.
set = set_  # type: ignore  # noqa: A001


if __name__ == "__main__":
    # Smoke test
    set_("smoke_test_key", "hello")
    assert get("smoke_test_key") == "hello"
    set_("smoke_test_key", 42)
    assert get("smoke_test_key") == 42
    # Clean up
    data = _read_all()
    data.pop("smoke_test_key", None)
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("settings smoke OK")
