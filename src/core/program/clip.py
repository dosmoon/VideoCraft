"""Clip Script — long video → N short vertical clips.

Phase A (walking skeleton, no AI): consume `subtitle.pack` postprocess.json,
let user manually pick chapter ranges, manually frame crop on a still
keyframe, and export 1080x1920 mp4 clips with burned subtitles + hook/outro
overlays.

Phase B will add AI: rank_chapters / find_peaks / package_clip layered on
top of the same data model. See docs/draft/program-script-clip.md.

Architecture: this is the *feature* layer (per principle 1). UI imports
this module; this module owns ffmpeg invocation and pack parsing. AI
calls (Phase B) will route through `core.ai.complete_json`.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Callable

import srt as _srt

from core.segment_model import format_timestamp, parse_timestamp, safe_filename
from core.subtitle_ops import (
    LAYOUT_DEFAULTS, escape_ffmpeg_path, hex_color_to_ass, read_srt,
    process_srt_split,
)


ProgressCallback = Callable[[str, int], None]   # (status, percent 0-100)


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class ClipDraft:
    """One short video being assembled. Pre-export fields filled by UI;
    crop_rect / output_path filled by export step."""
    id: int
    chapter_idx: int
    chapter_title: str
    start_sec: float
    end_sec: float
    original_excerpt: str = ""
    hook: str = ""
    outro: str = ""
    title: str = ""
    hashtags: list[str] = field(default_factory=list)
    crop_rect: dict | None = None       # {x, y, w, h} normalized 0..1
    status: str = "draft"               # draft / reviewed / exported / skipped
    output_path: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


# ── Pack ingestion ──────────────────────────────────────────────────────────

def load_pack(postprocess_json_path: str) -> dict:
    """Read a subtitle.pack postprocess.json into memory."""
    with open(postprocess_json_path, "r", encoding="utf-8") as f:
        pack = json.load(f)
    if not isinstance(pack, dict):
        raise ValueError(f"Pack file is not a JSON object: {postprocess_json_path}")
    if not pack.get("segments"):
        raise ValueError(f"Pack file has no 'segments': {postprocess_json_path}")
    return pack


def list_chapters(pack: dict, video_duration: float | None = None) -> list[dict]:
    """Convert pack's segments[] into chapter dicts with start_sec/end_sec.

    end_sec is derived: next chapter's start, or video_duration for the last.
    If video_duration is None, the last chapter's end_sec is left as
    start_sec + 600 (10min) as a coarse fallback — caller should pass a real
    duration via probe_duration() when available.
    """
    raw = pack.get("segments") or []
    chapters: list[dict] = []
    for idx, seg in enumerate(raw):
        time_str = (seg.get("time_str") or "").strip()
        start_sec = parse_timestamp(time_str)
        if start_sec is None:
            continue
        chapters.append({
            "idx": idx,
            "title": (seg.get("title") or "").strip(),
            "refined": (seg.get("refined") or "").strip(),
            "time_str": time_str,
            "start_sec": float(start_sec),
            "end_sec": 0.0,    # filled below
        })
    fallback_end = video_duration if video_duration else 0.0
    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            ch["end_sec"] = chapters[i + 1]["start_sec"]
        elif fallback_end and fallback_end > ch["start_sec"]:
            ch["end_sec"] = float(fallback_end)
        else:
            ch["end_sec"] = ch["start_sec"] + 600.0
    return chapters


def chapter_paragraphs(paragraphs_txt_path: str, chapter_idx: int,
                       chapters: list[dict]) -> str:
    """Extract the raw SRT slice block for one chapter from paragraphs.txt.

    paragraphs.txt format (from write_subtitle_pack):
      "<HH:MM:SS> <title>\n<raw SRT slice>\n\n" blocks.
    We split on blank lines and pick the block whose header matches the
    chapter's time_str + title. Returns empty string if not found.
    """
    if not os.path.exists(paragraphs_txt_path):
        return ""
    if chapter_idx < 0 or chapter_idx >= len(chapters):
        return ""
    target = chapters[chapter_idx]
    target_header_prefix = f"{target['time_str']} {target['title']}".strip()

    with open(paragraphs_txt_path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\s*\n", content)
    for block in blocks:
        first_line = block.splitlines()[0] if block.strip() else ""
        if first_line.strip() == target_header_prefix:
            # body = everything after the first line
            return "\n".join(block.splitlines()[1:]).strip()
    return ""


# ── SRT slicing ─────────────────────────────────────────────────────────────

def load_cues(srt_path: str) -> list[_srt.Subtitle]:
    """Parse an SRT file into a list of Subtitle cues."""
    return list(_srt.parse(read_srt(srt_path)))


def snap_to_cue_boundaries(cues: list[_srt.Subtitle],
                           start_sec: float, end_sec: float
                           ) -> tuple[float, float]:
    """Round (start, end) to the nearest enclosing cue boundaries.

    start → previous cue start ≤ start_sec; end → next cue end ≥ end_sec.
    If no cue brackets the range, returns the input unchanged.
    """
    if not cues:
        return (start_sec, end_sec)
    snapped_start = start_sec
    snapped_end = end_sec
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if cs <= start_sec:
            snapped_start = cs
        if ce >= end_sec and snapped_end == end_sec:
            snapped_end = ce
            break
    return (snapped_start, snapped_end)


def slice_srt_for_clip(cues: list[_srt.Subtitle],
                       start_sec: float, end_sec: float,
                       out_path: str) -> str:
    """Write a sub-SRT for the [start_sec, end_sec] window with timestamps
    rebased to start at 0. Returns out_path."""
    sliced: list[_srt.Subtitle] = []
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if ce <= start_sec or cs >= end_sec:
            continue
        new_start = max(0.0, cs - start_sec)
        new_end = min(end_sec - start_sec, ce - start_sec)
        if new_end <= new_start:
            continue
        sliced.append(_srt.Subtitle(
            index=len(sliced) + 1,
            start=timedelta(seconds=new_start),
            end=timedelta(seconds=new_end),
            content=cue.content,
        ))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_srt.compose(sliced) if sliced else "")
    return out_path


# ── Probing ─────────────────────────────────────────────────────────────────

def probe_duration(video_path: str) -> float:
    """Return video duration in seconds, 0.0 if probe fails."""
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries",
               "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
               video_path]
        out = subprocess.run(cmd, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=15)
        return float(out.stdout.strip()) if out.returncode == 0 else 0.0
    except Exception:
        return 0.0


def probe_resolution(video_path: str) -> tuple[int, int]:
    """Return (width, height) or (0, 0) if probe fails."""
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "csv=p=0",
               video_path]
        out = subprocess.run(cmd, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=15)
        if out.returncode != 0:
            return (0, 0)
        w, h = out.stdout.strip().split(",")
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def extract_keyframe(video_path: str, at_sec: float, out_path: str) -> str:
    """Extract a single JPEG keyframe at `at_sec`. Used by the crop UI to
    show a still frame to draw the rectangle on (Windows VLC HWND can't
    accept tk overlays, so crop is done on a thumbnail)."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-ss", f"{max(0.0, at_sec):.3f}",
           "-i", video_path, "-vframes", "1",
           "-q:v", "2", out_path]
    proc = subprocess.run(cmd, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=30)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg keyframe extract failed: {proc.stderr[-400:]}")
    return out_path


