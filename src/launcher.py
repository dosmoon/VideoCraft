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
import shutil
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from project import Project, get_recent_projects, add_recent_project
from core.project_schema import Source, ORIGIN_LINK
from core.source_acquire import AcquireError, ERR_CANCELLED
from ui.new_project_dialog import show_new_project_dialog, NewProjectRequest
from ui.disclaimer_dialog import show_if_needed as show_disclaimer_if_needed
from ui.source_prepare_modal import SourcePrepareModal


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
        tk.Label(header, text="源视频派生创作工具", font=("Microsoft YaHei UI", 10),
                 bg=BG, fg=TEXT_MUTED).pack(anchor="w", pady=(2, 0))

        # Primary actions
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="x", padx=24, pady=(16, 8))
        tk.Button(actions, text="  +  新建项目", font=("Microsoft YaHei UI", 11),
                  command=self._on_new_project,
                  bg=ACCENT, fg="white", relief="flat", padx=10, pady=8,
                  cursor="hand2", activebackground="#005ea2"
                  ).pack(fill="x", pady=(0, 6))
        tk.Button(actions, text="  □  打开已有项目...", font=("Microsoft YaHei UI", 11),
                  command=self._on_open_existing,
                  bg="#e0e0e0", fg=TEXT_DARK, relief="flat", padx=10, pady=8,
                  cursor="hand2", activebackground="#d0d0d0"
                  ).pack(fill="x")

        # Recent projects
        tk.Label(self.root, text="最近项目", font=("Microsoft YaHei UI", 10, "bold"),
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
            self._recent_tree.insert("", "end", text="  (空)", tags=("muted",))
            self._recent_tree.tag_configure("muted", foreground=TEXT_MUTED)
            return
        for path in recents:
            name = os.path.basename(path) or path
            self._recent_tree.insert("", "end", iid=path,
                                    text=f"  {name}    {path}")

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_new_project(self) -> None:
        """P2: full new-project flow.

          1. Dialog gathers source/name/parent (validated in-dialog)
          2. First-time disclaimer for link mode (settings-tracked)
          3. Project skeleton mkdir + .videocraft/project.json
          4. Source-prepare modal: yt-dlp / ffmpeg with progress + cancel
          5. Write final source meta back into project.json

        On cancel at any post-step-3 stage, the half-built project
        directory is rolled back so the user isn't left with junk.
        """
        req = show_new_project_dialog(self.root)
        if req is None:
            return  # user cancelled

        # First-time disclaimer (link mode only). Cancel here = abort entirely.
        if req.source.origin == ORIGIN_LINK:
            if not show_disclaimer_if_needed(self.root):
                return

        # Create the project skeleton — empty source/, subtitles/, derivatives/
        try:
            project = Project.new(req.parent_dir, req.name, req.source)
        except FileExistsError as e:
            messagebox.showerror("无法创建", str(e), parent=self.root)
            return
        except ValueError as e:
            messagebox.showerror("项目名不合法", str(e), parent=self.root)
            return
        except OSError as e:
            messagebox.showerror("无法创建", f"目录不可写或磁盘错误:\n{e}",
                                 parent=self.root)
            return

        # Acquire the source video (blocking modal).
        modal = SourcePrepareModal(
            self.root, req.source,
            dest_video_path=project.source_video_path,
            dest_meta_path=project.source_meta_path,
        )
        try:
            result = modal.run()
        except AcquireError as e:
            # Roll back the half-built project dir.
            _rmtree_quiet(project.folder)
            if e.category == ERR_CANCELLED:
                # Silent rollback on user cancel — no error popup.
                return
            messagebox.showerror(
                "源视频准备失败",
                f"{e.message}\n\n{e.details[:400]}" if e.details else e.message,
                parent=self.root,
            )
            return
        except Exception as e:
            _rmtree_quiet(project.folder)
            messagebox.showerror("源视频准备失败", str(e), parent=self.root)
            return

        # Backfill the metadata we now know from the acquired source.
        meta = project.meta
        if result.title:
            meta.source.title = result.title
        if result.duration_sec is not None:
            meta.source.duration_sec = result.duration_sec
        if result.width is not None:
            meta.source.width = result.width
        if result.height is not None:
            meta.source.height = result.height
        project.update_meta(meta)

        add_recent_project(project.folder)
        self._selected_project = project
        self.root.destroy()

    def _on_open_existing(self) -> None:
        path = filedialog.askdirectory(
            title="选择项目文件夹",
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
                "项目不存在", f"路径不存在或已被移动:\n{path}",
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
            messagebox.showerror("打开失败", str(e), parent=self.root)
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


def _rmtree_quiet(path: str) -> None:
    """Best-effort recursive delete; swallow errors so rollback never
    masks the underlying acquisition error."""
    try:
        shutil.rmtree(path)
    except OSError:
        pass


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
        print(f"  source_status: {project.source_status()}")
        print(f"  derivatives:   {project.list_derivatives()}")
