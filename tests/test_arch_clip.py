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
    """CompositionPreview must not expose set_cues / set_cues_secondary /
    set_clip_meta — set_timeline is the single Python entry for these.
    (set_style is intentionally kept; chapter_editor consumes it for the
    style-only preview surface.)"""
    from core.composition.preview import CompositionPreview
    for name in ("set_cues", "set_cues_secondary", "set_clip_meta"):
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
