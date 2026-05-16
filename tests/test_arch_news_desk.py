"""Architecture compliance regression guard for creations/news_desk.

Asserts ADR-0003 (creation snapshot semantics), ADR-0004 (plugin
contract / file ownership), and ADR-0005 (material binding) invariants
that the news_desk creation is expected to maintain.

Some ADR-0003 "snapshot only" rules are behavioral (which code path
runs at render time vs import time) and aren't fully covered here —
those needs e2e tests with mock filesystems. The mechanical checks
below catch the common regressions.
"""

from __future__ import annotations

import inspect
import os
import re
import ast

import creations
import creations.news_desk  # noqa: F401  trigger registration
from creations import CreationType


NEWS_DESK_TOOL_PATH = "src/creations/news_desk/news_desk_tool.py"
NEWS_DESK_DIR = "src/creations/news_desk"


# ── A. Registration ──────────────────────────────────────────────────────────

def test_news_desk_self_registers():
    assert creations.get("news_desk") is not None


def test_news_desk_required_fields():
    ct = creations.get("news_desk")
    for f in ("type_name", "display_name_key", "tool_key",
              "default_basename", "single_instance",
              "description_zh", "description_en"):
        v = getattr(ct, f, None)
        # bool fields legitimately False; string fields must be non-empty
        if f == "single_instance":
            assert isinstance(v, bool), f"{f} not bool"
        else:
            assert v, f"{f} empty"


def test_news_desk_display_name_key_resolves_in_i18n():
    """Slice I rename: display_name_key MUST point to a 'creation.X' key."""
    ct = creations.get("news_desk")
    assert ct.display_name_key.startswith("creation."), (
        f"display_name_key not in 'creation.*' namespace: "
        f"{ct.display_name_key}")
    from i18n import tr
    rendered = tr(ct.display_name_key)
    # tr() falls back to key on miss; rendered != key means the i18n
    # entry exists in zh.json or en.json.
    assert rendered != ct.display_name_key, (
        f"i18n key {ct.display_name_key} not found in i18n files")


def test_news_desk_tool_key_matches_tool_map():
    """tool_key must reference an existing TOOL_MAP entry pointing at
    creations/news_desk/news_desk_tool.py with class NewsDeskApp."""
    with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
        hub_src = f.read()
    ct = creations.get("news_desk")
    pat = rf'"{re.escape(ct.tool_key)}":\s*\{{\s*"file":\s*"([^"]+)",\s*"class":\s*"([^"]+)"'
    m = re.search(pat, hub_src)
    assert m, f"TOOL_MAP entry for {ct.tool_key!r} not found"
    file_path, class_name = m.group(1), m.group(2)
    assert file_path == "creations/news_desk/news_desk_tool.py", (
        f"unexpected file: {file_path}")
    assert class_name == "NewsDeskApp"


def test_news_desk_register_idempotent():
    ct = creations.get("news_desk")
    before = len(creations.all_types())
    creations.register(ct)
    assert len(creations.all_types()) == before


# ── B. File ownership ────────────────────────────────────────────────────────

def test_news_desk_in_creations_dir():
    """ADR-0004 slice C moved news_desk to creations/. Guard against
    re-emergence in tools/."""
    assert os.path.isdir(NEWS_DESK_DIR)
    assert not os.path.exists("src/tools/news_desk"), (
        "news_desk regrew under src/tools/ — slice C migration regressed")


def test_news_desk_tool_module_exports_app_class():
    """Spec entry point: NewsDeskApp class in news_desk_tool.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "news_desk_tool", NEWS_DESK_TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "NewsDeskApp")


def test_news_desk_components_subpackage():
    """Component specs (chapter / subtitle / text_wm / image_wm)
    live under components/."""
    comp_dir = os.path.join(NEWS_DESK_DIR, "components")
    assert os.path.isdir(comp_dir)
    for name in ("chapter.py", "subtitle.py",
                 "text_watermark.py", "image_watermark.py"):
        assert os.path.isfile(os.path.join(comp_dir, name)), (
            f"missing component: {name}")


def test_news_desk_publish_renderer_exists():
    """publish.md template lives next to the workbench, not in core."""
    pub = os.path.join(NEWS_DESK_DIR, "publish.py")
    assert os.path.isfile(pub)
    with open(pub, "r", encoding="utf-8") as f:
        src = f.read()
    assert "def render_news_desk_publish" in src


def test_no_news_desk_specific_ui_leaked_outside():
    """News-desk-specific UI must live under news_desk/. Generic Tk
    helpers can remain in src/ui/."""
    leaked: list[str] = []
    for f in os.listdir("src/ui"):
        if not f.endswith(".py") or f.startswith("__"):
            continue
        if "news_desk" in f.lower() or "newsdesk" in f.lower():
            leaked.append(f)
    assert not leaked, f"leaked into src/ui/: {leaked}"


# ── C. Workbench contract ───────────────────────────────────────────────────

def test_news_desk_app_init_signature():
    """Hub.open_tool calls cls(master, project=..., instance_name=...)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "news_desk_tool", NEWS_DESK_TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sig = inspect.signature(mod.NewsDeskApp.__init__)
    params = list(sig.parameters.keys())
    assert params == ["self", "master", "project", "instance_name"], (
        f"got: {params}")


def test_news_desk_app_inherits_tool_base():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "news_desk_tool", NEWS_DESK_TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from tools.base import ToolBase
    assert issubclass(mod.NewsDeskApp, ToolBase)


# ── D. ADR-0005 material binding ────────────────────────────────────────────

