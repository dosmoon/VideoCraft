"""Architecture compliance regression guard for materials/news_video.

Asserts the ADR-0004 / ADR-0005 / ADR-0008 invariants the plugin must maintain.
Failing here = the architecture has rotted and needs review BEFORE shipping.

Post-ADR-0008 B5: the news_video data model / schema / paths / ai_fill (Python)
were retired — the data model lives in TS (desktop/src/materials/news_video/) and
long-running work runs via the plugin-agnostic capability.* gateway. The sidecar
plugin is now just type metadata. The surviving invariants are: the type still
self-registers, and core/ imports NO material plugin by name (the old
TODO(ADR-0005) cross-tier warts are gone — full decoupling).
"""

from __future__ import annotations

import os
import re

import materials
import materials.news_video  # noqa: F401  trigger registration
from materials import MaterialType


# ── A. Plugin contract ───────────────────────────────────────────────────────

def test_news_video_self_registers():
    assert materials.get("news_video") is not None


def test_material_type_required_fields_filled():
    mt = materials.get("news_video")
    for f in ("type_name", "display_name_key", "icon",
              "description_zh", "description_en"):
        v = getattr(mt, f, None)
        assert v not in (None, ""), f"MaterialType.{f} empty"
    assert mt.single_instance is True
    assert callable(mt.suggest_name)


def test_has_instance_field_retired():
    assert "has_instance" not in MaterialType.__dataclass_fields__


def test_instance_factory_field_retired():
    """ADR-0008 B5 retired the Python instance_factory (model lives in TS)."""
    assert "instance_factory" not in MaterialType.__dataclass_fields__


# ── B. Full core/ ↔ plugin decoupling (ADR-0008) ─────────────────────────────

def test_core_does_not_import_news_video_plugin():
    """ADR-0008: core/ MUST NOT import materials.news_video.* at all. The old
    subtitle_pipeline / subtitle_analysis_runners warts were removed — the
    path-based pipeline takes injected paths and the analysis runner takes an
    injected context_block, so core/ carries zero material-plugin dependency."""
    violations: list[str] = []
    for root, _dirs, files in os.walk("src/core"):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.normpath(os.path.join(root, fn))
            with open(p, "r", encoding="utf-8") as f:
                c = f.read()
            if re.search(r"(^|\n)\s*(from|import)\s+materials\.news_video", c):
                violations.append(p)
    assert not violations, f"core/ imports the news_video plugin: {violations}"


# ── C. Headlessness ──────────────────────────────────────────────────────────

def test_core_zero_tk():
    """core/ MUST NOT import tkinter. The engines are headless."""
    violations: list[str] = []
    for root, _dirs, files in os.walk("src/core"):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.normpath(os.path.join(root, fn))
            with open(p, "r", encoding="utf-8") as f:
                c = f.read()
            if re.search(r"\bimport tkinter\b|\bfrom tkinter\b", c):
                violations.append(p)
    assert not violations, f"core/ imports tkinter in: {violations}"


def test_news_video_plugin_is_headless_no_tkinter():
    """The news_video sidecar plugin imports zero tkinter — all UI lives in the
    new-arch Electron renderer (desktop/)."""
    violations: list[str] = []
    for root, _dirs, files in os.walk("src/materials/news_video"):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.normpath(os.path.join(root, fn))
            with open(p, "r", encoding="utf-8") as f:
                c = f.read()
            if re.search(r"(^|\n)\s*(from\s+tkinter|import\s+tkinter)", c):
                violations.append(p)
    assert not violations, f"news_video still imports tkinter: {violations}"