# ── Crop helpers ────────────────────────────────────────────────────────────

def center_crop_rect(video_w: int, video_h: int) -> dict:
    """Default 9:16 center crop rect for a given video resolution.
    Returns normalized {x, y, w, h} 0..1."""
    if video_w <= 0 or video_h <= 0:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    target_ar = 9.0 / 16.0           # width / height
    cur_ar = video_w / video_h
    if cur_ar > target_ar:
        # Source is wider than 9:16 → take vertical strip in middle
        new_w = video_h * target_ar
        x = (video_w - new_w) / 2.0
        return {"x": x / video_w, "y": 0.0,
                "w": new_w / video_w, "h": 1.0}
    # Source is taller (or equal) → take horizontal strip in middle
    new_h = video_w / target_ar
    y = (video_h - new_h) / 2.0
    return {"x": 0.0, "y": y / video_h,
            "w": 1.0, "h": new_h / video_h}


def crop_rect_to_pixels(rect: dict, video_w: int, video_h: int
                        ) -> tuple[int, int, int, int]:
    """Convert normalized rect → (cw, ch, cx, cy) integer pixels."""
    cw = max(2, int(round(rect["w"] * video_w)))
    ch = max(2, int(round(rect["h"] * video_h)))
    cx = max(0, int(round(rect["x"] * video_w)))
    cy = max(0, int(round(rect["y"] * video_h)))
    # Ensure even dimensions for libx264
    cw -= cw % 2
    ch -= ch % 2
    return (cw, ch, cx, cy)


