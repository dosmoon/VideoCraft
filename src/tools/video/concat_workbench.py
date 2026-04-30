"""Video Concatenation Workbench — join multiple videos into one.

Companion to split_workbench: that tool turns one video into many,
this one turns many into one. Commit 1 ships stream-copy only —
inputs must share container/codec/resolution/fps. Mismatch is
detected via ffprobe and the Concatenate button stays disabled with
a clear hint until the user fixes the lineup. Re-encode mode comes
in a follow-up commit.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from tools.base import ToolBase
from i18n import tr
from hub_logger import logger
from core.video_concat import probe_video, concat_videos, concat_videos_reencode


def _fmt_duration(sec: float) -> str:
    s = max(0, int(round(sec)))
    h, rem = divmod(s, 3600)
    m, sec_r = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec_r:02d}"
    return f"{m}:{sec_r:02d}"


def _fmt_fps(fps: float) -> str:
    if not fps:
        return "?"
    # Round to 1 decimal but drop trailing .0 for clean look (30, 29.97, 60).
    rounded = round(fps, 2)
    if abs(rounded - round(rounded)) < 0.05:
        return f"{int(round(rounded))}"
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _fmt_resolution(width: int, height: int) -> str:
    if not width or not height:
        return "?"
    return f"{width}x{height}"


class ConcatWorkbenchApp(ToolBase):
    def __init__(self, root, initial_file=None):
        self.root = root
        self.master = root
        self.root.title(tr("tool.concat_workbench.title"))
        self.root.geometry("1100x650")

        # Each row: {"path": str, "probe": dict}
        self._rows: list[dict] = []

        self._build_ui()

        if initial_file:
            if isinstance(initial_file, (list, tuple)):
                for p in initial_file:
                    if os.path.isfile(p):
                        self._add_file(p)
            elif isinstance(initial_file, str) and os.path.isfile(initial_file):
                self._add_file(initial_file)
            self._refresh_after_change()

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Two-column layout: left = list + buttons + log; right = output panel.
        outer = tk.Frame(self.root, padx=10, pady=10)
        outer.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(outer)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = tk.Frame(outer, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        # Left: list label + Treeview
        tk.Label(left, text=tr("tool.concat_workbench.inputs_label"),
                 font=("Arial", 10, "bold"), anchor="w").pack(
            fill=tk.X, pady=(0, 4))

        list_frame = tk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("idx", "name", "duration", "resolution", "fps", "vcodec", "acodec")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                    selectmode="browse", height=12)
        for c, w, anchor in [
            ("idx", 36, "center"),
            ("name", 320, "w"),
            ("duration", 70, "center"),
            ("resolution", 90, "center"),
            ("fps", 60, "center"),
            ("vcodec", 70, "center"),
            ("acodec", 70, "center"),
        ]:
            self._tree.heading(c, text=tr(f"tool.concat_workbench.col.{c}"))
            self._tree.column(c, width=w, anchor=anchor)
        # Tag for rows whose attributes diverge from row 1.
        self._tree.tag_configure("mismatch", background="#fee2e2")
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, command=self._tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.configure(yscrollcommand=sb.set)

        # Buttons row under list
        btn_row = tk.Frame(left)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        for label_key, cmd in [
            ("tool.concat_workbench.btn_add", self._on_add),
            ("tool.concat_workbench.btn_remove", self._on_remove),
            ("tool.concat_workbench.btn_up", self._on_up),
            ("tool.concat_workbench.btn_down", self._on_down),
            ("tool.concat_workbench.btn_clear", self._on_clear),
        ]:
            tk.Button(btn_row, text=tr(label_key), command=cmd, width=10).pack(
                side=tk.LEFT, padx=(0, 4))

        # Mismatch hint banner (shown only when needed)
        self._hint_var = tk.StringVar(value="")
        self._hint_label = tk.Label(left, textvariable=self._hint_var,
                                      fg="#b91c1c", anchor="w",
                                      wraplength=720, justify="left",
                                      font=("Arial", 9))
        self._hint_label.pack(fill=tk.X, pady=(8, 0))

        # Status log
        tk.Label(left, text=tr("tool.concat_workbench.log_label"),
                 font=("Arial", 9, "bold"), anchor="w").pack(
            fill=tk.X, pady=(10, 2))
        self._log = tk.Text(left, height=8, wrap=tk.WORD, font=("Arial", 9))
        self._log.pack(fill=tk.BOTH, expand=False)
        self._log.config(state="disabled")

        # Right panel: totals + output + run button
        tk.Label(right, text=tr("tool.concat_workbench.output_header"),
                 font=("Arial", 12, "bold"), anchor="w").pack(
            fill=tk.X, pady=(0, 8))
        self._totals_var = tk.StringVar(value=tr(
            "tool.concat_workbench.totals", count=0, duration="0:00"))
        tk.Label(right, textvariable=self._totals_var, fg="#374151",
                 anchor="w").pack(fill=tk.X, pady=(0, 12))

        tk.Label(right, text=tr("tool.concat_workbench.output_path"),
                 font=("Arial", 10, "bold"), anchor="w").pack(fill=tk.X)
        out_row = tk.Frame(right)
        out_row.pack(fill=tk.X, pady=(2, 12))
        self._output_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self._output_var,
                 font=("Arial", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(out_row, text=tr("tool.concat_workbench.btn_browse"),
                  command=self._on_browse_output, width=8).pack(
            side=tk.RIGHT, padx=(4, 0))

        # Mode picker — auto-toggles to reencode when mismatch detected.
        tk.Label(right, text=tr("tool.concat_workbench.mode_label"),
                 font=("Arial", 10, "bold"), anchor="w").pack(fill=tk.X)
        self._mode_var = tk.StringVar(value="stream_copy")
        self._mode_var.trace_add("write",
                                  lambda *_: self._refresh_hint_and_run_state())
        self._stream_rb = tk.Radiobutton(
            right, text=tr("tool.concat_workbench.mode_stream_copy"),
            variable=self._mode_var, value="stream_copy", anchor="w")
        self._stream_rb.pack(fill=tk.X)
        self._reencode_rb = tk.Radiobutton(
            right, text=tr("tool.concat_workbench.mode_reencode"),
            variable=self._mode_var, value="reencode", anchor="w")
        self._reencode_rb.pack(fill=tk.X)

        # Re-encode target spec (only meaningful when reencode is selected).
        target_row = tk.Frame(right)
        target_row.pack(fill=tk.X, pady=(4, 12))
        tk.Label(target_row, text=tr("tool.concat_workbench.target_label"),
                 font=("Arial", 9), anchor="w").pack(side=tk.LEFT)
        self._target_var = tk.StringVar(value="follow_first")
        self._target_combo = ttk.Combobox(
            target_row, textvariable=self._target_var, state="readonly",
            values=["follow_first", "highest"], width=14, font=("Arial", 9))
        # Display labels via internal mapping.
        self._target_label_map = {
            "follow_first": tr("tool.concat_workbench.target_follow_first"),
            "highest": tr("tool.concat_workbench.target_highest"),
        }
        self._target_combo["values"] = list(self._target_label_map.values())
        self._target_combo.set(self._target_label_map["follow_first"])
        self._target_combo.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)

        # Progress bar (visible during re-encode, hidden otherwise).
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress = ttk.Progressbar(
            right, variable=self._progress_var, maximum=100.0)
        self._progress.pack(fill=tk.X, pady=(0, 4))

        self._run_btn = tk.Button(
            right, text=tr("tool.concat_workbench.btn_concat"),
            command=self._on_concat, state="disabled",
            bg="#2563eb", fg="white", font=("Arial", 11, "bold"), height=2)
        self._run_btn.pack(fill=tk.X, pady=(8, 0))

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str) -> None:
        self._log.config(state="normal")
        self._log.insert(tk.END, msg + "\n")
        self._log.see(tk.END)
        self._log.config(state="disabled")

    def _add_file(self, path: str) -> None:
        try:
            probe = probe_video(path)
        except Exception as e:
            self._log_msg(tr("tool.concat_workbench.log.probe_failed",
                              path=os.path.basename(path), e=str(e)))
            return
        self._rows.append({"path": path, "probe": probe})
        self._log_msg(tr("tool.concat_workbench.log.added",
                          path=os.path.basename(path)))

    def _selected_index(self) -> int | None:
        sel = self._tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _refresh_after_change(self) -> None:
        self._rebuild_tree()
        self._refresh_totals()
        self._refresh_default_output()
        # When inputs require re-encode, nudge the user there automatically.
        # Stays in stream_copy if the lineup happens to be consistent.
        if self._has_mismatch() and self._mode_var.get() == "stream_copy":
            self._mode_var.set("reencode")
        self._refresh_hint_and_run_state()

    def _has_mismatch(self) -> bool:
        if len(self._rows) < 2:
            return False
        ref = self._rows[0]["probe"]
        return any(self._row_diverges(r["probe"], ref) for r in self._rows[1:])

    def _resolve_target_spec(self) -> dict:
        """Build the target {width, height, fps, vcodec, acodec} from the combo.

        follow_first → exactly row 1's attrs
        highest      → max width × height across rows; max fps; libx264/aac
        """
        if not self._rows:
            return {}
        # Map the localized combo display back to the internal key.
        choice = self._target_var.get()
        for k, label in self._target_label_map.items():
            if choice == label:
                choice = k
                break
        if choice == "highest":
            w = max((r["probe"].get("width") or 0) for r in self._rows)
            h = max((r["probe"].get("height") or 0) for r in self._rows)
            fps = max((r["probe"].get("fps") or 0) for r in self._rows) or 30
            return {"width": w or 1920, "height": h or 1080,
                    "fps": fps, "vcodec": "libx264", "acodec": "aac"}
        # follow_first
        p = self._rows[0]["probe"]
        return {
            "width": p.get("width") or 1920,
            "height": p.get("height") or 1080,
            "fps": p.get("fps") or 30,
            "vcodec": "libx264", "acodec": "aac",
        }

    def _rebuild_tree(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        ref = self._rows[0]["probe"] if self._rows else None
        for i, r in enumerate(self._rows):
            p = r["probe"]
            tags: tuple[str, ...] = ()
            if ref is not None and i > 0 and self._row_diverges(p, ref):
                tags = ("mismatch",)
            self._tree.insert(
                "", "end", iid=str(i),
                values=(
                    str(i + 1),
                    os.path.basename(r["path"]),
                    _fmt_duration(p.get("duration", 0.0)),
                    _fmt_resolution(p.get("width", 0), p.get("height", 0)),
                    _fmt_fps(p.get("fps", 0.0)),
                    p.get("vcodec") or "?",
                    p.get("acodec") or "?",
                ),
                tags=tags,
            )

    @staticmethod
    def _row_diverges(p: dict, ref: dict) -> bool:
        for key in ("width", "height", "vcodec", "acodec"):
            if p.get(key) != ref.get(key):
                return True
        # FPS comparison with small tolerance (29.97 vs 30 considered same)
        a = float(p.get("fps") or 0.0)
        b = float(ref.get("fps") or 0.0)
        if abs(a - b) > 0.5:
            return True
        return False

    def _refresh_totals(self) -> None:
        total = sum(r["probe"].get("duration", 0.0) for r in self._rows)
        self._totals_var.set(tr(
            "tool.concat_workbench.totals",
            count=len(self._rows), duration=_fmt_duration(total)))

    def _refresh_default_output(self) -> None:
        # Only auto-fill while user hasn't typed anything custom.
        if self._output_var.get().strip():
            return
        if not self._rows:
            return
        first = self._rows[0]["path"]
        base = os.path.splitext(os.path.basename(first))[0]
        self._output_var.set(os.path.join(
            os.path.dirname(first), f"{base}_concat.mp4"))

    def _refresh_hint_and_run_state(self) -> None:
        n = len(self._rows)
        if n == 0:
            self._hint_var.set("")
            self._run_btn.config(state="disabled")
            return
        if n == 1:
            self._hint_var.set(tr("tool.concat_workbench.hint_need_two"))
            self._run_btn.config(state="disabled")
            return
        ref = self._rows[0]["probe"]
        bad = [i for i, r in enumerate(self._rows[1:], start=2)
               if self._row_diverges(r["probe"], ref)]
        mode = self._mode_var.get()
        if bad and mode == "stream_copy":
            self._hint_var.set(tr(
                "tool.concat_workbench.hint_mismatch_stream",
                rows=", ".join(f"#{i}" for i in bad)))
            self._run_btn.config(state="disabled")
        elif bad and mode == "reencode":
            self._hint_var.set(tr(
                "tool.concat_workbench.hint_mismatch_reencode",
                rows=", ".join(f"#{i}" for i in bad)))
            self._run_btn.config(state="normal")
        else:
            self._hint_var.set("")
            self._run_btn.config(state="normal")

    # ── Button handlers ──────────────────────────────────────────────────────

    def _on_add(self) -> None:
        paths = filedialog.askopenfilenames(
            title=tr("tool.concat_workbench.dlg_add_title"),
            filetypes=[("Video files", "*.mp4 *.mov *.mkv *.webm *.avi"),
                       ("All files", "*.*")])
        if not paths:
            return
        for p in paths:
            self._add_file(p)
        self._refresh_after_change()

    def _on_remove(self) -> None:
        i = self._selected_index()
        if i is None:
            return
        del self._rows[i]
        self._refresh_after_change()

    def _on_up(self) -> None:
        i = self._selected_index()
        if i is None or i == 0:
            return
        self._rows[i - 1], self._rows[i] = self._rows[i], self._rows[i - 1]
        self._refresh_after_change()
        self._tree.selection_set(str(i - 1))

    def _on_down(self) -> None:
        i = self._selected_index()
        if i is None or i >= len(self._rows) - 1:
            return
        self._rows[i + 1], self._rows[i] = self._rows[i], self._rows[i + 1]
        self._refresh_after_change()
        self._tree.selection_set(str(i + 1))

    def _on_clear(self) -> None:
        self._rows.clear()
        self._output_var.set("")
        self._refresh_after_change()

    def _on_browse_output(self) -> None:
        initial = self._output_var.get().strip() or os.getcwd()
        path = filedialog.asksaveasfilename(
            title=tr("tool.concat_workbench.dlg_output_title"),
            defaultextension=".mp4",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial),
            filetypes=[("MP4", "*.mp4"), ("All files", "*.*")])
        if path:
            self._output_var.set(path)

    def _on_concat(self) -> None:
        output = self._output_var.get().strip()
        if not output:
            self._log_msg(tr("tool.concat_workbench.log.no_output"))
            return
        files = [r["path"] for r in self._rows]
        mode = self._mode_var.get()
        self._run_btn.config(state="disabled")
        self._progress_var.set(0.0)
        self.set_busy(tr("tool.concat_workbench.status_running"))
        if mode == "reencode":
            target = self._resolve_target_spec()
            self._log_msg(tr(
                "tool.concat_workbench.log.starting_reencode",
                n=len(files), output=os.path.basename(output),
                spec=f"{target['width']}x{target['height']} @ {target['fps']}fps"))
            threading.Thread(target=self._concat_worker_reencode,
                              args=(files, output, target),
                              daemon=True).start()
        else:
            self._log_msg(tr("tool.concat_workbench.log.starting",
                              n=len(files), output=os.path.basename(output)))
            threading.Thread(target=self._concat_worker,
                              args=(files, output), daemon=True).start()

    def _concat_worker(self, files: list[str], output: str) -> None:
        try:
            concat_videos(files, output)
            self.master.after(0, self._on_concat_done, output, None)
        except Exception as e:
            self.master.after(0, self._on_concat_done, output, str(e))

    def _concat_worker_reencode(self, files: list[str], output: str,
                                  target: dict) -> None:
        def progress(pct: float):
            self.master.after(0, self._progress_var.set, pct)
        try:
            concat_videos_reencode(files, output, target, progress_cb=progress)
            self.master.after(0, self._progress_var.set, 100.0)
            self.master.after(0, self._on_concat_done, output, None)
        except Exception as e:
            self.master.after(0, self._on_concat_done, output, str(e))

    def _on_concat_done(self, output: str, err: str | None) -> None:
        if err:
            self._log_msg(tr("tool.concat_workbench.log.failed", e=err))
            self.set_error(tr("tool.concat_workbench.error_failed", e=err))
        else:
            self._log_msg(tr("tool.concat_workbench.log.done", output=output))
            logger.info(f"Video concat done → {output}")
            self.set_done(tr("tool.concat_workbench.status_done"))
        self._refresh_hint_and_run_state()


if __name__ == "__main__":
    root = tk.Tk()
    app = ConcatWorkbenchApp(root)
    root.mainloop()
