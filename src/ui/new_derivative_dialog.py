"""New Derivative dialogs (P3).

Two entry points:

  show_type_picker(parent, project) -> (type_name, instance_name) | None
    Full selection dialog: pick a derivative type AND name the instance.
    Used by the Sidebar [新建派生] button when the user hasn't decided
    which type yet.

  show_instance_namer(parent, project, type_name) -> instance_name | None
    Just ask for an instance name; type is already chosen. Used by the
    「创作」 menu (each menu item targets one type). Wired in P4/P5
    when the workbenches start using the new model.

Both dialogs validate name uniqueness inside <project>/derivatives/<type>/
before returning so the caller (Sidebar / menu handler) can safely
hand the name straight to Project.create_derivative_instance.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Tuple

from project import Project
import creations
from i18n import tr


def show_type_picker(
    parent: tk.Misc,
    project: Project,
) -> Optional[Tuple[str, str]]:
    """Full dialog: type radio + instance name. Returns (type, name) or None."""
    return _TypePickerDialog(parent, project).run()


def show_instance_namer(
    parent: tk.Misc,
    project: Project,
    type_name: str,
) -> Optional[str]:
    """Type-fixed dialog. Returns instance_name or None."""
    return _InstanceNamerDialog(parent, project, type_name).run()


# ── Type picker (full selection) ──────────────────────────────────────────────

class _TypePickerDialog:
    def __init__(self, parent: tk.Misc, project: Project) -> None:
        self.project = project
        self._result: Optional[Tuple[str, str]] = None

        self.win = tk.Toplevel(parent)
        self.win.title(tr("dialog.new_derivative.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # State
        types = creations.all_types()
        default_type = types[0].type_name if types else ""
        self._type_var = tk.StringVar(value=default_type)
        self._name_var = tk.StringVar()
        self._error_var = tk.StringVar()

        self._build_ui()
        self._auto_name()  # populate default name for the initial type
        self._center_over(parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("dialog.new_derivative.heading"),
                  font=("Microsoft YaHei UI", 13, "bold")
                  ).pack(anchor="w", pady=(0, 10))

        # Type radios with descriptions
        types_box = ttk.LabelFrame(body, text=tr("dialog.new_derivative.section_type"), padding=10)
        types_box.pack(fill="x", pady=(0, 12))
        for t in creations.all_types():
            row = ttk.Frame(types_box)
            row.pack(fill="x", pady=4)
            rb = ttk.Radiobutton(
                row, text=creations.display_name(t.type_name),
                value=t.type_name, variable=self._type_var,
                command=self._auto_name,
            )
            rb.pack(side="left")
            ttk.Label(
                row, text=f"   {t.description_zh}",
                font=("Microsoft YaHei UI", 9), foreground="#888",
            ).pack(side="left")

        # Instance name + preview path
        name_box = ttk.Frame(body)
        name_box.pack(fill="x", pady=(0, 4))
        ttk.Label(name_box, text=tr("dialog.new_derivative.label_instance"), width=8, anchor="e"
                  ).pack(side="left", padx=(0, 6))
        ttk.Entry(name_box, textvariable=self._name_var, width=36
                  ).pack(side="left", fill="x", expand=True)

        self._path_preview = ttk.Label(
            body, text="", font=("Microsoft YaHei UI", 8),
            foreground="#888",
        )
        self._path_preview.pack(anchor="w", padx=(72, 0))

        # Refresh path preview when name or type changes.
        self._name_var.trace_add("write", lambda *_: self._update_preview())
        self._type_var.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

        # Inline error
        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(14, 6))
        ttk.Label(body, textvariable=self._error_var,
                  foreground="#c00", font=("Microsoft YaHei UI", 9),
                  wraplength=460
                  ).pack(anchor="w")

        # Buttons
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.new_derivative.btn_create_open"), command=self._on_create
                   ).pack(side="right")

    def _auto_name(self) -> None:
        """Re-suggest instance name when the type changes (if user hasn't
        typed something custom yet)."""
        type_name = self._type_var.get()
        existing = self.project.list_derivative_instances(type_name)
        suggested = creations.suggest_instance_name(type_name, existing)
        # Only overwrite if the field is empty or contains a prior auto suggestion.
        cur = self._name_var.get().strip()
        if not cur or cur in _all_possible_auto_names(type_name, existing):
            self._name_var.set(suggested)

    def _update_preview(self) -> None:
        type_name = self._type_var.get()
        inst = self._name_var.get().strip()
        if not inst:
            self._path_preview.config(text="")
            return
        self._path_preview.config(
            text=tr("dialog.new_derivative.path_preview", type=type_name, instance=inst)
        )

    def _on_create(self) -> None:
        type_name = self._type_var.get()
        inst = self._name_var.get().strip()
        err = _validate_instance_name(self.project, type_name, inst)
        if err:
            self._error_var.set(err)
            return
        self._result = (type_name, inst)
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.win.destroy()

    def _center_over(self, parent: tk.Misc) -> None:
        from ui.dialog_utils import center_dialog_on_parent
        center_dialog_on_parent(self.win, parent)

    def run(self) -> Optional[Tuple[str, str]]:
        self.win.wait_window()
        return self._result


# ── Instance namer (type already chosen) ──────────────────────────────────────

class _InstanceNamerDialog:
    def __init__(self, parent: tk.Misc, project: Project, type_name: str) -> None:
        self.project = project
        self.type_name = type_name
        self._result: Optional[str] = None

        self.win = tk.Toplevel(parent)
        title = tr("dialog.new_derivative.title_typed", type=creations.display_name(type_name))
        self.win.title(title)
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        existing = project.list_derivative_instances(type_name)
        suggested = creations.suggest_instance_name(type_name, existing)
        self._name_var = tk.StringVar(value=suggested)
        self._error_var = tk.StringVar()

        self._build_ui(title)
        self._update_preview()
        self._center_over(parent)

    def _build_ui(self, title: str) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=title,
                  font=("Microsoft YaHei UI", 12, "bold")
                  ).pack(anchor="w", pady=(0, 12))

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Label(row, text=tr("dialog.new_derivative.label_instance"), width=8, anchor="e"
                  ).pack(side="left", padx=(0, 6))
        ttk.Entry(row, textvariable=self._name_var, width=36
                  ).pack(side="left", fill="x", expand=True)

        self._path_preview = ttk.Label(
            body, text="", font=("Microsoft YaHei UI", 8), foreground="#888",
        )
        self._path_preview.pack(anchor="w", padx=(72, 0))
        self._name_var.trace_add("write", lambda *_: self._update_preview())

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(14, 6))
        ttk.Label(body, textvariable=self._error_var,
                  foreground="#c00", font=("Microsoft YaHei UI", 9),
                  wraplength=440
                  ).pack(anchor="w")

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.new_derivative.btn_create_open"), command=self._on_create
                   ).pack(side="right")

    def _update_preview(self) -> None:
        inst = self._name_var.get().strip()
        self._path_preview.config(
            text=tr("dialog.new_derivative.path_preview", type=self.type_name, instance=inst) if inst else ""
        )

    def _on_create(self) -> None:
        inst = self._name_var.get().strip()
        err = _validate_instance_name(self.project, self.type_name, inst)
        if err:
            self._error_var.set(err)
            return
        self._result = inst
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.win.destroy()

    def _center_over(self, parent: tk.Misc) -> None:
        from ui.dialog_utils import center_dialog_on_parent
        center_dialog_on_parent(self.win, parent)

    def run(self) -> Optional[str]:
        self.win.wait_window()
        return self._result


# ── Shared helpers ────────────────────────────────────────────────────────────

def _validate_instance_name(project: Project, type_name: str, name: str) -> str:
    """Return human-readable error string, or empty string when OK."""
    if not name:
        return tr("dialog.new_derivative.err_empty_name")
    if name != name.strip():
        return tr("dialog.new_derivative.err_name_whitespace")
    if any(c in name for c in r'\/:*?"<>|'):
        return tr("dialog.new_derivative.err_illegal_chars")
    if name.startswith("."):
        return tr("dialog.new_derivative.err_leading_dot")
    if len(name) > 64:
        return tr("dialog.new_derivative.err_name_too_long")
    existing = project.list_derivative_instances(type_name)
    if name in existing:
        return tr("dialog.new_derivative.err_name_exists", name=name)
    return ""


def _all_possible_auto_names(type_name: str, existing: list[str]) -> set[str]:
    """Names this auto-suggester might have produced in the past, used to
    decide whether to overwrite the field when the user changes type.
    Cheap superset — generates up to 32 candidates."""
    out: set[str] = set()
    t = creations.get(type_name)
    if t is None:
        for i in range(1, 32):
            out.add(f"v{i}")
        return out
    if t.single_instance:
        out.add("default")
        for i in range(1, 32):
            out.add(f"v{i}")
    else:
        for i in range(1, 32):
            out.add(f"{t.default_basename}-{i}")
    return out
