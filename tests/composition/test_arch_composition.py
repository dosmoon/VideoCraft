"""Architecture guards for the new timeline scaffolding.

Engine files must stay free of UI (tkinter) and downstream (creations,
materials) imports — the engine is consumed by them, not the other way
around. ADR-0004 layering.
"""

from __future__ import annotations

import ast
import os


SRC = os.path.join("src", "core", "composition")


def _imported_modules(path: str) -> set[str]:
    """Top-level module names this file imports (covers `import X`,
    `from X import ...`, including relative imports' targets).
    """
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


FORBIDDEN = {"tkinter", "creations", "materials", "ui"}


def test_timeline_module_has_no_forbidden_imports():
    imports = _imported_modules(os.path.join(SRC, "timeline.py"))
    leaks = imports & FORBIDDEN
    assert not leaks, f"timeline.py imports {leaks}; engine must stay UI/downstream-free"


def test_compile_module_has_no_forbidden_imports():
    imports = _imported_modules(os.path.join(SRC, "compile.py"))
    leaks = imports & FORBIDDEN
    assert not leaks, f"compile.py imports {leaks}; engine must stay UI/downstream-free"


def test_primitives_registry_has_no_forbidden_imports():
    path = os.path.join(SRC, "primitives", "__init__.py")
    imports = _imported_modules(path)
    leaks = imports & FORBIDDEN
    assert not leaks, f"primitives/__init__.py imports {leaks}"


def test_compile_context_field_set_is_narrow():
    """Engine's CompileContext stays at 4 narrow data fields. UI hooks
    (seek_to, on_X, ...) belong in creation-side ProjectContext subclasses,
    not here. Guards Axis 7.1 lock.
    """
    from dataclasses import fields
    from core.composition.compile import CompileContext
    field_names = {f.name for f in fields(CompileContext)}
    expected = {"project", "material_model", "instance_dir", "duration"}
    assert field_names == expected, (
        f"CompileContext fields drifted: {field_names} != {expected}. "
        f"UI callbacks belong in creation-side subclasses.")
