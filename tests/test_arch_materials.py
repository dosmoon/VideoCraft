"""Architecture compliance regression guard for materials/news_video.

Asserts the ADR-0004 + ADR-0005 invariants that the plugin is
supposed to maintain. Failing here = the architecture has rotted and
needs review BEFORE shipping.

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
              "description_zh", "description_en",
              "sidebar_renderer", "create_handler", "instance_factory"):
        v = getattr(mt, f, None)
        assert v not in (None, ""), f"MaterialType.{f} empty"


def test_sidebar_renderer_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.sidebar_renderer).parameters.keys())
    assert params == ["parent", "hub", "instance_id"]


def test_create_handler_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.create_handler).parameters.keys())
    assert params == ["hub"]


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
    inside it would break headless usage (tests, future Web variant)."""
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


# ── D. UI ownership ──────────────────────────────────────────────────────────

def test_plugin_ui_files_in_plugin_dir():
    plugin_ui = [f for f in os.listdir("src/materials/news_video/ui")
                 if f.endswith(".py") and not f.startswith("__")]
    assert len(plugin_ui) >= 10, (
        f"expected ≥10 plugin-specific UI files, got {len(plugin_ui)}")


def test_src_ui_retains_only_generic():
    """src/ui/ keeps general-purpose Tk utilities; plugin-specific
    panes/dialogs should have moved to materials/news_video/ui/."""
    plugin_kw = ["source_", "news_context", "chapter_editor",
                 "subs_lang", "subtitle_analysis_preview",
                 "subtitles_dialogs", "subtitles_progress"]
    leaked: list[str] = []
    for f in os.listdir("src/ui"):
        if not f.endswith(".py") or f == "__init__.py":
            continue
        for kw in plugin_kw:
            if kw in f:
                leaked.append(f)
                break
    assert not leaked, f"plugin-specific UI leaked into src/ui/: {leaked}"


def test_sidebar_does_not_call_business_methods():
    """sidebar.py is a view + dispatcher; business invocations live in
    node_panes.py. Regression guard against accidental coupling."""
    with open("src/materials/news_video/sidebar.py", "r", encoding="utf-8") as f:
        src = f.read()
    biz_calls: list[str] = []
    for kw in ["run_asr", "run_translate", "ai_fill_context",
               "run_analysis", "import_subtitle", "commit_source"]:
        if re.search(rf"self\.model\.{kw}\(", src):
            biz_calls.append(kw)
    assert not biz_calls, f"sidebar calls business methods: {biz_calls}"


def test_node_panes_exists():
    assert os.path.isfile("src/materials/news_video/ui/node_panes.py")


# ── E. Multi-instance ────────────────────────────────────────────────────────

def test_hub_iterates_list_material_instances():
    with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
        src = f.read()
    assert "list_material_instances" in src


def test_paths_accept_explicit_instance_id():
    with open("src/materials/news_video/paths.py", "r", encoding="utf-8") as f:
        src = f.read()
    assert "instance_id: str | None = None" in src


def test_material_binding_module_exists():
    assert os.path.isfile("src/creations/material_binding.py")


# ── F. Hub invariants ────────────────────────────────────────────────────────

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


def test_hub_stripped_of_plugin_section_methods():
    """K.2 + slice R deleted these from Hub. Adding them back means the
    plugin is leaking back into Hub."""
    forbidden = ["_build_source_section",
                 "_build_news_context_section",
                 "_build_subtitles_section",
                 "_refresh_source_section",
                 "_refresh_subtitles_section",
                 "_refresh_news_context_section",
                 "_on_source_button", "_invoke_asr", "_invoke_translate",
                 "_subtitles_section_snapshot",
                 "_populate_analysis_rows"]
    with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
        src = f.read()
    leaked = [m for m in forbidden if f"def {m}" in src]
    assert not leaked, f"Hub regrew plugin-specific methods: {leaked}"


def test_hub_decoupled_from_plugin_internals():
    """Hub keeps the package import (for self-register side effect) +
    the paths helper, but should not reach for plugin internals like
    .ui.X. node_panes routing is the only legit entry point."""
    with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
        src = f.read()
    attr_refs = re.findall(r"materials\.news_video\.[a-zA-Z_]+", src)
    # Acceptable: one or two paths import lines. More signals
    # Hub leaking knowledge of plugin internals.
    assert len(attr_refs) <= 2, (
        f"Hub references materials.news_video.X {len(attr_refs)}x: {attr_refs}")
