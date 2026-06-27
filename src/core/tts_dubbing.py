"""TTS dubbing — synthesize a full-length voiceover track from one subtitle.

Given `subtitles/<iso>.srt` + the source video duration, this produces a single
audio file aligned to the source timeline: each cue is spoken by the chosen TTS
voice, placed at the cue's start time, with silence in the gaps. The output is
exactly as long as the source video so it drops straight onto the original video
as a dubbing audio track.

Timestamp fitting (the "match the timestamps" half of the feature). For each cue:
  1. Synthesize at normal speed, measure the natural duration.
  2. If it already fits the cue's slot (end − start), place it as-is.
  3. If it's too long, speed it up to fit — capped at `max_speed` so it stays
     intelligible. Engines with native rate control (edge_tts) re-synthesize at
     the computed speed (clean prosody, no pitch shift); others fall back to
     ffmpeg `atempo` post-stretch.
  4. If even the cap can't make it fit, place the capped version and let it
     overflow into the gap — never truncate, and the next cue still starts at
     its own timestamp (brief overlaps are summed by the assembler).

Outputs (atomic, under `subtitles/`):
  - `<iso>.dub.mp3`   — the audio track itself.
  - `<iso>.dub.json`  — manifest (registry artifact): provider/voice/policy plus
                        per-cue placement metadata, for reproducibility, the
                        sidebar detail view, and the news_desk audio component.

Plugin-free (ADR-0008): the caller injects resolved paths + the source duration;
this module updates no project meta and knows nothing about news_video.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any, Callable, Optional

import srt

from core import ai, video_ops
from core.ai.cancellation import CancellationToken
from core.subtitle_analysis import analysis_path
from core.subtitle_ops import read_srt
from core.subtitle_pipeline import ProgressInfo

# Providers with native per-call rate control. Everything else time-stretches
# the normal-speed render with ffmpeg atempo instead.
_ENGINE_SPEED_PROVIDERS = {"edge_tts"}

DEFAULT_MAX_SPEED = 1.5
# Slot-fit slack (seconds): renders within this of their slot count as fitting.
_FIT_EPS = 0.05

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

ProgressCb = Optional[Callable[[ProgressInfo], None]]


def _emit(cb: ProgressCb, info: ProgressInfo) -> None:
    if cb:
        cb(info)


def _spoken_text(content: str) -> str:
    """Flatten an SRT cue body to a single TTS-ready line (drop tags/newlines)."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", content or "")).strip()


def compute_speed(natural: float, slot: float, max_speed: float) -> float:
    """Speed factor to fit `natural` seconds of speech into a `slot`-second cue,
    capped at `max_speed`. Returns 1.0 when it already fits (within slack) or the
    slot is degenerate (≤ 0). When the uncapped ratio exceeds `max_speed` the
    result is the cap — the caller then places the (still-too-long) render and
    lets it overflow rather than truncating. Pure: the timestamp-fit policy."""
    if slot <= 0 or natural <= slot + _FIT_EPS:
        return 1.0
    return min(natural / slot, max_speed)


def cue_budget(start: float, next_start: float) -> float:
    """Room a cue's speech may occupy: its own window PLUS the trailing silent
    gap before the next cue begins. Speech overflows [start, end] into that gap
    without overlapping the next cue, so a cue with a far-away successor needs no
    speed-up even when its own [start, end] window is short. `next_start` is the
    following cue's start (or the track end for the last cue). Pure."""
    return max(0.0, next_start - start)


