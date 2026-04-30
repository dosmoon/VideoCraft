"""SRT quality fingerprint — cheap structural signals, no scoring.

Outputs facts about a subtitle file (cue count, avg duration, punctuation
ratio, ALL-CAPS ratio, speaker/sound tags, reading rate) so users can
judge quality themselves. Deliberately avoids returning a good/fair/bad
label because the thresholds are guesses and scoring varies by language.

Designed to run on any well-formed SRT in <100ms with zero deps.
"""

from __future__ import annotations

import re
from typing import Optional

_TS = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s+-->\s+(\d+):(\d+):(\d+),(\d+)")
_SPEAKER = re.compile(r"^[A-Z][a-zA-Z .]{1,18}:\s")
_SOUNDFX = re.compile(r"[\[\(♪]")
_PUNCT_END = ".!?,:;。！？，；："


def _ts_to_sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: str) -> list[tuple[float, float, str]]:
    """Return [(start_s, end_s, text), ...]. Tolerant of stray blank lines."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues: list[tuple[float, float, str]] = []
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 2:
            continue
        # First non-numeric line is the timestamp.
        ts_line = lines[1] if lines[0].strip().isdigit() else lines[0]
        m = _TS.match(ts_line)
        if not m:
            continue
        start = _ts_to_sec(*m.groups()[:4])
        end = _ts_to_sec(*m.groups()[4:])
        text_start = 2 if lines[0].strip().isdigit() else 1
        text = "\n".join(lines[text_start:]).strip()
        if text:
            cues.append((start, end, text))
    return cues


def fingerprint(path: str) -> Optional[dict]:
    """Compute structural metrics for an SRT. Returns None on empty/unparseable."""
    cues = parse_srt(path)
    if not cues:
        return None
    n = len(cues)
    durs = [e - s for s, e, _ in cues]
    texts = [t for _, _, t in cues]
    chars = [len(t.replace("\n", " ")) for t in texts]
    speech_secs = sum(durs) or 1e-6
    cps = sum(chars) / speech_secs

    punct_end = sum(1 for t in texts if t.rstrip() and t.rstrip()[-1] in _PUNCT_END)
    def _letters(t: str) -> str:
        return "".join(c for c in t if c.isalpha())
    upper_only = sum(1 for t in texts if _letters(t) and _letters(t).isupper())
    speaker_tags = sum(1 for t in texts if _SPEAKER.match(t))
    sound_fx = sum(1 for t in texts if _SOUNDFX.search(t))

    return {
        "cues": n,
        "first_cue_s": cues[0][0],
        "span_s": cues[-1][1] - cues[0][0],
        "avg_dur_s": sum(durs) / n,
        "avg_chars": sum(chars) / n,
        "cps": cps,
        "punct_end_ratio": punct_end / n,
        "uppercase_ratio": upper_only / n,
        "speaker_tags": speaker_tags,
        "sound_fx": sound_fx,
    }


def format_fingerprint(fp: dict) -> str:
    """One-line UI-friendly summary."""
    parts = [
        f"{fp['cues']} cues",
        f"avg {fp['avg_dur_s']:.1f}s",
        f"{fp['avg_chars']:.0f} chars",
        f"punct {fp['punct_end_ratio']*100:.0f}%",
        f"cps {fp['cps']:.1f}",
    ]
    if fp["uppercase_ratio"] > 0.5:
        parts.append(f"ALL-CAPS {fp['uppercase_ratio']*100:.0f}%")
    if fp["speaker_tags"]:
        parts.append(f"speaker tags {fp['speaker_tags']}")
    if fp["sound_fx"]:
        parts.append(f"sfx {fp['sound_fx']}")
    if fp["first_cue_s"] > 30:
        parts.append(f"starts at {fp['first_cue_s']:.0f}s")
    return " · ".join(parts)
