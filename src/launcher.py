"""
launcher.py - VideoCraft Project Launcher (separate window).

Pattern: Unity Hub / UE Launcher / IntelliJ Welcome — the launcher is a
standalone Tk window that runs before the main Hub. User picks (new /
open / recent) -> launcher destroys itself -> main returns the selected
Project to the caller, which then constructs the Hub.

P1 scope:
- Launcher window UI + recent-project list + open-folder dialog
- New-project entry is a MINIMAL placeholder (just name + parent dir);
  the full "paste link / pick local file / time range / disclaimer"
  dialog comes in P2. The placeholder is sufficient to verify the
  launcher → hub loop end-to-end during P1.

Returns a Project from run_launcher(), or None if the user closed the
window (= quit the app).
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from project import Project, get_recent_projects, add_recent_project
from ui.new_project_dialog import show_new_project_dialog
from i18n import tr
from materials.news_video import paths as _nv_paths


# ── Visual constants ──────────────────────────────────────────────────────────

WIN_W, WIN_H = 560, 460
BG = "#f5f5f5"
ACCENT = "#0078d4"
TEXT_DARK = "#222"
TEXT_MUTED = "#888"


class _LauncherWindow:
    """One-shot launcher window. Use run_launcher() instead of this directly."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("VideoCraft")
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        self._selected_project: Project | None = None

        self._set_icon()
        self._build_ui()

        # X button = quit (no project returned)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Center on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - WIN_W) // 2
        y = (self.root.winfo_screenheight() - WIN_H) // 2
        self.root.geometry(f"+{x}+{y}")

    def _set_icon(self) -> None:
        try:
            from PIL import Image
            import base64, io
            _src = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(_src, "..", "Logo", "logo.png")
            img = Image.open(logo_path).resize((64, 64), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self._icon = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def _build_ui(self) -> None:
        # Header
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(24, 8))
        tk.Label(header, text="VideoCraft", font=("Microsoft YaHei UI", 18, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(header, text=tr("launcher.tagline"), font=("Microsoft YaHei UI", 10),
                 bg=BG, fg=TEXT_MUTED).pack(anchor="w", pady=(2, 0))

        # Primary actions
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="x", padx=24, pady=(16, 8))
        tk.Button(actions, text=tr("launcher.btn_new"), font=("Microsoft YaHei UI", 11),
                  command=self._on_new_project,
                  bg=ACCENT, fg="white", relief="flat", padx=10, pady=8,
                  cursor="hand2", activebackground="#005ea2"
                  ).pack(fill="x", pady=(0, 6))
        tk.Button(actions, text=tr("launcher.btn_open"), font=("Microsoft YaHei UI", 11),
                  command=self._on_open_existing,
                  bg="#e0e0e0", fg=TEXT_DARK, relief="flat", padx=10, pady=8,
                  cursor="hand2", activebackground="#d0d0d0"
                  ).pack(fill="x")

        # Recent projects
        tk.Label(self.root, text=tr("launcher.recent_projects"), font=("Microsoft YaHei UI", 10, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w", padx=24, pady=(20, 4))

        list_frame = tk.Frame(self.root, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        vsb = ttk.Scrollbar(list_frame, orient="vertical")
        self._recent_tree = ttk.Treeview(
            list_frame, show="tree",
            yscrollcommand=vsb.set, selectmode="browse", height=8,
        )
        vsb.config(command=self._recent_tree.yview)
        self._recent_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._recent_tree.bind("<Double-1>", self._on_recent_double_click)

        self._refresh_recent_list()

    def _refresh_recent_list(self) -> None:
        self._recent_tree.delete(*self._recent_tree.get_children())
        recents = get_recent_projects()
        if not recents:
            self._recent_tree.insert("", "end", text=tr("launcher.recent_empty"), tags=("muted",))
            self._recent_tree.tag_configure("muted", foreground=TEXT_MUTED)
            return
        for path in recents:
            name = os.path.basename(path) or path
            self._recent_tree.insert("", "end", iid=path,
                                    text=f"  {name}    {path}")

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_new_project(self) -> None:
        """P4 simplified: dialog → Project.new(). No source acquisition.

        Source and subtitles are added later from the Hub sidebar after
        the empty project is opened. This keeps "new project" cheap and
        non-committal — user can build up the project incrementally.
        """
        req = show_new_project_dialog(self.root)
        if req is None:
            return  # user cancelled

        try:
            project = Project.new(req.parent_dir, req.name)
        except FileExistsError as e:
            messagebox.showerror(tr("launcher.error.cannot_create"), str(e), parent=self.root)
            return
        except ValueError as e:
            messagebox.showerror(tr("launcher.error.invalid_name"), str(e), parent=self.root)
            return
        except OSError as e:
            messagebox.showerror(tr("launcher.error.cannot_create"),
                                 tr("launcher.error.disk_error", error=str(e)),
                                 parent=self.root)
            return

        add_recent_project(project.folder)
        self._selected_project = project
        self.root.destroy()

    def _on_open_existing(self) -> None:
        path = filedialog.askdirectory(
            title=tr("launcher.dialog.select_folder"),
            parent=self.root,
        )
        if not path:
            return
        self._open_path(path)

    def _on_recent_double_click(self, _event) -> None:
        sel = self._recent_tree.selection()
        if not sel:
            return
        path = sel[0]
        if path == "":  # "(空)" placeholder row has no iid
            return
        if not os.path.isdir(path):
            messagebox.showwarning(
                tr("launcher.error.project_missing"),
                tr("launcher.error.path_not_exist", path=path),
                parent=self.root,
            )
            # Remove from recent list (get_recent_projects already filters,
            # but we should rewrite the file to be tidy).
            self._refresh_recent_list()
            return
        self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            project = Project.open(path)
        except Exception as e:
            messagebox.showerror(tr("launcher.error.open_failed"), str(e), parent=self.root)
            return
        add_recent_project(project.folder)
        self._selected_project = project
        self.root.destroy()

    def _on_close(self) -> None:
        """X button: quit without selecting a project."""
        self._selected_project = None
        self.root.destroy()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> Project | None:
        self.root.mainloop()
        return self._selected_project


def run_launcher() -> Project | None:
    """Show the launcher, block until user picks a project or closes.

    Returns the selected Project, or None if user quit. Creates and
    destroys its own Tk root, so safe to call repeatedly from the main
    application loop.
    """
    return _LauncherWindow().run()


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Make src/ importable when run directly
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    project = run_launcher()
    if project is None:
        print("Launcher closed without selecting a project.")
    else:
        print(f"Selected project: {project.name} @ {project.folder}")
        print(f"  source_status: {_nv_paths.source_status(project)}")
        print(f"  derivatives:   {project.list_creations()}")
