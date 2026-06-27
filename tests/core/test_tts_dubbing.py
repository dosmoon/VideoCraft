"""Unit tests for the TTS dubbing timestamp-fit policy + ffmpeg audio helpers.

The network (TTS) and ffmpeg-bound parts of run_tts_dub are exercised by the
end-to-end sidecar run; here we pin the pure decision logic (compute_speed,
_spoken_text) and the atempo chain decomposition.
"""

from __future__ import annotations

import json
import os

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


# ── cue_budget + gap-aware fit (don't speed up when there's room) ─────────────

def test_cue_budget_spans_window_plus_trailing_gap():
    # Cue [0,2] with the next cue at 10 → 10s of room, not just the 2s window.
    assert td.cue_budget(start=0.0, next_start=10.0) == 10.0


def test_cue_budget_back_to_back_is_just_the_window():
    # Next cue starts where this one ends → budget == the cue's own window.
    assert td.cue_budget(start=3.0, next_start=5.0) == 2.0


def test_cue_budget_never_negative():
    assert td.cue_budget(start=5.0, next_start=4.0) == 0.0


def test_gap_aware_fit_no_speedup_when_a_later_cue_is_far():
    # A 3.6s render into a 3.0s window WOULD be 1.2x by window alone, but with a
    # far-away next cue the budget is large → no speed-up (the user's bug).
    assert td.compute_speed(natural=3.6, slot=td.cue_budget(0.0, 10.0), max_speed=1.5) == 1.0
    # Same render, but the next cue is close → budget is tight → it speeds up.
    assert td.compute_speed(natural=3.6, slot=td.cue_budget(0.0, 3.0), max_speed=1.5) == 1.2


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


# ── Version collection (one version per voice) ───────────────────────────────

def test_version_id_reuses_same_voice_allocates_for_new():
    versions = [
        {"id": 1, "provider": "edge_tts", "voice_id": "A"},
        {"id": 2, "provider": "edge_tts", "voice_id": "B"},
    ]
    assert td._version_id_for(versions, "edge_tts", "A") == 1  # re-synth updates
    assert td._version_id_for(versions, "edge_tts", "C") == 3  # new voice → next id
    assert td._version_id_for([], "edge_tts", "A") == 1


def test_remove_dub_version_deletes_audio_and_entry(tmp_path):
    subs = str(tmp_path)
    # Two versions on disk + manifest.
    for vid in (1, 2):
        with open(os.path.join(subs, f"zh.dub.{vid}.mp3"), "w") as f:
            f.write("x")
    manifest = os.path.join(subs, "zh.dub.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "lang": "zh", "versions": [
            {"id": 1, "name": "A", "audio_file": "zh.dub.1.mp3"},
            {"id": 2, "name": "B", "audio_file": "zh.dub.2.mp3"},
        ]}, f)

    res = td.remove_dub_version(subs, "zh", 1)
    assert res == {"removed": True, "remaining": 1}
    assert not os.path.exists(os.path.join(subs, "zh.dub.1.mp3"))  # audio gone
    assert os.path.exists(os.path.join(subs, "zh.dub.2.mp3"))      # other kept
    left = json.load(open(manifest, encoding="utf-8"))["versions"]
    assert [v["id"] for v in left] == [2]


def test_remove_last_dub_version_clears_the_manifest(tmp_path):
    subs = str(tmp_path)
    with open(os.path.join(subs, "zh.dub.1.mp3"), "w") as f:
        f.write("x")
    manifest = os.path.join(subs, "zh.dub.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "lang": "zh", "versions": [
            {"id": 1, "name": "A", "audio_file": "zh.dub.1.mp3"},
        ]}, f)

    res = td.remove_dub_version(subs, "zh", 1)
    assert res == {"removed": True, "remaining": 0}
    assert not os.path.exists(manifest)  # node clears when empty
    assert not os.path.exists(os.path.join(subs, "zh.dub.1.mp3"))
