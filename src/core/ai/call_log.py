"""Local AI-call log — append-only JSONL under user_data/logs/.

One line per cloud/local API call: request shape (no payload), response
shape (preview + citations + usage), latency, error. Lets the user
verify whether features like Grok Live Search actually triggered
(citations present in response) without xAI's console showing
prompt/response bodies.

Logging is best-effort — failures here MUST NOT propagate. The log
auto-rotates when it exceeds ROTATE_AT lines (keeps the last half).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from core import user_data


_LOG_REL = os.path.join("logs", "ai-calls.jsonl")
ROTATE_AT = 2000  # trim to last 1000 when exceeded


def log_path() -> str:
    """Absolute path to the log file. Parent dirs created on demand."""
    p = user_data.path(_LOG_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def append(entry: dict) -> None:
    """Append one JSON line. Adds `ts` (UTC ISO). Never raises."""
    try:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 **entry}
        path = log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _maybe_rotate(path)
    except Exception:
        pass


def _maybe_rotate(path: str) -> None:
    """When line count exceeds ROTATE_AT, truncate to last ROTATE_AT//2."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= ROTATE_AT:
            return
        keep = lines[-(ROTATE_AT // 2):]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(keep)
    except Exception:
        pass