# ── Clips JSON persistence ──────────────────────────────────────────────────

CLIPS_JSON_VERSION = 1
CUT_FILE_VERSION = 2


def _hydrate_clip(c: dict) -> ClipDraft:
    return ClipDraft(
        id=c.get("id", 0),
        chapter_idx=c.get("chapter_idx", -1),
        chapter_title=c.get("chapter_title", ""),
        start_sec=float(c.get("start_sec", 0.0)),
        end_sec=float(c.get("end_sec", 0.0)),
        original_excerpt=c.get("original_excerpt", ""),
        hook=c.get("hook", ""),
        outro=c.get("outro", ""),
        title=c.get("title", ""),
        hashtags=list(c.get("hashtags") or []),
        crop_rect=c.get("crop_rect"),
        status=c.get("status", "draft"),
        output_path=c.get("output_path", ""),
    )


def write_cut_file(path: str, *, name: str, sources: dict,
                    clips: list[ClipDraft], output_dir: str = "") -> str:
    """Persist a self-contained clip-script project file.

    The cut file is the unit of persistence — a user-named .json that holds
    everything needed to reopen this edit later: source paths, the output
    directory preference, and the full clip list.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    payload = {
        "version": CUT_FILE_VERSION,
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "pack_path":  sources.get("pack_path", ""),
            "video_path": sources.get("video_path", ""),
            "srt_path":   sources.get("srt_path", ""),
        },
        "output_dir": output_dir or "",
        "clips": [asdict(c) for c in clips],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_cut_file(path: str) -> dict:
    """Read a cut file. Returns dict with keys:
    name / sources / output_dir / clips (list[ClipDraft])."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {
        "name": payload.get("name", os.path.splitext(os.path.basename(path))[0]),
        "sources": payload.get("sources") or {},
        "output_dir": payload.get("output_dir", ""),
        "clips": [_hydrate_clip(c) for c in (payload.get("clips") or [])],
    }


# Backward-compat aliases for the old write/read API. Older clips.json files
# (version 1) are still readable; new code writes v2 cut files exclusively.

def write_clips_json(clips: list[ClipDraft], video_path: str,
                     basename: str, out_dir: str) -> str:
    """Legacy: emit the v1 -clips.json layout. Kept for back-compat with
    callers that haven't migrated to the cut-file model."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{basename}-clips.json")
    payload = {
        "version": CLIPS_JSON_VERSION,
        "source_basename": basename,
        "source_video": os.path.abspath(video_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "clips": [asdict(c) for c in clips],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def load_clips_json(path: str) -> list[ClipDraft]:
    """Legacy v1 reader. New code should use load_cut_file()."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return [_hydrate_clip(c) for c in (payload.get("clips") or [])]


# ── Export pipeline ─────────────────────────────────────────────────────────

# Drawtext escapes: ffmpeg drawtext text= needs special chars escaped.
# Single quotes can't appear in text='...' literally; use \\\\: for : and
# \\\\\\' for '. We keep the rules narrow because hooks are short user text.
def _escape_drawtext(text: str) -> str:
    if not text:
        return ""
    out = (
        text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "’")    # convert straight quote to curly to avoid escaping hell
            .replace("%", "\\%")
    )
    return out


def _drawtext_filter(text: str, *, position: str, font_size: int,
                     duration: float, hook_secs: float = 5.0,
                     font_color: str = "white",
                     border_color: str = "black") -> str:
    """Build a drawtext filter for hook (top, first N seconds) or outro
    (bottom, last N seconds). `position` ∈ {'hook', 'outro'}."""
    txt = _escape_drawtext(text)
    if not txt:
        return ""
    if position == "hook":
        y = "h*0.08"
        enable = f"between(t,0,{hook_secs})"
    else:
        y = "h*0.78"
        start = max(0.0, duration - hook_secs)
        enable = f"between(t,{start},{duration})"
    # Microsoft YaHei is also used by burn_subs.py; consistent across platform.
    return (f"drawtext=text='{txt}':fontfile='C\\:/Windows/Fonts/msyh.ttc':"
            f"fontcolor={font_color}:fontsize={font_size}:"
            f"x=(w-text_w)/2:y={y}:"
            f"borderw=3:bordercolor={border_color}:"
            f"box=1:boxcolor=black@0.4:boxborderw=10:"
            f"enable='{enable}'")