def test_news_desk_app_init_calls_material_binding():
    """Slice Q: NewsDeskApp.__init__ MUST call material_binding.get_or_bind."""
    with open(NEWS_DESK_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # Find __init__ body
    tree = ast.parse(src)
    init_src: str | None = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.ClassDef) and node.name == "NewsDeskApp"):
            for sub in node.body:
                if (isinstance(sub, ast.FunctionDef)
                        and sub.name == "__init__"):
                    init_src = ast.unparse(sub)
                    break
    assert init_src is not None
    assert "material_binding" in init_src
    assert "get_or_bind" in init_src


def test_news_desk_app_stores_material_instance_id():
    with open(NEWS_DESK_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "self.material_instance_id" in src, (
        "NewsDeskApp doesn't store material_instance_id")


def test_nv_paths_calls_pass_material_instance_id_in_tool():
    """Every _nv_paths.X(self.project) MUST also pass
    self.material_instance_id. No silent fallback."""
    with open(NEWS_DESK_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    bare = re.findall(r"_nv_paths\.\w+\(self\.project\)(?!\s*,)", src)
    assert not bare, f"_nv_paths called without material_instance_id: {bare}"


def test_project_context_has_material_instance_id():
    """ADR-0005 slice Q added material_instance_id to ProjectContext."""
    from creations.news_desk.components import ProjectContext
    assert "material_instance_id" in ProjectContext.__dataclass_fields__


def test_nv_paths_calls_pass_material_instance_id_in_components():
    """Component code paths must propagate ctx.material_instance_id."""
    comp_dir = os.path.join(NEWS_DESK_DIR, "components")
    violations: list[str] = []
    for fn in os.listdir(comp_dir):
        if not fn.endswith(".py") or fn.startswith("__"):
            continue
        p = os.path.join(comp_dir, fn)
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        bare = re.findall(r"_nv_paths\.\w+\(ctx\.project\)(?!\s*,)", src)
        if bare:
            violations.append(f"{fn}: {bare}")
    assert not violations, (
        f"components call _nv_paths without ctx.material_instance_id: {violations}")


def test_ctx_constructors_pass_material_instance_id():
    """Each nd_components.ProjectContext(...) call must include
    material_instance_id=self.material_instance_id."""
    with open(NEWS_DESK_TOOL_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # Find all ProjectContext(...) constructor blocks and check.
    blocks = re.findall(
        r"nd_components\.ProjectContext\([^)]+\)", src, re.DOTALL)
    missing = [b for b in blocks if "material_instance_id" not in b]
    assert not missing, (
        f"ProjectContext constructors missing material_instance_id: "
        f"{len(missing)} of {len(blocks)}")


# ── E. ADR-0003 snapshot semantics (partial — behavioral) ───────────────────

def test_subtitle_component_snapshots_to_instance_dir():
    """subtitle.py copies the imported SRT into instance_dir/subtitles/,
    not just stores a reference to upstream."""
    with open(os.path.join(NEWS_DESK_DIR, "components", "subtitle.py"),
              "r", encoding="utf-8") as f:
        src = f.read()
    # Snapshot signal: copy/copyfile + ctx.instance_dir + "subtitles/"
    has_copy = re.search(r"shutil\.(copy|copyfile)", src)
    references_instance = "ctx.instance_dir" in src
    assert has_copy and references_instance, (
        "subtitle component doesn't appear to snapshot SRT into instance_dir")


def test_publish_writes_into_instance_dir():
    """publish.py renders publish.md content; the consumer (workbench)
    is responsible for writing it inside <instance_dir>/."""
    with open(os.path.join(NEWS_DESK_DIR, "publish.py"),
              "r", encoding="utf-8") as f:
        src = f.read()
    # Convention check: publish.py is a pure renderer (returns string),
    # no direct writes to source/ layer.
    bad = re.findall(r"_nv_paths\.\w+", src)
    assert not bad, f"publish.py references upstream paths: {bad}"


# ── F. Decoupling ────────────────────────────────────────────────────────────

def test_news_desk_does_not_import_other_creation_plugins():
    """news_desk MUST NOT import creations.clip / creations.bilingual_video.
    Each creation plugin is independent."""
    forbidden_imports = ["creations.clip", "creations.bilingual_video"]
    violations: list[str] = []
    for root, dirs, files in os.walk(NEWS_DESK_DIR):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            with open(p, "r", encoding="utf-8") as f:
                src = f.read()
            for imp in forbidden_imports:
                if re.search(rf"(^|\n)\s*(from|import)\s+{re.escape(imp)}", src):
                    violations.append(f"{p} → {imp}")
    assert not violations, f"cross-creation imports: {violations}"


def test_core_does_not_import_news_desk():
    """core/ MUST NOT know any creation plugin's name."""
    violations: list[str] = []
    for root, dirs, files in os.walk("src/core"):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.normpath(os.path.join(root, fn))
            with open(p, "r", encoding="utf-8") as f:
                src = f.read()
            if re.search(r"(^|\n)\s*(from|import)\s+creations\.news_desk", src):
                violations.append(p)
    assert not violations, f"core imports news_desk: {violations}"


def test_hub_does_not_hardcode_news_desk_outside_tool_map():
    """Hub references news_desk via TOOL_MAP (file path + class name)
    and via the package import for self-registration. It must not
    reach into news_desk internals."""
    with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
        src = f.read()
    # Acceptable: 'creations/news_desk/news_desk_tool.py' in TOOL_MAP,
    # 'import creations.news_desk' for registration side-effect.
    # Anything else (e.g. creations.news_desk.components.X) signals
    # Hub leaking knowledge.
    attr_refs = re.findall(r"creations\.news_desk\.[a-zA-Z_]+", src)
    assert not attr_refs, (
        f"Hub reaches into news_desk internals: {attr_refs}")
