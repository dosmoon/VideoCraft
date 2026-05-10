"""Model Manager — embedded-AI catalog browser + download queue UI.

Three regions stacked vertically:
  Top    — models dir path + free-space readout + buttons
           (open folder / change dir / refresh)
  Middle — Treeview: catalog grouped by capability with status + size,
           multi-select; toolbar with Download / Cancel / Remove / Reveal
  Bottom — Active downloads list with per-job progress bars and per-job cancel

This window is a "tool" and consumes core.models directly (allowed for
infrastructure-tier UIs; same posture as the AI Console).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from tools.base import ToolBase
from i18n import tr

from core import paths as _paths
from core.ai.router import router as _ai_router
from core.models import (
    CATALOG, get as cat_get, by_capability,
    scan, status_for, remove as registry_remove, reveal_in_explorer,
    manager, invalidate_all as invalidate_metadata, cache_age_sec,
    ResolveError,
)
from core.models.manager import (
    JOB_QUEUED, JOB_RUNNING, JOB_DONE, JOB_FAILED, JOB_CANCELLED,
)


# ── Display helpers ──────────────────────────────────────────────────────────

def _fmt_bytes(n: int | float) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_speed(bps: float) -> str:
    if not bps:
        return ""
    return f"{_fmt_bytes(bps)}/s"


def _fmt_eta(sec: float | None) -> str:
    if sec is None or sec <= 0:
        return ""
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def _capability_label(cap: str) -> str:
    return tr(f"tool.models.cap.{cap}")


def _tier_label(tier: str) -> str:
    return tr(f"tool.models.tier.{tier}")


def _status_label(st) -> str:
    if not st.resolved:
        return tr("tool.models.status.unresolved")
    if st.complete:
        return tr("tool.models.status.installed")
    if st.partial:
        return tr("tool.models.status.partial")
    return tr("tool.models.status.missing")


# ── Main app ─────────────────────────────────────────────────────────────────

class ModelManagerApp(ToolBase):
    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.models.title"))
        master.geometry("980x720")

        # iid mapping for the catalog Treeview
        self._cat_rows: dict[str, str] = {}     # model_id -> tree iid
        self._row_ids: dict[str, str] = {}      # tree iid -> model_id

        # iid mapping for the jobs Treeview
        self._job_rows: dict[str, str] = {}     # job_id -> tree iid

        # Subscription handle so we can detach on window close
        self._unsubscribe = None

        self._build_top_panel()
        self._build_catalog_panel()
        self._build_jobs_panel()

        self._refresh_catalog()
        self._refresh_jobs(manager.list_jobs())

        # Subscribe AFTER initial paint so the worker can't race the build.
        self._unsubscribe = manager.on_event(self._on_jobs_event)

        master.protocol("WM_DELETE_WINDOW", self._on_close)
        # Periodic catalog re-scan in case files changed outside our control.
        self._schedule_periodic_rescan()

    # ── Build: top ─────────────────────────────────────────────────────────

    def _build_top_panel(self):
        frm = tk.Frame(self.master, padx=10, pady=8)
        frm.pack(fill="x")

        tk.Label(frm, text=tr("tool.models.dir_label"),
                 font=("", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.var_dir = tk.StringVar(value=_paths.models_dir())
        self.lbl_dir = tk.Label(frm, textvariable=self.var_dir, fg="#0066cc",
                                cursor="hand2", anchor="w")
        self.lbl_dir.grid(row=0, column=1, sticky="we", padx=(6, 0))
        self.lbl_dir.bind("<Button-1>", lambda _e: reveal_in_explorer(_paths.models_dir()))

        self.var_free = tk.StringVar(value="")
        tk.Label(frm, textvariable=self.var_free, fg="#555").grid(
            row=1, column=1, sticky="w", padx=(6, 0))

        btns = tk.Frame(frm)
        btns.grid(row=0, column=2, rowspan=2, sticky="e", padx=(8, 0))
        tk.Button(btns, text=tr("tool.models.btn_open_dir"),
                  command=lambda: reveal_in_explorer(_paths.models_dir())
                  ).pack(side="left", padx=2)
        tk.Button(btns, text=tr("tool.models.btn_change_dir"),
                  command=self._on_change_dir).pack(side="left", padx=2)
        tk.Button(btns, text=tr("tool.models.btn_refresh_metadata"),
                  command=self._refresh_metadata).pack(side="left", padx=2)
        tk.Button(btns, text=tr("tool.models.btn_refresh"),
                  command=self._refresh_catalog).pack(side="left", padx=2)

        frm.columnconfigure(1, weight=1)
        self._update_disk_readout()

    def _on_change_dir(self):
        new = filedialog.askdirectory(
            title=tr("tool.models.dialog_pick_dir"),
            initialdir=_paths.models_dir(),
        )
        if not new:
            return
        if not messagebox.askyesno(
            tr("tool.models.title"),
            tr("tool.models.confirm_change_dir").format(path=new),
        ):
            return
        _ai_router.set_models_dir(new)
        messagebox.showinfo(
            tr("tool.models.title"),
            tr("tool.models.change_dir_restart_hint"),
        )
        # Best-effort: refresh display now even though env vars need restart.
        self.var_dir.set(new)
        self._refresh_catalog()

    def _update_disk_readout(self):
        from core.models.registry import disk_free_bytes
        free = disk_free_bytes(_paths.models_dir())
        self.var_free.set(tr("tool.models.disk_free").format(free=_fmt_bytes(free)))

    # ── Build: catalog ─────────────────────────────────────────────────────

    def _build_catalog_panel(self):
        outer = tk.LabelFrame(self.master, text=tr("tool.models.catalog_title"),
                              padx=8, pady=6)
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        bar = tk.Frame(outer)
        bar.pack(fill="x", pady=(0, 6))

        tk.Button(bar, text=tr("tool.models.btn_download"),
                  command=self._on_download_selected).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.models.btn_remove"),
                  command=self._on_remove_selected).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.models.btn_reveal"),
                  command=self._on_reveal_selected).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.models.btn_download_first_tier"),
                  command=lambda: self._enqueue_tier("first")
                  ).pack(side="left", padx=(16, 2))
        tk.Button(bar, text=tr("tool.models.btn_download_recommended_tier"),
                  command=lambda: self._enqueue_tier("recommended")
                  ).pack(side="left", padx=2)

        cols = ("size", "status", "tier", "on_disk")
        self.tree = ttk.Treeview(outer, columns=cols, selectmode="extended",
                                 show="tree headings")
        self.tree.heading("#0", text=tr("tool.models.col_model"))
        self.tree.heading("size", text=tr("tool.models.col_size"))
        self.tree.heading("status", text=tr("tool.models.col_status"))
        self.tree.heading("tier", text=tr("tool.models.col_tier"))
        self.tree.heading("on_disk", text=tr("tool.models.col_on_disk"))

        self.tree.column("#0", width=380, stretch=True)
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("tier", width=110, anchor="center")
        self.tree.column("on_disk", width=110, anchor="e")

        sb = ttk.Scrollbar(outer, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.tree.tag_configure("installed",  foreground="#1a7f1a")
        self.tree.tag_configure("partial",    foreground="#b07a00")
        self.tree.tag_configure("missing",    foreground="#666666")
        self.tree.tag_configure("unresolved", foreground="#a02020")

    def _refresh_catalog(self):
        # Wipe and rebuild — small enough that incremental update isn't worth
        # the bookkeeping. Selection survives via stable iid (model_id).
        selected_ids = {self._row_ids[i] for i in self.tree.selection()
                        if i in self._row_ids}

        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._cat_rows.clear()
        self._row_ids.clear()

        # Cached scan — fast even with 5+ specs. Force-refresh comes from
        # the explicit "Refresh Metadata" button.
        statuses = scan()
        for cap in ("asr", "tts", "llm", "vad"):
            specs = by_capability(cap)
            if not specs:
                continue
            group_iid = f"cap-{cap}"
            self.tree.insert("", "end", iid=group_iid,
                             text=_capability_label(cap), open=True,
                             values=("", "", "", ""))
            for spec in specs:
                st = statuses[spec.id]
                if not st.resolved:
                    tag = "unresolved"
                elif st.complete:
                    tag = "installed"
                elif st.partial:
                    tag = "partial"
                else:
                    tag = "missing"
                iid = f"m-{spec.id}"
                size_label = (_fmt_bytes(st.total_bytes) if st.resolved
                              else "—")
                self.tree.insert(
                    group_iid, "end", iid=iid,
                    text=spec.display_name,
                    values=(
                        size_label,
                        _status_label(st),
                        _tier_label(spec.tier),
                        _fmt_bytes(st.bytes_on_disk) if st.bytes_on_disk else "",
                    ),
                    tags=(tag,),
                )
                self._cat_rows[spec.id] = iid
                self._row_ids[iid] = spec.id

        restore = [self._cat_rows[mid] for mid in selected_ids
                   if mid in self._cat_rows]
        if restore:
            self.tree.selection_set(restore)
        self._update_disk_readout()

    def _refresh_metadata(self):
        """Force re-fetch HF metadata for every catalog repo (background).

        Cheap when the cache is fresh (no-op until TTL expires); useful
        after upstream re-uploads or when the user just installed network.
        """
        def worker():
            try:
                # invalidate ensures the next scan force-refreshes from HF.
                invalidate_metadata()
                scan(force_refresh=True)
                err = None
            except ResolveError as e:
                err = str(e)
            except Exception as e:  # noqa: BLE001
                err = repr(e)
            try:
                self.master.after(0, lambda: self._after_refresh_metadata(err))
            except Exception:
                pass

        self.set_busy(tr("tool.models.toast_refreshing_metadata"))
        threading.Thread(target=worker, name="ModelMetaRefresh",
                         daemon=True).start()

    def _after_refresh_metadata(self, err: str | None):
        if err:
            messagebox.showwarning(
                tr("tool.models.title"),
                tr("tool.models.warn_refresh_failed").format(err=err),
            )
        else:
            self.set_done(tr("tool.models.toast_metadata_refreshed"))
        self._refresh_catalog()

    def _selected_model_ids(self) -> list[str]:
        return [self._row_ids[i] for i in self.tree.selection()
                if i in self._row_ids]

    # ── Catalog actions ────────────────────────────────────────────────────

    def _on_download_selected(self):
        ids = self._selected_model_ids()
        if not ids:
            messagebox.showinfo(tr("tool.models.title"),
                                tr("tool.models.warn_pick_first"))
            return
        self._enqueue_with_preflight(ids)

    def _enqueue_tier(self, tier: str):
        ids = [s.id for s in CATALOG.values() if s.tier == tier]
        if not ids:
            return
        self._enqueue_with_preflight(ids)

    def _enqueue_with_preflight(self, ids: list[str]):
        # Strip already-installed entries; they'd be no-ops but warning the
        # user keeps the action transparent.
        statuses = scan()
        pending = [mid for mid in ids if not statuses[mid].complete]
        skipped = len(ids) - len(pending)
        if not pending:
            messagebox.showinfo(tr("tool.models.title"),
                                tr("tool.models.info_all_installed"))
            return

        ok, needed, free, target = manager.preflight_disk(pending)
        if not ok:
            proceed = messagebox.askyesno(
                tr("tool.models.title"),
                tr("tool.models.confirm_low_disk").format(
                    needed=_fmt_bytes(needed),
                    free=_fmt_bytes(free),
                    path=target,
                ),
            )
            if not proceed:
                return

        for mid in pending:
            manager.enqueue(mid)

        if skipped:
            self.set_busy(tr("tool.models.toast_enqueued_with_skip").format(
                count=len(pending), skipped=skipped))
        else:
            self.set_busy(tr("tool.models.toast_enqueued").format(count=len(pending)))

    def _on_remove_selected(self):
        ids = self._selected_model_ids()
        if not ids:
            messagebox.showinfo(tr("tool.models.title"),
                                tr("tool.models.warn_pick_first"))
            return
        names = "\n  • ".join(cat_get(mid).display_name for mid in ids)
        if not messagebox.askyesno(
            tr("tool.models.title"),
            tr("tool.models.confirm_remove").format(items=names),
        ):
            return
        freed_total = 0
        for mid in ids:
            freed_total += registry_remove(mid)
        self.set_busy(tr("tool.models.toast_removed").format(
            count=len(ids), freed=_fmt_bytes(freed_total)))
        self._refresh_catalog()

    def _on_reveal_selected(self):
        ids = self._selected_model_ids()
        if not ids:
            reveal_in_explorer(_paths.models_dir())
            return
        # Reveal first selection's directory.
        spec = cat_get(ids[0])
        target = spec.target_dir()
        if not target:
            return
        # Jump to first existing file inside, otherwise the dir itself.
        st = status_for(spec.id)
        first_existing = next(
            (f.target_path for f in st.files
             if f.bytes_on_disk > 0),
            target,
        )
        reveal_in_explorer(first_existing)

    # ── Build: jobs ────────────────────────────────────────────────────────

    def _build_jobs_panel(self):
        outer = tk.LabelFrame(self.master, text=tr("tool.models.jobs_title"),
                              padx=8, pady=6)
        outer.pack(fill="both", padx=10, pady=(0, 10))

        bar = tk.Frame(outer)
        bar.pack(fill="x", pady=(0, 6))
        tk.Button(bar, text=tr("tool.models.btn_cancel_job"),
                  command=self._on_cancel_selected_job
                  ).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.models.btn_cancel_all"),
                  command=manager.cancel_all).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.models.btn_clear_finished"),
                  command=manager.clear_finished).pack(side="left", padx=2)

        cols = ("state", "progress", "speed", "eta", "bytes")
        self.jobs_tree = ttk.Treeview(outer, columns=cols, show="tree headings",
                                      selectmode="browse", height=6)
        self.jobs_tree.heading("#0", text=tr("tool.models.col_model"))
        self.jobs_tree.heading("state", text=tr("tool.models.col_job_state"))
        self.jobs_tree.heading("progress", text=tr("tool.models.col_progress"))
        self.jobs_tree.heading("speed", text=tr("tool.models.col_speed"))
        self.jobs_tree.heading("eta", text=tr("tool.models.col_eta"))
        self.jobs_tree.heading("bytes", text=tr("tool.models.col_bytes"))

        self.jobs_tree.column("#0", width=320, stretch=True)
        self.jobs_tree.column("state",    width=90,  anchor="center")
        self.jobs_tree.column("progress", width=100, anchor="center")
        self.jobs_tree.column("speed",    width=110, anchor="e")
        self.jobs_tree.column("eta",      width=80,  anchor="e")
        self.jobs_tree.column("bytes",    width=170, anchor="e")

        sb = ttk.Scrollbar(outer, orient="vertical",
                           command=self.jobs_tree.yview)
        self.jobs_tree.configure(yscrollcommand=sb.set)
        self.jobs_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.jobs_tree.tag_configure("done",      foreground="#1a7f1a")
        self.jobs_tree.tag_configure("failed",    foreground="#a02020")
        self.jobs_tree.tag_configure("cancelled", foreground="#888888")
        self.jobs_tree.tag_configure("running",   foreground="#0066cc")

    def _on_cancel_selected_job(self):
        sel = self.jobs_tree.selection()
        if not sel:
            return
        iid = sel[0]
        # Reverse map iid -> job_id
        for jid, row_iid in self._job_rows.items():
            if row_iid == iid:
                manager.cancel(jid)
                return

    # ── Jobs event handler ─────────────────────────────────────────────────

    def _on_jobs_event(self, jobs):
        # Worker thread → marshal to Tk main loop.
        try:
            self.master.after(0, lambda: self._refresh_jobs(jobs))
        except Exception:
            pass

    def _refresh_jobs(self, jobs):
        # Track which iids we've used this pass; drop any not seen.
        seen = set()
        any_done_recently = False

        for job in jobs:
            iid = self._job_rows.get(job.job_id)
            if iid is None or not self.jobs_tree.exists(iid):
                iid = f"j-{job.job_id}"
                self.jobs_tree.insert("", "end", iid=iid,
                                       text=job.spec.display_name,
                                       values=("", "", "", "", ""))
                self._job_rows[job.job_id] = iid

            seen.add(iid)
            pct = int(job.fraction * 100)
            state_label = tr(f"tool.models.job_state.{job.state}")
            if job.state == JOB_FAILED and job.error:
                state_label = f"{state_label}: {job.error[:60]}"
            elif job.state == JOB_RUNNING and job.current_file:
                state_label = f"{state_label} ({job.current_file})"

            tag_map = {
                JOB_DONE:      "done",
                JOB_FAILED:    "failed",
                JOB_CANCELLED: "cancelled",
                JOB_RUNNING:   "running",
                JOB_QUEUED:    "",
            }
            self.jobs_tree.item(iid,
                text=job.spec.display_name,
                values=(
                    state_label,
                    f"{pct}%",
                    _fmt_speed(job.bytes_per_sec) if job.state == JOB_RUNNING else "",
                    _fmt_eta(job.eta_sec) if job.state == JOB_RUNNING else "",
                    f"{_fmt_bytes(job.bytes_done)} / {_fmt_bytes(job.bytes_total)}",
                ),
                tags=(tag_map.get(job.state, ""),),
            )
            if job.state == JOB_DONE and not getattr(job, "_ui_seen_done", False):
                any_done_recently = True
                # Mark on the local snapshot so subsequent ticks don't re-fire.
                # Note: we don't mutate the manager's job state — this is purely
                # a UI dedupe flag scoped to our snapshot view.
                job._ui_seen_done = True  # type: ignore[attr-defined]

        # Drop rows for jobs that disappeared (clear_finished).
        existing = set(self.jobs_tree.get_children(""))
        for iid in existing - seen:
            self.jobs_tree.delete(iid)
            for jid, row_iid in list(self._job_rows.items()):
                if row_iid == iid:
                    self._job_rows.pop(jid, None)

        if any_done_recently:
            # A download finished — refresh catalog to flip status badges.
            self._refresh_catalog()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def _schedule_periodic_rescan(self):
        # Catch user-side changes (manual file copy / external delete) so the
        # status column doesn't go stale. Cheap — disk metadata only.
        try:
            self.master.after(5000, self._tick_rescan)
        except Exception:
            pass

    def _tick_rescan(self):
        try:
            self._refresh_catalog()
        finally:
            self._schedule_periodic_rescan()

    def _on_close(self):
        try:
            if self._unsubscribe is not None:
                self._unsubscribe()
        finally:
            try:
                self.master.destroy()
            except Exception:
                pass
