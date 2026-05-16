"""Creation ↔ material binding (ADR-0005 slice Q).

Each creation instance declares which material instance it consumes
via `bound_material: {type_name, instance_name, bound_at}` inside its
config.json. The picker is shown the first time a workbench opens for
an unbound creation; the binding is persisted so subsequent opens go
straight to work.

Per ADR-0003, the creation still snapshots material data into its own
instance dir for actual render/export. `bound_material` is the
audit pointer + the "where to re-import from" handle, not a runtime
link.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timezone
from typing import Optional

from i18n import tr


# ── Config-level helpers ─────────────────────────────────────────────────────

def _read_config(config_path: str) -> dict:
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_config(config_path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path)


def read_bound_material(config_path: str) -> Optional[dict]:
    """Returns {'type_name', 'instance_name', 'bound_at'} or None."""
    cfg = _read_config(config_path)
    bm = cfg.get("bound_material")
    if isinstance(bm, dict) and bm.get("type_name") and bm.get("instance_name"):
        return bm
    return None


def write_bound_material(config_path: str, type_name: str,
                          instance_name: str) -> None:
    """Persist the binding. Merges into existing config (preserves other fields)."""
    cfg = _read_config(config_path)
    cfg["bound_material"] = {
        "type_name": type_name,
        "instance_name": instance_name,
        "bound_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_config(config_path, cfg)


# ── Picker dialog ────────────────────────────────────────────────────────────

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
    """Modal: show picker over all material instances. Returns
    (type_name, instance_name) or None on cancel / no available materials."""
    return _MaterialPickerDialog(parent, project).run()


# ── Orchestration ────────────────────────────────────────────────────────────

def get_or_bind(parent: tk.Misc, project, config_path: str
                 ) -> Optional[tuple[str, str]]:
    """If config has bound_material, return (type, instance). Otherwise
    show picker, persist, return result. None on cancel."""
    bound = read_bound_material(config_path)
    if bound is not None:
        return (bound["type_name"], bound["instance_name"])
    res = show_material_picker(parent, project)
    if res is None:
        return None
    write_bound_material(config_path, res[0], res[1])
    return res