def export_clip(
    video_path: str,
    clip: ClipDraft,
    out_dir: str,
    *,
    source_srt: str | None = None,
    target_w: int = 1080,
    target_h: int = 1920,
    encode_preset: str = "veryfast",
    crf: int = 23,
    on_progress: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Render one clip to mp4: trim → crop → scale → burn subtitle → hook/outro.

    Single ffmpeg invocation via filter_complex. Returns the output path.
    Raises RuntimeError on ffmpeg failure.
    """
    src_w, src_h = probe_resolution(video_path)
    if src_w == 0 or src_h == 0:
        raise RuntimeError(f"Cannot probe video resolution: {video_path}")

    # Crop rect → pixels (default to center crop if not set)
    rect = clip.crop_rect or center_crop_rect(src_w, src_h)
    cw, ch, cx, cy = crop_rect_to_pixels(rect, src_w, src_h)

    duration = clip.duration
    if duration <= 0:
        raise ValueError(f"Clip {clip.id} has non-positive duration")

    os.makedirs(out_dir, exist_ok=True)
    title_slug = safe_filename(clip.title or clip.chapter_title or f"clip-{clip.id}")[:40]
    out_name = f"clip-{clip.id:02d}-{title_slug}.mp4"
    out_path = os.path.join(out_dir, out_name)

    # Build temp clipped SRT (rebased to 0) if source SRT provided.
    tmp_srt_path: str | None = None
    if source_srt and os.path.exists(source_srt):
        try:
            cues = load_cues(source_srt)
            # Pre-split for vertical width to avoid overflow.
            tmp_srt_path = os.path.join(
                tempfile.gettempdir(),
                f"clip-{clip.id}-{int(clip.start_sec)}.srt"
            )
            slice_srt_for_clip(cues, clip.start_sec, clip.end_sec, tmp_srt_path)
            # Re-split each cue line for vertical layout (max ~10 zh chars)
            try:
                vlayout = LAYOUT_DEFAULTS["vertical"]
                split_subs = process_srt_split(
                    tmp_srt_path,
                    vlayout["max_chars_zh"],
                    is_chinese=True,
                )
                with open(tmp_srt_path, "w", encoding="utf-8") as f:
                    f.write(_srt.compose(split_subs))
            except Exception:
                pass    # leave un-split on failure; better than no subs
        except Exception:
            tmp_srt_path = None

    # Build filter_complex
    parts: list[str] = []
    cur = "[0:v]"
    parts.append(f"{cur}crop={cw}:{ch}:{cx}:{cy},"
                 f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                 f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                 f"setsar=1[v0]")
    cur = "[v0]"

    if tmp_srt_path and os.path.exists(tmp_srt_path) and os.path.getsize(tmp_srt_path) > 0:
        srt_ff = escape_ffmpeg_path(tmp_srt_path)
        vlayout = LAYOUT_DEFAULTS["vertical"]
        style = (f"Fontname=Microsoft YaHei,"
                 f"Fontsize={vlayout['fontsize']},"
                 f"PrimaryColour={hex_color_to_ass('#FFFFFF')},"
                 f"OutlineColour=&H00000000&,"
                 f"BorderStyle=1,Outline=2,Shadow=0,"
                 f"Bold=1,Alignment=2,MarginV={vlayout['margin_v']}")
        parts.append(f"{cur}subtitles=filename='{srt_ff}':"
                     f"force_style='{style}'[v1]")
        cur = "[v1]"

    # Hook + outro overlays
    overlay_filters: list[str] = []
    if clip.hook:
        overlay_filters.append(_drawtext_filter(
            clip.hook, position="hook", font_size=46, duration=duration))
    if clip.outro:
        overlay_filters.append(_drawtext_filter(
            clip.outro, position="outro", font_size=42, duration=duration))
    if overlay_filters:
        parts.append(f"{cur}{','.join(overlay_filters)}[vout]")
    else:
        parts.append(f"{cur}null[vout]")

    filter_complex = ";".join(parts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{clip.start_sec:.3f}",
        "-to", f"{clip.end_sec:.3f}",
        "-i", os.path.abspath(video_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", encode_preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        os.path.abspath(out_path),
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    tail: list[str] = []
    last_pct = -1
    assert proc.stderr is not None
    try:
        for line in proc.stderr:
            tail.append(line)
            if len(tail) > 60:
                tail.pop(0)
            if cancel_check and cancel_check():
                proc.terminate()
                raise InterruptedError("Export cancelled")
            m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
            if m and duration > 0:
                cur_sec = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                           + float(m.group(3)))
                pct = max(0, min(100, int(cur_sec / duration * 100)))
                if pct != last_pct:
                    last_pct = pct
                    if on_progress:
                        on_progress("encoding", pct)
        proc.wait()
    finally:
        if tmp_srt_path and os.path.exists(tmp_srt_path):
            try:
                os.unlink(tmp_srt_path)
            except OSError:
                pass

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg export failed ({proc.returncode}): "
            f"{''.join(tail)[-800:]}"
        )

    clip.output_path = out_path
    clip.status = "exported"
    return out_path


# ── Convenience: bulk export ────────────────────────────────────────────────

def export_all(
    video_path: str,
    clips: list[ClipDraft],
    out_dir: str,
    *,
    source_srt: str | None = None,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Export each clip in order. on_progress(i, total, status, percent).
    Skips clips whose status == 'skipped'. Stops on cancel."""
    todo = [c for c in clips if c.status != "skipped"]
    total = len(todo)
    out_paths: list[str] = []
    for i, clip in enumerate(todo, 1):
        if cancel_check and cancel_check():
            break
        def _step_progress(status: str, pct: int, _i=i):
            if on_progress:
                on_progress(_i, total, status, pct)
        out_paths.append(export_clip(
            video_path, clip, out_dir,
            source_srt=source_srt,
            on_progress=_step_progress,
            cancel_check=cancel_check,
        ))
    return out_paths


# ── AI (Phase B) ────────────────────────────────────────────────────────────

# JSON schemas for the three AI calls. Each is a strict structured output
# that the prompt instructs the model to emit verbatim.

_RANK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["idx", "score", "reason"],
            },
        }
    },
    "required": ["ranked"],
}

