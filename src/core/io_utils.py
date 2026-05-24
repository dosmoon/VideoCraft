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
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    import time
    for i in range(10):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.05)


def atomic_write_json(path: str, data: Any) -> None:
    """Atomic write of pretty-printed UTF-8 JSON with trailing newline."""
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
