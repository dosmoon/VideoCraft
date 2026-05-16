"""Material picker UI (ADR-0005).

This module is a pure UI helper — it shows a modal listbox of every
material instance in the project and returns the user's choice. It
does NOT read or write any config file. Persistence is the host
creation's responsibility (each creation has its own InstanceConfig
schema that owns bound_material as one field among many).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from i18n import tr


class _MaterialPickerDialog:
    def __init__(self, parent: tk.Misc, project) -> None:
        self.project = project
        self.result: Optional[tuple[str, str]] = None

        self.win = tk.Toplevel(parent)
        self.win.title(tr("creation.bind.dialog.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()
        self._center_over(parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("creation.bind.dialog.heading"),
                  font=("Microsoft YaHei UI", 13, "bold")
                  ).pack(anchor="w", pady=(0, 6))
        ttk.Label(body, text=tr("creation.bind.dialog.hint"),
                  font=("Microsoft YaHei UI", 9), foreground="#666",
                  wraplength=440, justify="left",
                  ).pack(anchor="w", pady=(0, 10))

        # Build a flat list of (type, instance) entries across all
        # material types. For the current 单素材类型 era this is just
        # news_video instances; future material types appear here too.
        import materials
        entries: list[tuple[str, str, str]] = []  # (type, instance, display_label)
        for mt in materials.all_types():
            inst_list = self.project.list_material_instances(mt.type_name)
            for inst in inst_list:
                disp = (tr(mt.display_name_key) if mt.display_name_key
                        else mt.type_name)
                label = f"{mt.icon or '📦'}  {inst}  ·  {disp}"
                entries.append((mt.type_name, inst, label))

        self._entries = entries

        if not entries:
            ttk.Label(
                body, text=tr("creation.bind.dialog.no_materials"),
                font=("Microsoft YaHei UI", 10), foreground="#c44",
                wraplength=440, justify="left",
            ).pack(anchor="w", pady=(0, 10))
            btns = ttk.Frame(body)
            btns.pack(fill="x", pady=(10, 0))
            ttk.Button(btns, text=tr("dialog.common.btn_cancel"),
                       command=self._on_cancel).pack(side="right")
            return

        # Listbox of instances.
        list_frame = ttk.Frame(body)
        list_frame.pack(fill="x", pady=(0, 10))
        self._listbox = tk.Listbox(
            list_frame, height=min(8, len(entries)),
            font=("Microsoft YaHei UI", 10), activestyle="dotbox",
            selectmode="browse",
        )
        for _, _, label in entries:
            self._listbox.insert("end", label)
        self._listbox.selection_set(0)
        self._listbox.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(list_frame, orient="vertical",
                              command=self._listbox.yview)
        vsb.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=vsb.set)
        self._listbox.bind("<Double-Button-1>", lambda _e: self._on_ok())

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"),
                   command=self._on_cancel).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("creation.bind.dialog.btn_bind"),
                   command=self._on_ok).pack(side="right")

    def _on_ok(self) -> None:
        if not self._entries:
            return
        sel = self._listbox.curselection()
        if not sel:
            return
        type_name, inst_name, _ = self._entries[sel[0]]
        self.result = (type_name, inst_name)
        self.win.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.win.destroy()

    def _center_over(self, parent: tk.Misc) -> None:
        from ui.dialog_utils import center_dialog_on_parent
        center_dialog_on_parent(self.win, parent)

    def run(self) -> Optional[tuple[str, str]]:
        self.win.wait_window()
        return self.result


def show_material_picker(parent: tk.Misc, project) -> Optional[tuple[str, str]]:
    """Modal picker over all material instances. Returns
    (type_name, instance_name) or None on cancel / no materials.

    Pure UI — does NOT touch any config file. The caller persists the
    selection into its own creation-specific InstanceConfig.
    """
    return _MaterialPickerDialog(parent, project).run()
