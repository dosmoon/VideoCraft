"""Architecture compliance regression guard for creations/news_desk.

Asserts the ADR-0003 (snapshot semantics) / ADR-0004 (plugin contract /
decoupling) / ADR-0005 (material binding) invariants that survive the Tk-app
retirement. The Tk workbench (news_desk_tool.py + components/* specs + the
publish renderer) was retired when the new-arch Electron workbench took over
(see desktop/src/renderer/workbenches/news_desk/); news_desk is now a headless
sidecar plugin. The old Tk-tool/component-spec/publish checks went with it —
the new-arch component + config + provider surface is covered by
tests/core_rpc/test_creation_news_desk.py.
"""

from __future__ import annotations

import os
import re

import creations
import creations.news_desk  # noqa: F401  trigger registration


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
    """display_name_key MUST point to a resolvable 'creation.X' key."""
    ct = creations.get("news_desk")
    assert ct.display_name_key.startswith("creation."), (
        f"display_name_key not in 'creation.*' namespace: "
        f"{ct.display_name_key}")
    from i18n import tr
    rendered = tr(ct.display_name_key)
    # tr() falls back to key on miss; rendered != key means the entry exists.
    assert rendered != ct.display_name_key, (
        f"i18n key {ct.display_name_key} not found in i18n files")


def test_news_desk_register_idempotent():
    ct = creations.get("news_desk")
    before = len(creations.all_types())
    creations.register(ct)
    assert len(creations.all_types()) == before


def test_news_desk_wires_new_arch_providers():
    """The sidecar resolves preview/render/import providers + the single config
    owner generically (ADR-0004). Wiring them on the CreationType is what makes
    the whole RPC surface work without the base layer naming news_desk."""
    ct = creations.get("news_desk")
    assert ct.config_owner_cls is not None
    assert ct.preview_provider is not None
    assert ct.render_provider is not None
    assert ct.import_provider is not None


# ── B. File ownership / headlessness ─────────────────────────────────────────

def test_news_desk_in_creations_dir():
    """ADR-0004 slice C moved news_desk to creations/. Guard against
    re-emergence in tools/."""
    assert os.path.isdir(NEWS_DESK_DIR)
    assert not os.path.exists("src/tools/news_desk"), (
        "news_desk regrew under src/tools/ — slice C migration regressed")


def test_news_desk_is_headless_no_tkinter():
    """Post-Tk-retirement invariant: the sidecar plugin must import zero
    tkinter — all UI lives in the new-arch Electron renderer (desktop/)."""
    violations: list[str] = []
    for root, _dirs, files in os.walk(NEWS_DESK_DIR):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            with open(p, "r", encoding="utf-8") as f:
                src = f.read()
            if re.search(r"(^|\n)\s*(from\s+tkinter|import\s+tkinter)", src):
                violations.append(p)
    assert not violations, f"news_desk still imports tkinter: {violations}"


def test_no_news_desk_specific_ui_leaked_outside():
    """News-desk-specific UI must not live under src/ui/."""
    leaked: list[str] = []
    for f in os.listdir("src/ui"):
        if not f.endswith(".py") or f.startswith("__"):
            continue
        if "news_desk" in f.lower() or "newsdesk" in f.lower():
            leaked.append(f)
    assert not leaked, f"leaked into src/ui/: {leaked}"


# ── C. ADR-0005 material binding ─────────────────────────────────────────────

def test_material_binding_module_is_picker_only():
    """material_binding.py exposes ONLY show_material_picker — no config IO."""
    import creations.material_binding as mb
    publicish = [n for n in dir(mb)
                 if not n.startswith("_") and callable(getattr(mb, n))]
    forbidden = {"read_bound_material", "write_bound_material", "get_or_bind"}
    leaked = forbidden & set(publicish)
    assert not leaked, f"material_binding leaks config-IO API: {leaked}"


# ── D. ADR-0003 snapshot semantics (import path) ─────────────────────────────

def test_imports_snapshot_subtitle_into_instance_dir():
    """imports.py copies the imported SRT into <instance_dir>/, not a reference
    to upstream — the snapshot decision the Tk subtitle spec used to make."""
    with open(os.path.join(NEWS_DESK_DIR, "imports.py"),
              "r", encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"shutil\.(copy|copyfile)", src), (
        "imports.py doesn't snapshot the SRT (no shutil.copy*)")
    assert "inst_dir" in src


# ── E. Decoupling ────────────────────────────────────────────────────────────

def test_news_desk_does_not_import_other_creation_plugins():
    """news_desk MUST NOT import other creation plugins. Each is independent."""
    violations: list[str] = []
    for root, _dirs, files in os.walk(NEWS_DESK_DIR):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            with open(p, "r", encoding="utf-8") as f:
                src = f.read()
            if re.search(r"(^|\n)\s*(from|import)\s+creations\.clip", src):
                violations.append(f"{p} → creations.clip")
    assert not violations, f"cross-creation imports: {violations}"


def test_core_does_not_import_news_desk():
    """core/ MUST NOT know any creation plugin's name."""
    violations: list[str] = []
    for root, _dirs, files in os.walk("src/core"):
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


def test_hub_does_not_reach_into_news_desk_internals():
    """The Tk hub retired news_desk; it must not reach into news_desk internals
    (creations.news_desk.X attribute access)."""
    with open("src/VideoCraftHub.py", "r", encoding="utf-8") as f:
        src = f.read()
    attr_refs = re.findall(r"creations\.news_desk\.[a-zA-Z_]+", src)
    assert not attr_refs, (
        f"Hub reaches into news_desk internals: {attr_refs}")
