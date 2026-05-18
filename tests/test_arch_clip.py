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