_PEAKS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "peaks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_sec": {"type": "number"},
                    "end_sec":   {"type": "number"},
                    "score":     {"type": "integer"},
                    "reason":    {"type": "string"},
                },
                "required": ["start_sec", "end_sec", "score", "reason"],
            },
        }
    },
    "required": ["peaks"],
}

_PACKAGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "hook":     {"type": "string"},
        "outro":    {"type": "string"},
        "title":    {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "outro", "title", "hashtags"],
}


def _ai_call_json(prompt: str, *, schema: dict, task: str,
                   tier: str = None, cancel_token=None) -> dict:
    """Wrap ai.complete_json with the standard AIError unwrap pattern
    (mirror core/translate.py and core/srt_ops.py)."""
    from core import ai
    from core.ai.tiers import TIER_STANDARD, TIER_PREMIUM
    from core.ai.errors import AIError as _AIError

    _tier = tier or TIER_STANDARD
    try:
        return ai.complete_json(prompt, schema=schema, task=task,
                                 tier=_tier, cancel_token=cancel_token)
    except Exception as e:
        if isinstance(e, _AIError):
            raise
        raise RuntimeError(f"AI call failed (task={task}, tier={_tier}): {e}")


def rank_chapters(pack: dict, *, cancel_token=None) -> list[dict]:
    """Score every chapter for highlight potential. Returns a list of
    dicts {idx, score, reason} sorted descending by score.

    Idempotent — does not mutate pack. The full chapter set is always
    returned (model is instructed to score every input idx); if the model
    misses some, those get score=0, reason='' as a safe fallback.
    """
    from core import prompts as _prompts
    from core.ai.tiers import TIER_STANDARD

    raw = pack.get("segments") or []
    chapter_list = []
    for idx, seg in enumerate(raw):
        chapter_list.append({
            "idx": idx,
            "title": (seg.get("title") or "").strip(),
            "refined": (seg.get("refined") or "").strip(),
        })
    if not chapter_list:
        return []

    template = _prompts.get("clip.rank-chapters")
    prompt = template.replace("{chapter_list}",
                               json.dumps(chapter_list, ensure_ascii=False, indent=2))
    result = _ai_call_json(prompt, schema=_RANK_SCHEMA,
                            task="clip.rank", tier=TIER_STANDARD,
                            cancel_token=cancel_token)
    ranked_raw = result.get("ranked") or []
    by_idx: dict[int, dict] = {
        int(r["idx"]): {
            "idx": int(r["idx"]),
            "score": max(0, min(100, int(r.get("score", 0)))),
            "reason": str(r.get("reason", "")).strip(),
        }
        for r in ranked_raw if isinstance(r, dict) and "idx" in r
    }
    out: list[dict] = []
    for ch in chapter_list:
        out.append(by_idx.get(ch["idx"],
                               {"idx": ch["idx"], "score": 0, "reason": ""}))
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def find_peaks(pack: dict, chapter_idx: int, paragraphs_txt_path: str,
                video_duration: float | None = None, *,
                cancel_token=None) -> list[dict]:
    """Find 1-3 highlight clip ranges within one chapter. Returns
    [{start_sec, end_sec, score, reason}] with bounds clamped to the
    chapter and snapped to nearest cue boundaries (caller-owned cue list
    not required — this function does its own clamp; snapping happens
    at the workbench layer where SRT cues are loaded).

    Length policy: 30 ≤ duration ≤ 90 enforced post-AI. Out-of-range
    peaks are dropped silently."""
    from core import prompts as _prompts
    from core.ai.tiers import TIER_STANDARD

    chapters = list_chapters(pack, video_duration)
    if not (0 <= chapter_idx < len(chapters)):
        return []
    ch = chapters[chapter_idx]

    paragraphs = chapter_paragraphs(paragraphs_txt_path, chapter_idx, chapters)
    if not paragraphs:
        return []

    template = _prompts.get("clip.find-peaks")
    prompt = (template
              .replace("{chapter_title}", ch["title"])
              .replace("{chapter_refined}", ch["refined"] or "")
              .replace("{chapter_start_sec}", f"{ch['start_sec']:.1f}")
              .replace("{chapter_end_sec}",   f"{ch['end_sec']:.1f}")
              .replace("{chapter_paragraphs}", paragraphs))
    result = _ai_call_json(prompt, schema=_PEAKS_SCHEMA,
                            task="clip.peak", tier=TIER_STANDARD,
                            cancel_token=cancel_token)

    peaks_raw = result.get("peaks") or []
    out: list[dict] = []
    for p in peaks_raw:
        if not isinstance(p, dict):
            continue
        try:
            s = float(p["start_sec"])
            e = float(p["end_sec"])
        except (KeyError, ValueError, TypeError):
            continue
        # Clamp to chapter bounds
        s = max(s, ch["start_sec"])
        e = min(e, ch["end_sec"])
        if e - s < 30 or e - s > 90:
            continue
        out.append({
            "start_sec": s,
            "end_sec": e,
            "score": max(0, min(100, int(p.get("score", 0)))),
            "reason": str(p.get("reason", "")).strip(),
        })
    return out