def run_tts_dub(
    *,
    srt_path: str,
    subtitles_dir: str,
    lang_iso: str,
    video_duration_sec: float,
    provider: str,
    voice_id: str,
    options: dict[str, Any] | None = None,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Synthesize a dubbing track for `srt_path` and write the audio + manifest.

    Returns {audio_path, manifest_path, total_sec, cue_count, spoken_count,
    overflow_count}. Raises on synthesis / ffmpeg failure; returns early with a
    None-ish result is NOT done — cancellation surfaces as AIError(CANCELLED).
    """
    opts = options or {}
    max_speed = float(opts.get("max_speed", DEFAULT_MAX_SPEED))
    if max_speed < 1.0:
        max_speed = 1.0

    cues = list(srt.parse(read_srt(srt_path)))
    last_end = cues[-1].end.total_seconds() if cues else 0.0
    total_sec = float(video_duration_sec) if video_duration_sec and video_duration_sec > 0 else last_end
    if total_sec < last_end:
        # A cue ends past the declared video duration (rare); never clip it off.
        total_sec = last_end

    manifest_path = analysis_path(subtitles_dir, lang_iso, "dub")

    placements: list[dict[str, Any]] = []
    mix_inputs: list[dict[str, Any]] = []
    overflow_count = 0
    n = len(cues)
    engine_speed = provider in _ENGINE_SPEED_PROVIDERS

    tmpdir = tempfile.mkdtemp(prefix="vc_dub_")
    try:
        for i, cue in enumerate(cues):
            if cancel_token is not None:
                cancel_token.throw_if_cancelled(provider)

            text = _spoken_text(cue.content)
            start = cue.start.total_seconds()
            end = cue.end.total_seconds()
            # Fit against the room until the NEXT cue starts (window + trailing
            # gap), not just this cue's own [start, end] — a far-away next cue
            # means the speech can overflow into the silence and need no speed-up.
            next_start = cues[i + 1].start.total_seconds() if i + 1 < n else total_sec
            budget = cue_budget(start, next_start)

            _emit(progress_cb, ProgressInfo(
                phase="synth",
                percent=(i / n * 90.0) if n else 0.0,
                status_text=f"配音合成 {i + 1}/{n}",
            ))

            if not text:
                placements.append({
                    "idx": cue.index, "start": round(start, 3), "end": round(end, 3),
                    "natural": 0.0, "speed": 1.0, "placed": 0.0,
                    "overflowed": False, "skipped": True,
                })
                continue

            pass1 = os.path.join(tmpdir, f"{i:05d}_1.mp3")
            ai.tts(text, pass1, provider=provider, voice_id=voice_id,
                   audio_format="mp3", speed=1.0, cancel_token=cancel_token)
            natural = video_ops.probe_duration_sec(pass1)

            speed = compute_speed(natural, budget, max_speed)
            if speed <= 1.0:
                placed_path = pass1
                placed = natural
            else:
                pass2 = os.path.join(tmpdir, f"{i:05d}_2.mp3")
                if engine_speed:
                    ai.tts(text, pass2, provider=provider, voice_id=voice_id,
                           audio_format="mp3", speed=speed, cancel_token=cancel_token)
                else:
                    video_ops.time_stretch_audio(pass1, pass2, speed)
                placed_path = pass2
                placed = video_ops.probe_duration_sec(pass2)

            # Overflow = the placed speech runs past the budget (into the next cue).
            overflowed = (budget > 0) and (placed > budget + _FIT_EPS)
            if overflowed:
                overflow_count += 1

            placements.append({
                "idx": cue.index, "start": round(start, 3), "end": round(end, 3),
                "budget": round(budget, 3), "natural": round(natural, 3),
                "speed": round(speed, 4), "placed": round(placed, 3),
                "overflowed": overflowed,
            })
            mix_inputs.append({"path": placed_path, "delay_sec": start})

        _emit(progress_cb, ProgressInfo(
            phase="assembling", percent=92.0, status_text="拼接配音音轨...",
        ))
        if cancel_token is not None:
            cancel_token.throw_if_cancelled(provider)

        # Resolve the version slot: one version per (provider, voice_id). Re-synth
        # of the same voice updates that version's audio in place; a new voice
        # appends a new version (so the user can keep several to compare).
        existing = _load_versions(manifest_path)
        version_id = _version_id_for(existing, provider, voice_id)
        audio_name = f"{lang_iso}.dub.{version_id}.mp3"
        audio_path = os.path.join(subtitles_dir, audio_name)

        os.makedirs(subtitles_dir, exist_ok=True)
        tmp_audio = audio_path + ".tmp.mp3"
        video_ops.assemble_delayed_mix(mix_inputs, total_sec, tmp_audio)
        os.replace(tmp_audio, audio_path)
    finally:
        _cleanup_dir(tmpdir)

    spoken_count = sum(1 for p in placements if not p.get("skipped"))
    version = {
        "id": version_id,
        "name": _voice_display_name(provider, voice_id),
        "audio_file": audio_name,
        "total_sec": round(total_sec, 3),
        "provider": provider,
        "voice_id": voice_id,
        "policy": {"mode": "engine_speed" if engine_speed else "atempo", "max_speed": max_speed},
        "cue_count": n,
        "spoken_count": spoken_count,
        "overflow_count": overflow_count,
        "cues": placements,
    }
    # Replace the same-id version (re-synth) or append; keep ordered by id.
    versions = [v for v in existing if int(v.get("id", -1)) != version_id]
    versions.append(version)
    versions.sort(key=lambda v: int(v.get("id", 0)))
    _write_json_atomic(manifest_path, {"version": 2, "lang": lang_iso, "versions": versions})

    _emit(progress_cb, ProgressInfo(phase="done", percent=100.0, status_text="配音完成"))
    return {
        "audio_path": audio_path,
        "manifest_path": manifest_path,
        "version_id": version_id,
        "name": version["name"],
        "total_sec": round(total_sec, 3),
        "cue_count": n,
        "spoken_count": spoken_count,
        "overflow_count": overflow_count,
    }


# ── Version collection (multiple voices per language) ────────────────────────

def _load_versions(manifest_path: str) -> list[dict[str, Any]]:
    """Read the v2 dub manifest's `versions` list (empty when missing/legacy)."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    versions = data.get("versions") if isinstance(data, dict) else None
    return [v for v in versions if isinstance(v, dict)] if isinstance(versions, list) else []


def _next_id(versions: list[dict[str, Any]]) -> int:
    return max((int(v.get("id", 0)) for v in versions), default=0) + 1


def _version_id_for(versions: list[dict[str, Any]], provider: str, voice_id: str) -> int:
    """The version id for a (provider, voice_id): reuse the matching version's id
    (re-synth updates it) or allocate the next free id (a new voice)."""
    for v in versions:
        if v.get("provider") == provider and v.get("voice_id") == voice_id:
            try:
                return int(v["id"])
            except (KeyError, ValueError, TypeError):
                break
    return _next_id(versions)


def _voice_display_name(provider: str, voice_id: str) -> str:
    """Human label for a voice (catalog display name; falls back to the id)."""
    try:
        from core.ai.tts_voice import find_voice

        v = find_voice(provider, voice_id)
        if v and v.display_name:
            return v.display_name
    except Exception:
        pass
    return voice_id


def remove_dub_version(subtitles_dir: str, lang_iso: str, version_id: int) -> dict[str, Any]:
    """Delete one dub version: its audio file + its manifest entry. When no
    versions remain, the manifest is deleted too (so the sidebar node clears).
    Returns {removed, remaining}."""
    manifest_path = analysis_path(subtitles_dir, lang_iso, "dub")
    versions = _load_versions(manifest_path)
    keep: list[dict[str, Any]] = []
    removed: dict[str, Any] | None = None
    for v in versions:
        if int(v.get("id", -1)) == int(version_id):
            removed = v
        else:
            keep.append(v)
    if removed is not None:
        audio = os.path.join(subtitles_dir, str(removed.get("audio_file", "")))
        try:
            os.remove(audio)
        except OSError:
            pass
    if keep:
        _write_json_atomic(manifest_path, {"version": 2, "lang": lang_iso, "versions": keep})
    else:
        try:
            os.remove(manifest_path)
        except OSError:
            pass
    return {"removed": removed is not None, "remaining": len(keep)}


def _write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _cleanup_dir(path: str) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
