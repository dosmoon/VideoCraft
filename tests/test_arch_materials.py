"""Architecture compliance regression guard for materials/news_video.

Asserts the ADR-0004 + ADR-0005 invariants that the plugin is
supposed to maintain. Failing here = the architecture has rotted and
needs review BEFORE shipping.

Post-P2 (Tk app retired): the Hub / sidebar / node_panes / plugin-UI
separation guards are gone with the Tk presentation layer. What remains
are the headless/sidecar invariants — the model is zero-Tk, schema /
paths / ai_fill live in the plugin, and core/ never imports the plugin
by name (except the documented warts).

Two known cross-tier warts are whitelisted in KNOWN_WART_FILES;
adding a third triggers a fail.
"""

from __future__ import annotations

import inspect
import os
import re

import materials
import materials.news_video  # noqa: F401  trigger registration
from materials import MaterialType
from materials.news_video.model import NewsVideoModel


# ── Acceptable cross-tier warts (must carry TODO(ADR-0005) markers) ─────────

KNOWN_WART_FILES = {
    os.path.normpath("src/core/subtitle_pipeline.py"),
    os.path.normpath("src/core/subtitle_analysis_runners.py"),
}


# ── A. Plugin contract ───────────────────────────────────────────────────────

def test_news_video_self_registers():
    assert materials.get("news_video") is not None


def test_material_type_required_fields_filled():
    mt = materials.get("news_video")
    for f in ("type_name", "display_name_key", "icon",
              "description_zh", "description_en", "instance_factory"):
        v = getattr(mt, f, None)
        assert v not in (None, ""), f"MaterialType.{f} empty"


def test_instance_factory_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.instance_factory).parameters.keys())
    assert params == ["project", "instance_id"]


def test_has_instance_field_retired():
    assert "has_instance" not in MaterialType.__dataclass_fields__


# ── B. Data ownership ────────────────────────────────────────────────────────

def test_source_context_schema_in_plugin():
    from materials.news_video.schema import SourceContext
    assert len(SourceContext.__dataclass_fields__) == 15


def test_paths_resolver_in_plugin():
    from materials.news_video import paths
    assert hasattr(paths, "source_dir")
    assert hasattr(paths, "subtitles_dir")


def test_schema_io_in_plugin():
    from materials.news_video.schema import (
        read_basic_info, write_basic_info, read_context, write_context,
    )
    assert callable(read_basic_info)
    assert callable(write_basic_info)
    assert callable(read_context)
    assert callable(write_context)


def test_ai_fill_in_plugin():
    from materials.news_video import ai_fill
    assert hasattr(ai_fill, "extract")


def test_core_does_not_import_plugin_outside_known_warts():
    """core/ MUST NOT import materials.news_video.* except for the
    documented warts in KNOWN_WART_FILES."""
    violations: list[str] = []
    for root, dirs, files in os.walk("src/core"):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.normpath(os.path.join(root, fn))
            with open(p, "r", encoding="utf-8") as f:
                c = f.read()
            if re.search(r"(^|\n)\s*(from|import)\s+materials\.news_video", c):
                if p not in KNOWN_WART_FILES:
                    violations.append(p)
    assert not violations, (
        f"unauthorized core/-side plugin imports: {violations}; "
        f"add to KNOWN_WART_FILES only with a TODO(ADR-0005) marker."
    )


# ── C. NewsVideoModel surface ────────────────────────────────────────────────

def test_news_video_model_constructor_signature():
    params = list(inspect.signature(NewsVideoModel.__init__).parameters.keys())
    assert params == ["self", "project", "instance_id"]


def test_news_video_model_is_zero_tk():
    """The model is the canonical no-Tk layer. Importing tkinter from
    inside it would break headless usage (sidecar, tests)."""
    with open("src/materials/news_video/model.py", "r", encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"\bimport tkinter\b|\bfrom tkinter\b", src) is None


def test_news_video_model_path_properties():
    for prop in ("instance_dir", "source_dir", "subtitles_dir",
                 "source_video_path", "source_meta_path"):
        assert hasattr(NewsVideoModel, prop), f"missing property {prop}"


def test_news_video_model_business_methods():
    methods = ["commit_source", "read_basic_info", "write_basic_info",
               "read_context", "write_context", "ai_fill_context",
               "run_asr", "run_translate", "import_subtitle",
               "quick_fix_subtitle", "run_analysis", "check_subtitle",
               "list_subtitle_languages", "list_analysis_artifacts",
               "slot_readiness", "get_artifact", "subscribe"]
    missing = [m for m in methods if not hasattr(NewsVideoModel, m)]
    assert not missing, f"NewsVideoModel missing methods: {missing}"


def test_write_methods_call_notify():
    """All write methods must call _notify() so subscribers get refreshed."""
    with open("src/materials/news_video/model.py", "r", encoding="utf-8") as f:
        src = f.read()
    write_methods = ["commit_source", "write_basic_info", "write_context",
                     "ai_fill_context", "run_asr", "run_translate",
                     "import_subtitle", "quick_fix_subtitle", "run_analysis"]
    missing: list[str] = []
    for m in write_methods:
        pat = re.compile(rf"def {m}\b.*?(?=\n    def |\nclass |\Z)", re.DOTALL)
        match = pat.search(src)
        if match and "_notify(" not in match.group(0):
            missing.append(m)
    assert not missing, f"write methods missing _notify: {missing}"


# ── D. Multi-instance ────────────────────────────────────────────────────────

def test_paths_accept_explicit_instance_id():
    with open("src/materials/news_video/paths.py", "r", encoding="utf-8") as f:
        src = f.read()
    assert "instance_id: str | None = None" in src


# ── E. Headlessness ──────────────────────────────────────────────────────────

def test_core_zero_tk():
    """core/ MUST NOT import tkinter. The engines are headless."""
    violations: list[str] = []
    for root, dirs, files in os.walk("src/core"):
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
    """Post-P2 invariant: the news_video sidecar plugin imports zero
    tkinter — all UI lives in the new-arch Electron renderer (desktop/)."""
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
