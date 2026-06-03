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


# ── C. Decoupling ────────────────────────────────────────────────────────────

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
