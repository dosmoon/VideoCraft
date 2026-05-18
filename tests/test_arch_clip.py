"""Architecture compliance regression guard for creations/clip.

Step 1 of the clip refactor (material-via-Model) locks in: the clip
workbench must access upstream material data through a NewsVideoModel
instance, never via the materials.news_video.paths private helper.

Mirrors the equivalent guards in test_arch_news_desk.py.
"""

from __future__ import annotations

import os
import re


CLIP_TOOL_PATH = "src/creations/clip/clip_tool.py"
CLIP_DIR = "src/creations/clip"


def test_clip_tool_does_not_call_nv_paths():
    """The clip workbench accesses upstream material data through
    self.material_model. Direct _nv_paths.X calls are forbidden."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "_nv_paths." not in src, (
        "clip_tool must not call _nv_paths.*")


def test_clip_tool_does_not_import_nv_paths():
    """materials.news_video.paths is a private detail of the material
    plugin. Clip must not import it under any alias."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    bad = re.search(
        r"from\s+materials\.news_video\s+import\s+paths", src)
    assert bad is None, (
        "clip_tool must not import materials.news_video.paths")


def test_clip_tool_constructs_material_model():
    """ClipToolApp.__init__ must wire self.material_model =
    NewsVideoModel(...) — the single legitimate handle on upstream
    material data."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "self.material_model = NewsVideoModel(" in src, (
        "ClipToolApp must construct self.material_model")


def test_clip_tool_loads_instance_config():
    """ClipToolApp.__init__ must wire self.config = ClipInstanceConfig.load(...).
    All config.json access funnels through this owner."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "self.config = ClipInstanceConfig.load(" in src, (
        "ClipToolApp must construct self.config via ClipInstanceConfig.load")


