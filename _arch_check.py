"""Architecture compliance check for materials/news_video plugin."""
import sys
import os
import re
import inspect

sys.path.insert(0, "src")

results = []


def check(label, cond, detail=""):
    mark = "OK " if cond else "FAIL"
    results.append((mark, label, detail))


# A. Plugin 契约
import materials.news_video
import materials

mt = materials.get("news_video")
check("A1 self-register via materials.register()", mt is not None,
      "materials.get('news_video') not None")

required = ["type_name", "display_name_key", "icon",
            "description_zh", "description_en",
            "sidebar_renderer", "create_handler", "instance_factory"]
missing = [f for f in required if getattr(mt, f, None) in (None, "")
           and f not in ("description_zh", "description_en")]
check("A2 required MaterialType fields filled", not missing,
      f"missing: {missing}" if missing else "all set")

params = list(inspect.signature(mt.sidebar_renderer).parameters.keys())
check("A3 sidebar_renderer(parent, hub, instance_id)",
      params == ["parent", "hub", "instance_id"], f"got: {params}")

params = list(inspect.signature(mt.create_handler).parameters.keys())
check("A4 create_handler(hub)", params == ["hub"], f"got: {params}")

params = list(inspect.signature(mt.instance_factory).parameters.keys())
check("A5 instance_factory(project, instance_id)",
      params == ["project", "instance_id"], f"got: {params}")

from materials import MaterialType
check("A6 has_instance field retired",
      "has_instance" not in MaterialType.__dataclass_fields__,
      "")

# B. Data ownership
from materials.news_video.schema import SourceContext
check("B1 SourceContext schema in plugin", True,
      f"{len(SourceContext.__dataclass_fields__)} fields")

from materials.news_video import paths as _nv_paths
check("B2 path resolver in plugin",
      hasattr(_nv_paths, "source_dir"), "")

from materials.news_video.schema import (
    read_basic_info, write_basic_info, read_context, write_context)
check("B3 schema IO in plugin", True, "")

from materials.news_video import ai_fill
check("B4 AI fill in plugin", hasattr(ai_fill, "extract"), "")

core_imports_plugin = []
for root, dirs, files in os.walk("src/core"):
    if "__pycache__" in root:
        continue
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(root, fn)
        with open(p, "r", encoding="utf-8") as f:
            c = f.read()
        if re.search(r"(^|\n)\s*(from|import)\s+materials\.news_video", c):
            core_imports_plugin.append(os.path.relpath(p))
# Acceptable known warts (both must have TODO(ADR-0005) markers):
#   - core/subtitle_pipeline.py (needs run_asr/run_translate parameterization)
#   - core/subtitle_analysis_runners.py (needs combined_prompt_block injection)
KNOWN_WART_FILES = {
    os.path.normpath("src/core/subtitle_pipeline.py"),
    os.path.normpath("src/core/subtitle_analysis_runners.py"),
}
unknown_violations = [p for p in core_imports_plugin
                       if p not in KNOWN_WART_FILES]
check("B5 core/ plugin imports limited to known TODO warts",
      not unknown_violations,
      f"unexpected: {unknown_violations}" if unknown_violations
      else f"{len(core_imports_plugin)} known warts")

# C. NewsVideoModel
from materials.news_video.model import NewsVideoModel

params = list(inspect.signature(NewsVideoModel.__init__).parameters.keys())
check("C1 NewsVideoModel(project, instance_id=None)",
      params == ["self", "project", "instance_id"], f"got: {params}")

with open("src/materials/news_video/model.py", "r", encoding="utf-8") as f:
    model_src = f.read()
has_tk = re.search(r"\bimport tkinter\b|\bfrom tkinter\b", model_src) is not None
check("C2 NewsVideoModel is zero-Tk", not has_tk, "")

required_props = ["instance_dir", "source_dir", "subtitles_dir",
                  "source_video_path", "source_meta_path"]
missing_props = [p for p in required_props if not hasattr(NewsVideoModel, p)]
check("C3 path properties present", not missing_props,
      f"missing: {missing_props}" if missing_props else "all present")

check("C4 slot_readiness method",
      callable(getattr(NewsVideoModel, "slot_readiness", None)), "")
check("C5 get_artifact(key) method",
      callable(getattr(NewsVideoModel, "get_artifact", None)), "")
check("C6 subscribe + _notify",
      callable(getattr(NewsVideoModel, "subscribe", None))
      and callable(getattr(NewsVideoModel, "_notify", None)), "")

biz_methods = ["commit_source", "read_basic_info", "write_basic_info",
               "read_context", "write_context", "ai_fill_context",
               "run_asr", "run_translate", "import_subtitle",
               "quick_fix_subtitle", "run_analysis", "check_subtitle",
               "list_subtitle_languages", "list_analysis_artifacts"]
missing_biz = [m for m in biz_methods if not hasattr(NewsVideoModel, m)]
check("C7 business methods complete", not missing_biz,
      f"missing: {missing_biz}" if missing_biz else "all present")

