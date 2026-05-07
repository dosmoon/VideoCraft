"""ASR feature layer — audio/video file -> SRT + verbose JSON.

UI calls transcribe_audio() with an `on_event` callback; this module owns
AI dispatch (via core.ai.asr), SRT rendering, JSON persistence, and output
path resolution (with automatic language-suffix correction when the
detected language differs from what the user selected).

── Timestamp contract: BOTH sentence-level AND word-level required ─────────
Every ASR provider VideoCraft uses must return verbose_json containing
TWO independent timestamp layers:

  segments[]  sentence-level semantic units (one complete sentence each).
              Drives translate_srt.py — each SRT row becomes one LLM call
              with full sentence context. Cue length is unbounded; do NOT
              client-side split sentences here, or LLM translation quality
              collapses (clauses lose tense / referent / topic).

  words[]     word-level (or character-level for CJK) timestamps. NOT
              consumed by translation. Reserved for the burn-subtitles
              module's future aspect-ratio-aware cue-sizer: portrait video
              needs narrower cues than landscape, karaoke overlays need
              per-word timing, multi-line wrap needs to align with word
              boundaries. The current SRT writer below is deliberately a
              one-segment-one-row passthrough — the sophisticated cue-
              sizing belongs in burn_subs.py and runs AFTER translation,
              on the translated sentence text.

So: ASR → sentence segments + word timestamps; translate at sentence
granularity; cue-size at burn time using both layers + video aspect
ratio. Three stages, each does its one job — never compose them.
"""

import json
import os
import re
from typing import Callable

from core import ai
from core.lang_names import WHISPER_LANGUAGES


