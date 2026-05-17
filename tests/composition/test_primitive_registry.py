"""Primitive renderer registry — register / lookup / duplicate guards."""

from __future__ import annotations

import pytest

from core.composition import primitives


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty registry. The 7 real primitive
    modules land in PR 2; nothing self-registers in PR 1, so reset is
    purely test hygiene against cross-test leakage.
    """
    primitives._reset_for_tests()
    yield
    primitives._reset_for_tests()


def test_register_and_lookup():
    def renderer(*_a, **_kw): return "rendered"
    primitives.register_overlay_renderer("subtitle_cue", renderer)
    assert primitives.is_registered("subtitle_cue")
    assert primitives.get_overlay_renderer("subtitle_cue") is renderer


def test_duplicate_registration_raises():
    def r1(*_a, **_kw): return None
    def r2(*_a, **_kw): return None
    primitives.register_overlay_renderer("text_watermark", r1)
    with pytest.raises(ValueError, match="already registered"):
        primitives.register_overlay_renderer("text_watermark", r2)


def test_unknown_lookup_raises():
    with pytest.raises(KeyError, match="not registered"):
        primitives.get_overlay_renderer("nonexistent_kind")


def test_empty_kind_raises():
    with pytest.raises(ValueError, match="empty kind"):
        primitives.register_overlay_renderer("", lambda *a, **kw: None)


def test_is_registered_false_for_unknown():
    assert primitives.is_registered("nope") is False
