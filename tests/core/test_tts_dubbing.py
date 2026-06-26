"""Unit tests for the TTS dubbing timestamp-fit policy + ffmpeg audio helpers.

The network (TTS) and ffmpeg-bound parts of run_tts_dub are exercised by the
end-to-end sidecar run; here we pin the pure decision logic (compute_speed,
_spoken_text) and the atempo chain decomposition.
"""

from __future__ import annotations

from core import tts_dubbing as td
from core import video_ops as vo


# ── compute_speed: the timestamp-fit policy ──────────────────────────────────

def test_compute_speed_fits_within_slot_is_unity():
    assert td.compute_speed(natural=1.0, slot=2.0, max_speed=1.5) == 1.0


def test_compute_speed_within_slack_is_unity():
    # Just over the slot but inside _FIT_EPS → still no speed-up.
    assert td.compute_speed(natural=2.0 + td._FIT_EPS / 2, slot=2.0, max_speed=1.5) == 1.0


def test_compute_speed_speeds_up_to_fit():
    # 3s into a 2s slot → 1.5×, under the cap.
    assert td.compute_speed(natural=3.0, slot=2.0, max_speed=2.0) == 1.5


def test_compute_speed_is_capped():
    # 4s into a 2s slot would need 2.0× but the cap is 1.5× → capped (overflow).
    assert td.compute_speed(natural=4.0, slot=2.0, max_speed=1.5) == 1.5


def test_compute_speed_degenerate_slot_is_unity():
    assert td.compute_speed(natural=3.0, slot=0.0, max_speed=1.5) == 1.0
    assert td.compute_speed(natural=3.0, slot=-1.0, max_speed=1.5) == 1.0


# ── _spoken_text: cue-body flattening ────────────────────────────────────────

def test_spoken_text_strips_tags_and_newlines():
    assert td._spoken_text("<i>Hello</i>\nworld") == "Hello world"


def test_spoken_text_collapses_whitespace():
    assert td._spoken_text("  a   b\t c \n") == "a b c"


def test_spoken_text_empty():
    assert td._spoken_text("") == ""
    assert td._spoken_text("  \n ") == ""


# ── atempo_chain: speed-factor decomposition (atempo only spans 0.5–2.0) ──────

def test_atempo_chain_noop_for_unity():
    assert vo.atempo_chain(1.0) == ""


def test_atempo_chain_single_step_in_range():
    assert vo.atempo_chain(1.5) == "atempo=1.500000"


def test_atempo_chain_decomposes_large_speedup():
    # 2.5 = 2.0 × 1.25
    assert vo.atempo_chain(2.5) == "atempo=2.000000,atempo=1.250000"


def test_atempo_chain_decomposes_large_slowdown():
    # 0.3 = 0.5 × 0.6
    assert vo.atempo_chain(0.3) == "atempo=0.500000,atempo=0.600000"


def test_atempo_chain_rejects_nonpositive():
    import pytest

    with pytest.raises(ValueError):
        vo.atempo_chain(0.0)