def transcribe_audio(
    audio_path: str,
    output_srt_path: str,
    *,
    expected_lang_iso: str | None = None,
    language: str | None = None,
    translate: bool = False,
    speaker_labels: bool = False,
    provider: str | None = None,
    on_event: Callable[..., None] | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio and write both .srt and .json outputs.

    Args:
        audio_path:        Source audio/video file.
        output_srt_path:   Target SRT path. If detected language differs
                           from `expected_lang_iso`, the path's language
                           suffix is rewritten automatically.
        expected_lang_iso: ISO code the user selected, or None for "Auto
                           Detect". Used to decide whether to rewrite the
                           output suffix.
        language:          Hint to pass to the provider (display name or
                           None for auto-detect).
        translate:         If True, output is translated to English.
        speaker_labels:    If True, SRT lines prefixed with [SPEAKER_xx].
        provider:          ASR provider override. None (default) resolves
                           from AI Console task_routing[asr.transcribe];
                           falls back to "lemonfox" when unset.
        on_event:          Optional (event_type, **kwargs) callback for
                           upload progress / retries / wait ticks. UI
                           translates event types via i18n.

    Returns:
        {
            "srt_path":           final .srt path (may differ from
                                  output_srt_path when suffix was rewritten),
            "json_path":          sibling .json path next to the SRT,
            "detected_lang":      display name reported by the provider,
            "detected_lang_iso":  ISO code (best-effort lookup),
            "expected_lang_iso":  same value passed in (echoed for UI),
            "lang_mismatch":      True when expected != detected (and
                                  expected was not auto),
            "duration":           seconds or "?" if provider omitted it,
            "segment_count":      number of segments in the response,
            "word_count":         number of word-level timestamps (0 if
                                  the provider returned only segments),
        }

    Raises:
        RuntimeError: provider error or all retries exhausted.
    """
    result = ai.asr(
        audio_path,
        provider=provider,
        language=language,
        translate=translate,
        speaker_labels=speaker_labels,
        on_event=on_event,
        cancel_token=cancel_token,
    )

    # Resolve detected language and decide on output suffix rewrite.
    # Note: Whisper-family backends treat the `language` parameter as
    # "output in THIS language" (auto-translating if needed), NOT "the
    # audio IS in this language". So when a hint is provided, `result["language"]`
    # simply echoes the hint and lang_mismatch is effectively a no-op.
    # Mismatch detection only produces meaningful results when the user
    # runs in Auto Detect mode; the UI nudges toward that by defaulting
    # the dropdown to Auto Detect.
    detected_name = result.get("language", "")
    detected_iso = _iso_from_english(detected_name) if detected_name else None

    is_auto = expected_lang_iso is None
    lang_mismatch = (
        (not is_auto)
        and detected_iso is not None
        and detected_iso != expected_lang_iso
    )

    final_srt_path = output_srt_path
    if detected_iso is not None and (is_auto or lang_mismatch):
        final_srt_path = _apply_lang_suffix(output_srt_path, detected_iso)

    # Save raw verbose_json alongside the SRT for word-level access
    json_path = os.path.splitext(final_srt_path)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(result, jf, ensure_ascii=False, indent=2)

    # Build SRT from the segments array
    srt_content = _verbose_json_to_srt(result)
    srt_content = _clean_srt_content(srt_content)
    with open(final_srt_path, "w", encoding="utf-8", newline="") as sf:
        sf.write(srt_content)

    return {
        "srt_path":          final_srt_path,
        "json_path":         json_path,
        "detected_lang":     detected_name,
        "detected_lang_iso": detected_iso,
        "expected_lang_iso": expected_lang_iso,
        "lang_mismatch":     lang_mismatch,
        "duration":          result.get("duration", "?"),
        "segment_count":     len(result.get("segments", [])),
        "word_count":        len(result.get("words", [])),
    }


# ── Language ISO lookup ──────────────────────────────────────────────────────

def _iso_from_english(english_name: str) -> str | None:
    """Best-effort ISO code lookup from English language name.
    Falls back to the first 2 lowercase chars if not found."""
    if not english_name:
        return None
    target = english_name.lower()
    for code, (eng, _chn) in WHISPER_LANGUAGES.items():
        if eng.lower() == target:
            return code
    # Fallback: first 2 chars (historical behavior from speech2text.py)
    return english_name[:2].lower() if english_name else None


_LANG_SUFFIX_RE = re.compile(r"_[a-z]{2,5}(\.srt)$", re.IGNORECASE)


def _apply_lang_suffix(srt_path: str, iso: str) -> str:
    """Strip any existing _<lang>.srt suffix and append _<iso>.srt."""
    stripped = _LANG_SUFFIX_RE.sub(r"\1", srt_path)
    base = stripped[:-4] if stripped.lower().endswith(".srt") else stripped
    return f"{base}_{iso}.srt"


# ── SRT rendering ────────────────────────────────────────────────────────────

def _verbose_json_to_srt(data: dict) -> str:
    """Render verbose_json `segments[]` to SRT text — one row per segment.

    Intentionally a passthrough: each sentence-level segment becomes one
    SRT row. See module docstring for the full contract — short version:
    translate_srt.py is row-by-row, so cue-splitting here would break LLM
    translation; broadcast-style cue-sizing belongs in burn_subs.py and
    runs AFTER translation using both segments[] and words[].

    Segments with a `speaker` field get a [SPEAKER_xx] prefix.
    """
    lines = []
    for i, seg in enumerate(data.get("segments", []), 1):
        start   = _format_timestamp(seg["start"])
        end     = _format_timestamp(seg["end"])
        text    = seg["text"].strip()
        speaker = seg.get("speaker", "")
        if speaker:
            text = f"[{speaker}] {text}"
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _format_timestamp(t: float, always_include_hours: bool = True,
                      decimal_marker: str = ",") -> str:
    """Format seconds -> 'HH:MM:SS,mmm'."""
    hours = int(t // 3600)
    mins  = int((t % 3600) // 60)
    secs  = int(t % 60)
    msecs = int(round((t - int(t)) * 1000))
    if always_include_hours or hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}{decimal_marker}{msecs:03d}"
    return f"{mins:02d}:{secs:02d}{decimal_marker}{msecs:03d}"


def _clean_srt_content(srt_content: str) -> str:
    """Normalize line endings. Providers sometimes return escaped newlines;
    this un-escapes them and converts to CRLF (what SRT expects)."""
    if not srt_content:
        return ""
    cleaned = srt_content.strip('"')
    cleaned = cleaned.replace('\\n', '\n')
    cleaned = cleaned.replace('\r\n', '\n').replace('\n', '\r\n')
    return cleaned