write_methods = ["commit_source", "write_basic_info", "write_context",
                 "ai_fill_context", "run_asr", "run_translate",
                 "import_subtitle", "quick_fix_subtitle", "run_analysis"]
no_notify = []
for m in write_methods:
    pat = re.compile(rf"def {m}\b.*?(?=\n    def |\nclass |\Z)", re.DOTALL)
    match = pat.search(model_src)
    if match and "_notify(" not in match.group(0):
        no_notify.append(m)
check("C8 write methods call _notify",
      not no_notify, f"missing: {no_notify}" if no_notify else "all notify")

# D. UI ownership
plugin_ui = [f for f in os.listdir("src/materials/news_video/ui")
              if f.endswith(".py") and not f.startswith("__")]
check("D1 plugin-specific UI in materials/news_video/ui/",
      len(plugin_ui) >= 10, f"{len(plugin_ui)} files")

generic_ui = os.listdir("src/ui")
plugin_specific_kw = ["source_", "news_context", "chapter_editor",
                       "subs_lang", "subtitle_analysis_preview",
                       "subtitles_dialogs", "subtitles_progress"]
leaked = []
for f in generic_ui:
    if not f.endswith(".py"):
        continue
    if f in ("__init__.py",):
        continue
    for kw in plugin_specific_kw:
        if kw in f:
            leaked.append(f)
            break
check("D2 src/ui/ retains generic only",
      not leaked, f"leaked: {leaked}" if leaked else "")

with open("src/materials/news_video/sidebar.py", "r", encoding="utf-8") as f:
    sidebar_src = f.read()
biz_in_sidebar = []
for kw in ["run_asr", "run_translate", "ai_fill_context", "run_analysis",
           "import_subtitle", "commit_source"]:
    if re.search(rf"self\.model\.{kw}\(", sidebar_src):
        biz_in_sidebar.append(kw)
check("D3 sidebar does not call business methods directly",
      not biz_in_sidebar,
      f"calls: {biz_in_sidebar}" if biz_in_sidebar else "")

check("D4 node_panes.py exists",
      os.path.isfile("src/materials/news_video/ui/node_panes.py"), "")

sidebar_funcs = re.findall(r"def (\w+)", sidebar_src)
biz_funcs = [f for f in sidebar_funcs
             if any(kw in f.lower()
                    for kw in ("invoke", "action", "asr", "translate",
                               "analysis_menu", "quick_fix"))]
check("D5 sidebar has no action/invoke methods",
      not biz_funcs,
      f"found: {biz_funcs}" if biz_funcs else "")

# E. Multi-instance
with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
    hub_src = f.read()
check("E1 Hub iterates list_material_instances",
      "list_material_instances" in hub_src, "")
check("E2 sidebar render(parent, hub, instance_id)",
      True, "verified above (A3)")
check("E3 bound_material binding module exists",
      os.path.isfile("src/creations/material_binding.py"), "")

with open("src/materials/news_video/paths.py", "r", encoding="utf-8") as f:
    paths_src = f.read()
check("E4 paths.X accepts instance_id explicitly",
      "instance_id: str | None = None" in paths_src, "")

# F. Invariants
core_tk = []
for root, dirs, files in os.walk("src/core"):
    if "__pycache__" in root:
        continue
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(root, fn)
        with open(p, "r", encoding="utf-8") as f:
            c = f.read()
        if re.search(r"\bimport tkinter\b|\bfrom tkinter\b", c):
            core_tk.append(os.path.relpath(p))
check("F1 core/ zero Tk", not core_tk,
      f"violations: {core_tk}" if core_tk else "")

check("F2 core/ plugin imports limited to known TODO warts (2 allowed)",
      not unknown_violations,
      f"count: {len(core_imports_plugin)} known warts" if not unknown_violations
      else f"unexpected: {unknown_violations}")

forbidden = ["_build_source_section",
             "_build_news_context_section",
             "_build_subtitles_section",
             "_refresh_source_section",
             "_refresh_subtitles_section",
             "_refresh_news_context_section",
             "_on_source_button", "_invoke_asr", "_invoke_translate",
             "_subtitles_section_snapshot",
             "_populate_analysis_rows"]
hub_violations = [m for m in forbidden if f"def {m}" in hub_src]
check("F3 Hub stripped of news_video section/handler methods",
      not hub_violations,
      f"violations: {hub_violations}" if hub_violations else "")

hub_news_video_attr = len(re.findall(r"materials\.news_video\.[a-zA-Z_]+",
                                        hub_src))
check("F4 Hub decoupled from materials.news_video internals",
      hub_news_video_attr <= 2,
      f"attribute accesses: {hub_news_video_attr}")

# Output
print()
print(f"{'#':<3}  {'Mark':<5}  Detail")
print("-" * 90)
for i, (mark, label, detail) in enumerate(results, 1):
    suffix = f"  -- {detail}" if detail else ""
    print(f"{i:<3}  {mark:<5}  {label}{suffix}")
ok = sum(1 for m, _, _ in results if m == "OK ")
fail = sum(1 for m, _, _ in results if m == "FAIL")
print()
print(f"Total: {ok}/{len(results)} OK; {fail} FAIL")
