"""Shared low-level IO helpers.

Atomic writers used by any module that persists JSON / text artifacts.
Lives here (rather than inside a feature module) so cross-feature
writers don't reach into siblings' private helpers.
"""

from __future__ import annotations

import json
import os
from typing import Any


def atomic_write_text(path: str, text: str) -> None:
    """Write text to path via a temp file + rename to avoid partial files."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def atomic_write_json(path: str, data: Any) -> None:
    """Atomic write of pretty-printed UTF-8 JSON with trailing newline."""
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
