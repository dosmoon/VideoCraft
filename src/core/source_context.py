"""Source content context — user-augmented metadata about the source video.

Sits next to the technical metadata (`source/meta.json` from yt-dlp/ffprobe)
and feeds into AI prompts so subtitle analyses (chapters / titles /
hotclips) produce non-generic outputs anchored to the actual subject
matter, speakers, audience, and platform tone.

This schema migrated from core/program/clip.py (Phase C's
ProjectBackground dataclass) — same fields, new home, renamed
SourceContext to reflect that it describes the source video specifically
rather than a generic "project background". The old location is kept
for one release cycle as a deprecation shim; new code should import
from here.

All fields are optional. Empty/missing fields are simply omitted from
the prompt context block (no "(unset)" placeholders that would dilute
the AI's signal).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


SOURCE_CONTEXT_FILENAME = "context.json"


@dataclass
class SourceContext:
    """Free-form context describing the source material."""
    show_type: str = ""          # 访谈 / 演讲 / 直播切片 / 课程 / 评论 / 解说
    host: str = ""               # main speaker / host name
    host_bio: str = ""           # one-line identity / role
    guests: str = ""             # other on-screen people (free text, comma-separated)
    audience: str = ""           # target audience profile
    episode_topic: str = ""      # episode-level topic / YouTube title
    platform_tone: str = ""      # B 站 / 抖音 / 小红书 / YouTube
    notes: str = ""              # misc: sensitive topics, taboo words, tone hints

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceContext":
        """Tolerant: drops unknown keys, missing keys default to ''."""
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in fields and isinstance(v, str)})

    def is_empty(self) -> bool:
        """True when every field is blank — used to skip prompt injection."""
        return not any(getattr(self, f).strip() for f in self.__dataclass_fields__)

    def as_prompt_block(self) -> str:
        """Render as a markdown block to prepend to AI prompts. Empty fields
        are omitted entirely (not rendered as "field: (unset)") so the AI
        doesn't waste context on null signals."""
        if self.is_empty():
            return ""
        lines = ["以下是源视频的内容背景，请在生成时充分考虑："]
        labels = [
            ("show_type",     "节目类型"),
            ("host",          "主讲人"),
            ("host_bio",      "身份"),
            ("guests",        "嘉宾"),
            ("audience",      "观众"),
            ("episode_topic", "整集主题"),
            ("platform_tone", "平台语气"),
            ("notes",         "备注"),
        ]
        for field, zh in labels:
            val = getattr(self, field).strip()
            if val:
                lines.append(f"- {zh}: {val}")
        return "\n".join(lines)


def context_path(source_dir: str) -> str:
    """Canonical location: <source_dir>/context.json (next to meta.json)."""
    return os.path.join(source_dir, SOURCE_CONTEXT_FILENAME)


def read_context(source_dir: str) -> SourceContext:
    """Read context from disk; return empty SourceContext if not present."""
    path = context_path(source_dir)
    if not os.path.isfile(path):
        return SourceContext()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return SourceContext()
    if not isinstance(data, dict):
        return SourceContext()
    return SourceContext.from_dict(data)


def write_context(source_dir: str, ctx: SourceContext) -> None:
    """Persist context.json atomically (temp + rename)."""
    os.makedirs(source_dir, exist_ok=True)
    path = context_path(source_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ctx.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_platform_metadata(source_dir: str) -> dict:
    """Read read-only platform metadata from `source/meta.json` (yt-dlp output)
    so the edit UI can show uploader / description / tags / etc. as
    reference. Returns a dict; empty if file is missing or malformed.
    """
    path = os.path.join(source_dir, "meta.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}
