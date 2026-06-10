"""Project schema dataclasses (new model, 2026-05-11).

Single source of truth for `.videocraft/project.json` shape. Used by the
Project class and any UI that needs to construct or inspect project
metadata. See docs/_archive/project-restructure.md for the full design.

Layout under a project folder:
    <project>/
      .videocraft/project.json     ← serialized ProjectMeta
      .videocraft/background.json  ← AI context, not part of ProjectMeta
      source/video.mp4
      source/meta.json
      subtitles/*.srt
      derivatives/<type>/<instance>/...

Backward compat: old projects opened via Project.open() may have a
different shape (no schema_version, only `version` + `created`). Those
are tolerated — from_dict() returns a ProjectMeta with defaults filled
in. The old manifest pipeline keeps working until P6 cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# Origin of the source video. "link" = downloaded via yt-dlp (no specific
# site name surfaced anywhere in the UI). "local" = imported from a local
# file. Keep neutral wording for legal posture.
ORIGIN_LINK = "link"
ORIGIN_LOCAL = "local"


@dataclass
class ClipRange:
    """Optional time range applied at source acquisition time.

    Format strings as `HH:MM:SS` or `MM:SS` (validated at the dialog).
    When set, only this range is downloaded (yt-dlp --download-sections)
    or copied (ffmpeg -ss/-to). All downstream timestamps reference the
    resulting source/video.mp4 local time (which starts at 00:00:00).
    """
    start: str
    end: str

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    @staticmethod
    def from_dict(d: dict | None) -> "ClipRange | None":
        if not d:
            return None
        start = d.get("start")
        end = d.get("end")
        if not start or not end:
            return None
        return ClipRange(start=str(start), end=str(end))


@dataclass
class Source:
    origin: str = ORIGIN_LINK            # ORIGIN_LINK | ORIGIN_LOCAL
    url: str | None = None               # populated when origin=link
    imported_from: str | None = None     # populated when origin=local
    clip_range: ClipRange | None = None  # optional sub-range
    title: str | None = None
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict:
        d: dict = {"origin": self.origin}
        if self.url is not None:
            d["url"] = self.url
        if self.imported_from is not None:
            d["imported_from"] = self.imported_from
        if self.clip_range is not None:
            d["clip_range"] = self.clip_range.to_dict()
        if self.title is not None:
            d["title"] = self.title
        if self.duration_sec is not None:
            d["duration_sec"] = self.duration_sec
        if self.width is not None:
            d["width"] = self.width
        if self.height is not None:
            d["height"] = self.height
        return d

    @staticmethod
    def from_dict(d: dict | None) -> "Source":
        if not d:
            return Source()
        return Source(
            origin=str(d.get("origin", ORIGIN_LINK)),
            url=d.get("url"),
            imported_from=d.get("imported_from"),
            clip_range=ClipRange.from_dict(d.get("clip_range")),
            title=d.get("title"),
            duration_sec=d.get("duration_sec"),
            width=d.get("width"),
            height=d.get("height"),
        )


@dataclass
class Language:
    source: str | None = None
    translated_to: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {}
        if self.source is not None:
            d["source"] = self.source
        if self.translated_to:
            d["translated_to"] = list(self.translated_to)
        return d

    @staticmethod
    def from_dict(d: dict | None) -> "Language":
        if not d:
            return Language()
        return Language(
            source=d.get("source"),
            translated_to=list(d.get("translated_to", []) or []),
        )


@dataclass
class ProjectMeta:
    """Top-level structure of .videocraft/project.json (v1)."""
    schema_version: int = SCHEMA_VERSION
    name: str = ""
    created_at: str = ""  # ISO 8601 UTC
    source: Source = field(default_factory=Source)
    language: Language = field(default_factory=Language)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "created_at": self.created_at,
            "source": self.source.to_dict(),
            "language": self.language.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict | None) -> "ProjectMeta":
        if not d:
            return ProjectMeta(created_at=now_iso())
        return ProjectMeta(
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            name=str(d.get("name", "")),
            created_at=str(d.get("created_at", "")),
            source=Source.from_dict(d.get("source")),
            language=Language.from_dict(d.get("language")),
        )


def now_iso() -> str:
    """UTC timestamp in ISO 8601 (seconds resolution)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Round-trip test: build a meta, serialize, deserialize, compare.
    meta = ProjectMeta(
        name="Demo Project",
        created_at=now_iso(),
        source=Source(
            origin=ORIGIN_LINK,
            url="https://example.com/video",
            clip_range=ClipRange(start="00:10:00", end="00:20:00"),
            title="Sample Title",
            duration_sec=600.0,
            width=1920,
            height=1080,
        ),
        language=Language(source="en", translated_to=["zh"]),
    )
    d = meta.to_dict()
    print("Serialized:", d)
    meta2 = ProjectMeta.from_dict(d)
    assert meta2.to_dict() == d, "round-trip mismatch"
    assert meta2.source.clip_range is not None
    assert meta2.source.clip_range.start == "00:10:00"
    assert meta2.language.translated_to == ["zh"]

    # Empty / missing data tolerated
    empty = ProjectMeta.from_dict({})
    assert empty.schema_version == SCHEMA_VERSION
    assert empty.source.origin == ORIGIN_LINK
    assert empty.language.translated_to == []

    # Old-style data (only version+created) → defaults fill in
    old = ProjectMeta.from_dict({"version": 1, "created": "2026-04-01"})
    assert old.name == ""  # old format had no name
    assert old.source.origin == ORIGIN_LINK  # default

    print("All smoke checks passed.")
