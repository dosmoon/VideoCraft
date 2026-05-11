"""Data model for Media Segment Composer.

No Tk dependency — pure data layer.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field


@dataclass
class MediaSegment:
    id: str
    text: str
    image_path: str | None
    audio_path: str | None
    extra_overlays: list = field(default_factory=list)  # Phase 2 reserved

    @classmethod
    def new(cls) -> "MediaSegment":
        return cls(id=str(uuid.uuid4()), text="", image_path=None, audio_path=None)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "image_path": self.image_path,
            "audio_path": self.audio_path,
            "extra_overlays": self.extra_overlays,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MediaSegment":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            text=d.get("text", ""),
            image_path=d.get("image_path"),
            audio_path=d.get("audio_path"),
            extra_overlays=d.get("extra_overlays", []),
        )


@dataclass
class ComposerProject:
    segments: list[MediaSegment] = field(default_factory=list)
    # Voice is now (provider, voice_id) — TTS picks carry both. Old
    # projects with only voice_id load with voice_provider="" and
    # the picker's set_from_ids fills in metadata on first display.
    voice_id: str = ""
    voice_provider: str = ""
    output_path: str = ""
    resolution: tuple[int, int] = (1920, 1080)

    def to_dict(self) -> dict:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "voice_id": self.voice_id,
            "voice_provider": self.voice_provider,
            "output_path": self.output_path,
            "resolution": list(self.resolution),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComposerProject":
        return cls(
            segments=[MediaSegment.from_dict(s) for s in d.get("segments", [])],
            voice_id=d.get("voice_id", ""),
            voice_provider=d.get("voice_provider", ""),
            output_path=d.get("output_path", ""),
            resolution=tuple(d.get("resolution", [1920, 1080])),
        )

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "ComposerProject":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
