"""Task -> JSON schema registry for the AI Console Playground.

The Playground needs to know which tasks expect a structured JSON output
(use ai.complete_json with a schema) versus plain text (ai.complete).
This module is the single read-only lookup; feature modules continue to
own their schemas.

Adding a new structured task: import its schema constant here and add
an entry to SCHEMAS. Tasks not in SCHEMAS are treated as text-only.
"""

from __future__ import annotations

from core.srt_ops import SUBTITLE_PACK_SCHEMA
from core.program.clip import RANK_SCHEMA, PEAKS_SCHEMA, PACKAGE_SCHEMA


SCHEMAS: dict[str, dict] = {
    "subtitle.pack":       SUBTITLE_PACK_SCHEMA,
    "clip.rank-chapters":  RANK_SCHEMA,
    "clip.find-peaks":     PEAKS_SCHEMA,
    "clip.package":        PACKAGE_SCHEMA,
}


def has_schema(task: str) -> bool:
    return task in SCHEMAS


def get_schema(task: str) -> dict | None:
    return SCHEMAS.get(task)
