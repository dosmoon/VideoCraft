"""Mirror test: pyproject.toml is the single source of truth for dependency pins.

The runtime opt-in tiers (embedded-ai, gpu) install at runtime into py-extra via
core.runtime_extras, NOT via `uv sync`, so their pins live as module constants in
the installers (core.embedded_ai_install / core.gpu_install) for dead-simple
runtime code. pyproject.toml's [project.optional-dependencies] is the logical
authority (ADR-0009); these tests fail if the constants drift from it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from core import embedded_ai_install, gpu_install

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def test_pyproject_exists_with_extras():
    extras = _extras()
    assert "embedded-ai" in extras
    assert "gpu" in extras


def test_embedded_ai_pins_mirror_pyproject():
    """embedded_ai_install._PACKAGES == pyproject [embedded-ai] extra."""
    assert sorted(embedded_ai_install._PACKAGES) == sorted(_extras()["embedded-ai"])


def test_gpu_pins_mirror_pyproject():
    """gpu_install._TOP_LEVEL (pinned install specs) == pyproject [gpu] extra."""
    assert sorted(gpu_install._TOP_LEVEL) == sorted(_extras()["gpu"])


def test_gpu_top_level_pins_are_pinned():
    """Every GPU wheel carries an exact == pin (reproducibility + mirror check)."""
    for spec in gpu_install._TOP_LEVEL:
        assert "==" in spec, f"GPU wheel {spec!r} must be pinned with =="