def test_clip_tool_has_no_other_config_json_writers():
    """The only legitimate writer of config.json is self.config.save(...).
    No raw json.dump targeting 'config.json' may live in clip_tool."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # Catch the ad-hoc pattern: a json.dump in the same function that
    # opens/writes a path ending in config.json.
    bad_patterns = [
        r"json\.dump\([^)]*config\.json",     # direct dump path
        r"def _save_instance_config\b",        # ad-hoc helper resurrected
        r"def _load_instance_config\b",
    ]
    for pat in bad_patterns:
        assert not re.search(pat, src), (
            f"clip_tool.py has forbidden config.json writer pattern: {pat}")


def test_clip_subtree_has_single_config_writer():
    """Across creations/clip/, only config.py owns config.json IO.
    Other modules must not contain `json.dump(...config.json...)`
    patterns or define _save/_load_instance_config helpers."""
    violations: list[str] = []
    for fn in os.listdir(CLIP_DIR):
        if not fn.endswith(".py") or fn == "config.py" or fn.startswith("__"):
            continue
        p = os.path.join(CLIP_DIR, fn)
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        if re.search(r"json\.dump\([^)]*config\.json", src):
            violations.append(f"{fn}: ad-hoc json.dump of config.json")
        if re.search(r"def _save_instance_config\b|def _load_instance_config\b", src):
            violations.append(f"{fn}: defines forbidden config IO helper")
    assert not violations, (
        f"clip modules must route config.json IO through config.py only: "
        f"{violations}")


def test_clip_tool_uses_single_timeline_bridge():
    """Clip preview push must funnel through CompositionPreview.set_timeline.
    Legacy bridges (.set_cues / .set_cues_secondary / .set_clip_meta /
    .set_style) are retired — calling them is a regression."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    forbidden = (".set_cues(", ".set_cues_secondary(",
                  ".set_clip_meta(")
    bad = [pat for pat in forbidden if pat in src]
    assert not bad, (
        f"clip_tool must not call retired preview bridges: {bad}")


def test_composition_preview_has_no_legacy_cue_meta_methods():
    """The two methods that drove clip's old 5-bridge subtitle/clip-meta
    path are retired — set_timeline is now the single Python entry for
    those. (set_cues and set_style remain on the class: chapter_editor
    consumes them for its boundary-reference preview, where preview ≡
    render parity is not a concern.)"""
    from core.composition.preview import CompositionPreview
    for name in ("set_cues_secondary", "set_clip_meta"):
        assert not hasattr(CompositionPreview, name), (
            f"CompositionPreview still exposes retired method: {name}")


def test_clip_tool_uses_hotclips_repo():
    """Snapshot + lang listing live in candidates.HotclipsRepo. The
    workbench must delegate, not inline the filesystem logic."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "HotclipsRepo(" in src, "clip_tool must construct HotclipsRepo"
    forbidden_helpers = (
        "def _hotclips_snapshot_path",
        "def _srt_snapshot_path",
        "def _ensure_snapshot",
        "def _list_available_langs",
    )
    bad = [h for h in forbidden_helpers if h in src]
    assert not bad, (
        f"clip_tool still defines repo helpers (move to candidates.py): {bad}")


def test_clip_tool_uses_render_queue():
    """Batch rendering must funnel through RenderQueue. The workbench
    no longer owns a raw thread, _render_worker is retired, and
    cancellation goes through the queue's cancel()."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "RenderQueue(" in src, "clip_tool must construct RenderQueue"
    forbidden = (
        "def _render_worker",
        "threading.Thread(",
        "self._cancel_flag",
        "self._render_thread",
    )
    bad = [pat for pat in forbidden if pat in src]
    assert not bad, (
        f"clip_tool still owns raw threading state (move to "
        f"render_queue.py): {bad}")


def test_clip_tool_uses_detail_panel():
    """Per-clip detail UI lives in ClipDetailPanel. The workbench must
    construct it and must not redefine the migrated handlers."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "ClipDetailPanel(" in src, (
        "clip_tool must construct ClipDetailPanel")
    forbidden = (
        "def _build_clip_detail_panel",
        "def _show_detail",
        "def _on_time_entry_blur",
        "def _on_text_entry_blur",
        "def _on_nudge_start",
        "def _on_nudge_end",
        "def _on_clip_crop_changed",
        "def _on_reset_clip_crop",
        "def _on_restore_ai_text",
        "def _refresh_detail_dependents",
    )
    bad = [pat for pat in forbidden if pat in src]
    assert not bad, (
        f"clip_tool still defines detail-panel methods (move to "
        f"clip_editor.py): {bad}")


def test_clip_tool_uses_style_panel():
    """Style tab UI + form vars + preset menus live in StylePanel. The
    workbench must construct it and must not redefine the migrated
    methods."""
    with open(CLIP_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "StylePanel(" in src, "clip_tool must construct StylePanel"
    forbidden = (
        "def _build_tab_style",
        "def _build_style_form",
        "def _color_picker",
        "def _wire_traces",
        "def _populate_form_from_style",
        "def _read_form_into_style",
        "def _on_form_changed",
        "def _on_preset_applied",
        "def _on_preset_save_as",
        "def _on_preset_overwrite",
        "def _on_preset_delete",
        "def _on_ho_preset_applied",
        "def _refresh_preset_combos",
        "def _browse_watermark",
        "def _on_style_crop_changed",
        "def _on_apply_crop_to_all",
        "def _schedule_style_preview_refresh",
        "def _push_style_preview",
    )
    bad = [pat for pat in forbidden if pat in src]
    assert not bad, (
        f"clip_tool still defines style-panel methods (move to "
        f"style_panel.py): {bad}")
    # Form Tk vars must not be re-introduced on the workbench
    var_leaks = ("self._aspect_var", "self._sub1_enabled",
                  "self._wm_enabled", "self._ho_font",
                  "self._suspend_traces", "self._style_preview",
                  "self._lang_combo", "self._status_var")
    leaked = [v for v in var_leaks if v in src]
    assert not leaked, (
        f"clip_tool still holds style-form state (move to "
        f"style_panel.py): {leaked}")


def test_timeline_builder_retired():
    """Step 5.4 retires creations/clip/timeline_builder.py — the
    inline Element/Track construction is gone, replaced by
    composer.compile_for_candidate which drives compile_timeline()
    against component-spec adapters. Any resurrection is a regression."""
    assert not os.path.isfile(
        os.path.join(CLIP_DIR, "timeline_builder.py")), (
        "creations/clip/timeline_builder.py must stay deleted")
    for fn in os.listdir(CLIP_DIR):
        if not fn.endswith(".py") or fn.startswith("__"):
            continue
        p = os.path.join(CLIP_DIR, fn)
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        assert "build_clip_timeline" not in src, (
            f"{fn} still references retired build_clip_timeline")


def test_clip_subtree_does_not_call_nv_paths():
    """No module under creations/clip/ may reach into _nv_paths."""
    violations: list[str] = []
    for fn in os.listdir(CLIP_DIR):
        if not fn.endswith(".py") or fn.startswith("__"):
            continue
        p = os.path.join(CLIP_DIR, fn)
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        if re.search(r"from\s+materials\.news_video\s+import\s+paths",
                     src):
            violations.append(f"{fn}: imports materials.news_video.paths")
        if "_nv_paths." in src:
            violations.append(f"{fn}: calls _nv_paths.*")
    assert not violations, (
        f"clip modules must not import or call _nv_paths: {violations}")