def package_clip(clip: ClipDraft, pack: dict, *,
                  cancel_token=None) -> dict:
    """Generate hook / outro / title / hashtags for one clip.
    Returns {hook, outro, title, hashtags}."""
    from core import prompts as _prompts
    from core.ai.tiers import TIER_PREMIUM

    chapters_meta = list_chapters(pack)
    ch_meta = (chapters_meta[clip.chapter_idx]
               if 0 <= clip.chapter_idx < len(chapters_meta)
               else {"title": clip.chapter_title, "refined": ""})

    template = _prompts.get("clip.package")
    prompt = (template
              .replace("{chapter_title}", ch_meta.get("title", ""))
              .replace("{chapter_refined}", ch_meta.get("refined", ""))
              .replace("{clip_excerpt}", clip.original_excerpt or ""))
    result = _ai_call_json(prompt, schema=_PACKAGE_SCHEMA,
                            task="clip.package", tier=TIER_PREMIUM,
                            cancel_token=cancel_token)
    return {
        "hook":     str(result.get("hook", "")).strip(),
        "outro":    str(result.get("outro", "")).strip(),
        "title":    str(result.get("title", "")).strip(),
        "hashtags": [str(t).strip() for t in (result.get("hashtags") or [])
                      if str(t).strip()],
    }


__all__ = [
    "ClipDraft",
    "load_pack",
    "list_chapters",
    "chapter_paragraphs",
    "load_cues",
    "snap_to_cue_boundaries",
    "slice_srt_for_clip",
    "probe_duration",
    "probe_resolution",
    "extract_keyframe",
    "center_crop_rect",
    "crop_rect_to_pixels",
    "write_cut_file",
    "load_cut_file",
    "write_clips_json",
    "load_clips_json",
    "export_clip",
    "export_all",
    "rank_chapters",
    "find_peaks",
    "package_clip",
]
