"""Subtitle analysis artifacts — project-anchored AI products of a subtitle.

A "subtitle analysis" is a structured output derived from one
`subtitles/<iso>.srt` by running an AI prompt on its content. Each
analysis is independent, reusable across derivatives, and viewable
in the preview tab.

Six analysis types are registered (see ANALYSIS_TYPES). Files land
flat under `subtitles/` with `<iso>.<suffix>` naming so they sort
together with the source SRT.

This module is the schema layer only: it defines the registry,
path conventions, and a scanner for existing artifacts. Generation
runners live in subtitle_analysis_runners.py (P2+).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


# Analysis kinds.
AnalysisKind = Literal[
    "analysis",
    "transcript",
    "chapter_transcript",
    "hotclips",
    "dub",
]


@dataclass(frozen=True)
class AnalysisType:
    """Static metadata for one analysis kind."""
    kind: AnalysisKind
    suffix: str          # e.g. "titles.json"; appended after "<iso>."
    format: str          # "json" | "md"
    icon: str            # single emoji for sidebar row
    display_zh: str
    display_en: str


# Registry. Order is the order shown in the sidebar [+] menu.
# `analysis` is the unified AI subtitle pack (titles + chapters with
# refined + key_points). The legacy 3-file split (titles / chapters /
# chapter_refined) was retired — they always came from one AI call and
# carrying them as 3 sidebar rows + 3 files just spread the data thin.
ANALYSIS_TYPES: tuple[AnalysisType, ...] = (
    AnalysisType("analysis",           "analysis.json",           "json", "📑", "标题与章节",   "Titles & Chapters"),
    AnalysisType("transcript",         "transcript.md",           "md",   "📄", "全文文字稿",   "Transcript"),
    AnalysisType("chapter_transcript", "chapter_transcript.md",   "md",   "📜", "分章节全文",   "Chapter Transcript"),
    AnalysisType("hotclips",           "hotclips.json",           "json", "🔥", "热点片段",     "Hot Clips"),
    # Dubbing: the manifest (<iso>.dub.json) is the registry artifact; it points
    # at the sibling audio file (<iso>.dub.mp3). Synthesized via capability.tts_dub
    # (not the generic analyze runner), so it's not part of the generatable menu.
    AnalysisType("dub",                "dub.json",                "json", "🎙️", "配音音频",     "Dubbing"),
)


_BY_KIND: dict[str, AnalysisType] = {t.kind: t for t in ANALYSIS_TYPES}


def get_type(kind: str) -> AnalysisType | None:
    """Look up an analysis type by its `kind` string. None if unknown."""
    return _BY_KIND.get(kind)


def all_types() -> tuple[AnalysisType, ...]:
    return ANALYSIS_TYPES


def analysis_path(subtitles_dir: str, lang_iso: str, kind: str) -> str:
    """Canonical path for an analysis artifact.

    Format: `<subtitles_dir>/<iso>.<suffix>` (flat layout so files
    sort together with the source SRT). Raises ValueError on unknown kind.
    """
    t = get_type(kind)
    if t is None:
        raise ValueError(f"Unknown analysis kind: {kind}")
    return os.path.join(subtitles_dir, f"{lang_iso}.{t.suffix}")


@dataclass
class AnalysisArtifact:
    """One concrete artifact on disk."""
    type: AnalysisType
    lang_iso: str
    path: str            # absolute
    exists: bool
    size_bytes: int      # 0 if missing
    mtime: float         # 0.0 if missing


def scan_artifacts(subtitles_dir: str, lang_iso: str) -> list[AnalysisArtifact]:
    """Return all analysis artifacts for one language, in registry order.

    Missing artifacts are still returned with `exists=False` so callers
    can render placeholders or "generate" affordances uniformly.
    """
    out: list[AnalysisArtifact] = []
    for t in ANALYSIS_TYPES:
        p = analysis_path(subtitles_dir, lang_iso, t.kind)
        try:
            st = os.stat(p)
            out.append(AnalysisArtifact(
                type=t, lang_iso=lang_iso, path=p,
                exists=True, size_bytes=st.st_size, mtime=st.st_mtime,
            ))
        except FileNotFoundError:
            out.append(AnalysisArtifact(
                type=t, lang_iso=lang_iso, path=p,
                exists=False, size_bytes=0, mtime=0.0,
            ))
    return out


def existing_artifacts(subtitles_dir: str, lang_iso: str) -> list[AnalysisArtifact]:
    """Same as scan_artifacts but filters to ones that exist on disk."""
    return [a for a in scan_artifacts(subtitles_dir, lang_iso) if a.exists]
