"""News-video material instance model — single source of truth.

Per ADR-0005, every material instance has a model object that owns:
- On-disk paths for this instance (delegate to paths.py)
- Schema read/write (basic_info, context, subtitles, analysis)
- Slot readiness state (gated/empty/filled per dependency rules)
- Business actions (add source, generate subtitles, AI fill, run analysis)
- Subscribers for change notifications

The model is zero-Tk. UI views (sidebar.py, dialogs) call methods here
to read state, and pass concrete user input back to model methods to
mutate state. Long-running operations (ASR, translate, AI fill,
analysis) accept progress_cb + cancel_token — UI wraps these in modals.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from materials.news_video import paths as _paths
from materials.news_video.schema import (
    SourceBasicInfo, SourceContext,
    basic_info_path, context_path,
    read_basic_info, write_basic_info,
    read_context, write_context,
)


# ── Slot state ───────────────────────────────────────────────────────────────

# Slot identifiers — stable strings the sidebar uses to reference slots.
SLOT_SOURCE = "source"
SLOT_NEWS_CONTEXT = "news_context"
SLOT_SUBTITLES = "subtitles"

ALL_SLOTS = (SLOT_SOURCE, SLOT_NEWS_CONTEXT, SLOT_SUBTITLES)


@dataclass(frozen=True)
class SlotState:
    """One slot's render-ready state. Sidebar consumes this dict-of-states
    instead of doing its own readiness logic."""
    slot_id: str
    is_locked: bool          # dependency not met (e.g. context locked w/o source)
    is_filled: bool          # has data on disk
    summary: str = ""        # human-readable status text (e.g. "✓ video.mp4 · 3:45 · 1920x1080")


# ── Model ────────────────────────────────────────────────────────────────────

class NewsVideoModel:
    """One news_video instance. Wrap-and-call surface for sidebar/UI."""

    def __init__(self, project, instance_id: str | None = None):
        self.project = project
        # Caller may omit instance_id for ergonomic transitional callsites;
        # we resolve via paths.default_instance which prefers an existing
        # instance over the "default" fallback.
        self.instance_id = instance_id or _paths.default_instance(project)
        self._subscribers: list[Callable[[], None]] = []

    # ── Identity / paths ──────────────────────────────────────────────────

    @property
    def instance_dir(self) -> str:
        return _paths.instance_dir(self.project, self.instance_id)

    @property
    def source_dir(self) -> str:
        return _paths.source_dir(self.project, self.instance_id)

    @property
    def subtitles_dir(self) -> str:
        return _paths.subtitles_dir(self.project, self.instance_id)

    @property
    def source_video_path(self) -> str:
        return _paths.source_video_path(self.project, self.instance_id)

    @property
    def source_meta_path(self) -> str:
        return _paths.source_meta_path(self.project, self.instance_id)

    # ── Source video slot ─────────────────────────────────────────────────

    def has_source_video(self) -> bool:
        return _paths.source_status(self.project, self.instance_id) == "ready"

    def get_source_meta(self):
        """The Source descriptor stored in project meta (origin/url/title/...).
        Returns the Source dataclass even when has_source_video() is False —
        meta survives independent of the file's presence."""
        return self.project.meta.source

    def commit_source(self, src, *, title: str | None = None,
                       duration_sec: float | None = None,
                       width: int | None = None,
                       height: int | None = None) -> None:
        """Persist a Source descriptor + post-acquisition probe values.

        Caller is responsible for the actual file acquisition (download
        / copy via SourcePrepareModal); this just stamps metadata once
        the file landed at source_video_path."""
        meta = self.project.meta
        meta.source = src
        if title:
            meta.source.title = title
        if duration_sec is not None:
            meta.source.duration_sec = duration_sec
        if width is not None:
            meta.source.width = width
        if height is not None:
            meta.source.height = height
        self.project.update_meta(meta)
        self._notify()

    # ── News context slot (basic_info + context) ──────────────────────────

    def read_basic_info(self) -> SourceBasicInfo:
        return read_basic_info(self.source_dir)

    def write_basic_info(self, info: SourceBasicInfo) -> None:
        write_basic_info(self.source_dir, info)
        self._notify()

    def read_context(self) -> SourceContext:
        return read_context(self.source_dir)

    def write_context(self, ctx: SourceContext) -> None:
        write_context(self.source_dir, ctx)
        self._notify()

    def context_completion(self) -> tuple[int, int]:
        """(filled, total) — drives the sidebar status badge."""
        ctx = self.read_context().to_dict()
        total = len(SourceContext.__dataclass_fields__)
        filled = sum(1 for v in ctx.values() if isinstance(v, str) and v.strip())
        return filled, total

    def ai_fill_context(self, *, progress_cb=None, cancel_token=None) -> SourceContext:
        """Run AI extraction to populate context.json. Returns the new
        SourceContext. Caller wraps in progress modal."""
        from materials.news_video.ai_fill import extract
        ctx = extract(self.source_dir,
                      progress_cb=progress_cb, cancel_token=cancel_token)
        write_context(self.source_dir, ctx)
        self._notify()
        return ctx

    # ── Subtitles slot ────────────────────────────────────────────────────

    def list_subtitle_languages(self) -> list[str]:
        """Returns sorted language codes for which <lang>.srt exists."""
        if not os.path.isdir(self.subtitles_dir):
            return []
        out: list[str] = []
        try:
            for name in os.listdir(self.subtitles_dir):
                if not name.lower().endswith(".srt"):
                    continue
                stem = name[:-4]
                if 1 < len(stem) <= 8 and all(c.isalpha() or c == "-" for c in stem):
                    out.append(stem)
        except OSError:
            pass
        return sorted(out)

    def subtitle_path(self, lang_iso: str) -> str:
        return os.path.join(self.subtitles_dir, f"{lang_iso}.srt")

    def has_subtitle(self, lang_iso: str) -> bool:
        return os.path.isfile(self.subtitle_path(lang_iso))

    def source_language(self) -> Optional[str]:
        return self.project.meta.language.source

    def translated_languages(self) -> list[str]:
        return list(self.project.meta.language.translated_to)

    def run_asr(self, *, source_lang_iso: str | None,
                 progress_cb, cancel_token):
        """Generate the source SRT via ASR. Returns the pipeline result.
        Caller wraps in progress modal."""
        from core.subtitle_pipeline import run_asr
        result = run_asr(
            self.project,
            source_lang_iso=source_lang_iso,
            progress_cb=progress_cb,
            cancel_token=cancel_token,
        )
        self._notify()
        return result

    def run_translate(self, *, target_lang_iso: str,
                       progress_cb, cancel_token):
        """Translate from the project's source language to target_lang_iso."""
        from core.subtitle_pipeline import run_translate
        result = run_translate(
            self.project,
            target_lang_iso=target_lang_iso,
            progress_cb=progress_cb,
            cancel_token=cancel_token,
        )
        self._notify()
        return result

    def import_subtitle(self, src_path: str, lang_iso: str) -> None:
        """Copy an external SRT into subtitles/<lang>.srt. First-imported
        SRT becomes the project's source language."""
        os.makedirs(self.subtitles_dir, exist_ok=True)
        dst = self.subtitle_path(lang_iso)
        shutil.copy2(src_path, dst)
        meta = self.project.meta
        if not meta.language.source:
            meta.language.source = lang_iso
            self.project.update_meta(meta)
        self._notify()

    def quick_fix_subtitle(self, lang_iso: str) -> None:
        """Apply auto-fixes to a subtitle in place."""
        from core.subtitle_check import apply_auto_fixes
        apply_auto_fixes(self.subtitle_path(lang_iso))
        self._notify()

    def check_subtitle(self, lang_iso: str, *, reference_lang_iso: str | None = None):
        """Run the quality check on a subtitle; returns the SubtitleCheck."""
        from core.subtitle_check import check_srt
        ref_path = None
        if reference_lang_iso and reference_lang_iso != lang_iso:
            cand = self.subtitle_path(reference_lang_iso)
            if os.path.isfile(cand):
                ref_path = cand
        return check_srt(
            self.subtitle_path(lang_iso),
            expected_lang_iso=lang_iso,
            reference_srt_path=ref_path,
        )

    # ── Analysis artifacts (per-subtitle) ─────────────────────────────────

    def list_analysis_artifacts(self, lang_iso: str):
        from core.subtitle_analysis import existing_artifacts
        return existing_artifacts(self.subtitles_dir, lang_iso)

    def analysis_path(self, lang_iso: str, kind: str) -> str:
        from core.subtitle_analysis import analysis_path
        return analysis_path(self.subtitles_dir, lang_iso, kind)

    def has_analysis(self, lang_iso: str, kind: str) -> bool:
        return os.path.isfile(self.analysis_path(lang_iso, kind))

    def run_analysis(self, kind: str, lang_iso: str, *,
                      progress_cb, cancel_token):
        from core.subtitle_analysis_runners import run as run_analysis
        srt = self.subtitle_path(lang_iso)
        result = run_analysis(kind, srt, self.subtitles_dir, lang_iso,
                              progress_cb, cancel_token)
        self._notify()
        return result

    # ── Slot readiness (drives sidebar tree rendering) ────────────────────

    def slot_readiness(self) -> dict[str, SlotState]:
        """Returns one SlotState per top-level slot, ready to render."""
        src_ready = self.has_source_video()

        # Source
        if src_ready:
            meta = self.get_source_meta()
            extras = []
            if meta.duration_sec:
                extras.append(_fmt_duration(meta.duration_sec))
            if meta.width and meta.height:
                extras.append(f"{meta.width}x{meta.height}")
            summary = "✓ " + (meta.title or "video.mp4")
            if extras:
                summary += "  ·  " + " · ".join(extras)
            src_state = SlotState(SLOT_SOURCE, is_locked=False,
                                   is_filled=True, summary=summary)
        else:
            src_state = SlotState(SLOT_SOURCE, is_locked=False,
                                   is_filled=False, summary="✗ 无")

        # News context (locked until source ready)
        if not src_ready:
            ctx_state = SlotState(SLOT_NEWS_CONTEXT, is_locked=True,
                                   is_filled=False,
                                   summary="待源视频就绪")
        else:
            filled, total = self.context_completion()
            ctx_state = SlotState(
                SLOT_NEWS_CONTEXT, is_locked=False,
                is_filled=filled > 0,
                summary=(f"已填 {filled}/{total} 字段"
                         if filled else f"未填（共 {total} 字段）"),
            )

        # Subtitles (locked until source ready)
        if not src_ready:
            subs_state = SlotState(SLOT_SUBTITLES, is_locked=True,
                                    is_filled=False,
                                    summary="待源视频就绪")
        else:
            langs = self.list_subtitle_languages()
            if langs:
                subs_state = SlotState(
                    SLOT_SUBTITLES, is_locked=False, is_filled=True,
                    summary=f"✓ {len(langs)} 种语言: " + ", ".join(langs),
                )
            else:
                subs_state = SlotState(SLOT_SUBTITLES, is_locked=False,
                                        is_filled=False, summary="✗ 无")

        return {
            SLOT_SOURCE: src_state,
            SLOT_NEWS_CONTEXT: ctx_state,
            SLOT_SUBTITLES: subs_state,
        }

    # ── Change notification ───────────────────────────────────────────────

    def subscribe(self, callback: Callable[[], None]) -> None:
        """Register a refresh callback. Invoked after every write."""
        self._subscribers.append(callback)

    def _notify(self) -> None:
        for cb in self._subscribers:
            try:
                cb()
            except Exception:
                pass

    # ── Artifact resolver (for creation plugins per ADR-0005) ─────────────

    def get_artifact(self, key: str) -> Optional[Path]:
        """Resolve an artifact key to a file Path; None if absent.

        Key namespace (stable contract — creation plugins depend on these):
          source             → source/video.mp4
          source_meta        → source/meta.json
          basic_info         → source/basic_info.json
          context            → source/context.json
          subtitle:<lang>    → subtitles/<lang>.srt
          analysis:<lang>:<kind>  → subtitles/<lang>.<kind suffix>
        """
        if key == "source":
            return _exists_path(self.source_video_path)
        if key == "source_meta":
            return _exists_path(self.source_meta_path)
        if key == "basic_info":
            return _exists_path(basic_info_path(self.source_dir))
        if key == "context":
            return _exists_path(context_path(self.source_dir))
        if key.startswith("subtitle:"):
            return _exists_path(self.subtitle_path(key[len("subtitle:"):]))
        if key.startswith("analysis:"):
            _, lang, kind = key.split(":", 2)
            try:
                return _exists_path(self.analysis_path(lang, kind))
            except ValueError:
                return None
        return None


# ── Helpers (private) ────────────────────────────────────────────────────────

def _exists_path(p: str) -> Optional[Path]:
    return Path(p) if os.path.isfile(p) else None


def _fmt_duration(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
