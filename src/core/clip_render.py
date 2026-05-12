"""Clip render pipeline — slice the source video into N short clips.

P4b MVP scope: pure video slicing with accurate re-encode (ffmpeg
-ss/-to). No subtitle burn, no style preset, no aspect conversion;
those land in later passes. The point of this layer is to be the
deterministic counterpart of the AI hotclips analyzer — given a set
of (start, end) timestamps, produce N mp4 files on disk.

Subtitle burn / 9:16 conversion / hook + outro cards can be added
later by composing burn_subs.burn_subtitles on top of the sliced
outputs without changing this module's API.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

from core.video_split import SplitMode, split_one


_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$")


def _parse_ts(s: str) -> float:
    """Parse HH:MM:SS or HH:MM:SS.fff or MM:SS into seconds."""
    m = _TS_RE.match((s or "").strip())
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2))
    sec = int(m.group(3))
    frac = m.group(4)
    base = h * 3600 + mn * 60 + sec
    if frac:
        base += int(frac[:3].ljust(3, "0")) / 1000.0
    return base


@dataclass
class ClipPlanItem:
    """One scheduled clip render. Indexes back to the source hotclip."""
    index: int                    # 1-based output index (clip_001.mp4 = 1)
    source_clip_idx: int          # which entry in hotclips.clips this came from
    start_sec: float
    end_sec: float
    output_path: str
    hook: str = ""                # for display / log only


@dataclass
class ClipRenderResult:
    plan: list[ClipPlanItem]
    rendered: list[str]           # paths of successfully rendered files
    errors: list[tuple[int, str]]  # (plan.index, error message)


def build_plan(
    hotclips_data: dict,
    selected_indices: list[int],
    output_dir: str,
) -> list[ClipPlanItem]:
    """Translate hotclips.json + user selection into a render plan.

    `selected_indices` are 0-based indices into hotclips["clips"]; the
    output naming is renumbered 1..N in selection order so files always
    start at clip_001.mp4 regardless of which source clips got picked.
    """
    clips = hotclips_data.get("clips") or []
    plan: list[ClipPlanItem] = []
    out_idx = 1
    for src_idx in selected_indices:
        if not (0 <= src_idx < len(clips)):
            continue
        c = clips[src_idx]
        if not isinstance(c, dict):
            continue
        start = _parse_ts(c.get("start", ""))
        end = _parse_ts(c.get("end", ""))
        if end <= start:
            continue
        out = os.path.join(output_dir, f"clip_{out_idx:03d}.mp4")
        plan.append(ClipPlanItem(
            index=out_idx,
            source_clip_idx=src_idx,
            start_sec=start,
            end_sec=end,
            output_path=out,
            hook=str(c.get("hook", "")),
        ))
        out_idx += 1
    return plan


def render_clips(
    video_path: str,
    plan: list[ClipPlanItem],
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ClipRenderResult:
    """Render every item in the plan via ffmpeg accurate cut.

    progress_cb(done_count, total, current_label) is called between items.
    cancel_check returning True aborts the loop (already-rendered files
    stay on disk; the caller decides whether to delete them).
    """
    os.makedirs(os.path.dirname(plan[0].output_path), exist_ok=True) if plan else None
    rendered: list[str] = []
    errors: list[tuple[int, str]] = []
    total = len(plan)

    for i, item in enumerate(plan, 1):
        if cancel_check and cancel_check():
            break
        label = item.hook or f"#{item.index}"
        if progress_cb:
            progress_cb(i - 1, total, label)
        try:
            duration = max(0.0, item.end_sec - item.start_sec)
            split_one(
                video_path, item.start_sec, duration, item.output_path,
                mode=SplitMode.ACCURATE,
            )
            rendered.append(item.output_path)
        except Exception as e:
            errors.append((item.index, str(e)))
            # Don't abort the whole batch on one failure — the user gets
            # whatever rendered, plus an error report at the end.

    if progress_cb:
        progress_cb(total, total, "done")
    return ClipRenderResult(plan=plan, rendered=rendered, errors=errors)


# ── Instance config helpers ──────────────────────────────────────────────────

def load_instance_config(instance_dir: str) -> dict:
    """Load derivatives/clip/<inst>/config.json; empty dict if missing."""
    path = os.path.join(instance_dir, "config.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_instance_config(instance_dir: str, config: dict) -> None:
    """Write config.json atomically."""
    os.makedirs(instance_dir, exist_ok=True)
    path = os.path.join(instance_dir, "config.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
