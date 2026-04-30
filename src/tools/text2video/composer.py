"""Media Segment Composer — PPT-style batch import video composer.

Each segment is a (text, image, audio) tuple. Segments are composed linearly
into one MP4 via core.video_compose + core.video_concat.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

import core.tts as _tts
import core.video_compose as _vcompose
import core.video_concat as _vconcat
from core import user_data
from core.composer_model import ComposerProject, MediaSegment
from i18n import tr
from tools.base import ToolBase


_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_TEXT_EXTS = (".txt",)

_AUTOSAVE_PATH = user_data.path("composer_project.json")


def _sorted_by_basename(paths: list[str]) -> list[str]:
    return sorted(paths, key=lambda p: os.path.basename(p).lower())


def _list_folder(folder: str, exts: tuple) -> list[str]:
    return _sorted_by_basename([
        os.path.join(folder, f) for f in os.listdir(folder)
        if f.lower().endswith(exts)
    ])


def _read_text_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except UnicodeDecodeError:
        with open(path, encoding="gbk", errors="replace") as f:
            return f.read().strip()


class MediaSegmentComposerApp(ToolBase):
    """Tkinter UI for the Media Segment Composer."""

    def __init__(self, master):
        self.master = master
        master.title(tr("composer.title"))
        master.geometry("900x680")

        self._project = ComposerProject()
        self._expanded: set[str] = set()
        self._thumbs: dict[str, object] = {}
        self._save_timer: str | None = None
        self._working = False

        self._build_ui()
        master.after(120, self._try_restore)

    # ── UI Construction ─────────────────────────────────────────────────────

    def _build_ui(self):
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self.master, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text=tr("composer.voice_id") + ":").pack(side="left")
        self._voice_var = tk.StringVar()
        self._voice_var.trace_add("write", lambda *_: self._schedule_save())
        ttk.Entry(toolbar, textvariable=self._voice_var, width=32).pack(
            side="left", padx=(4, 14))
        ttk.Button(toolbar, text=tr("composer.gen_all_audio"),
                   command=self._generate_all_audio).pack(side="left", padx=2)
        ttk.Button(toolbar, text=tr("composer.compose"),
                   command=self._start_compose).pack(side="left", padx=2)

        import_bar = ttk.Frame(self.master, padding=(8, 2))
        import_bar.grid(row=1, column=0, sticky="ew")
        ttk.Button(import_bar, text=tr("composer.import_text"),
                   command=lambda: self._import_batch("text")).pack(side="left", padx=2)
        ttk.Button(import_bar, text=tr("composer.import_audio"),
                   command=lambda: self._import_batch("audio")).pack(side="left", padx=2)
        ttk.Button(import_bar, text=tr("composer.import_image"),
                   command=lambda: self._import_batch("image")).pack(side="left", padx=2)

        list_frame = ttk.Frame(self.master)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=4, pady=(2, 4))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(list_frame, highlightthickness=0, background="#f5f5f5")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._inner = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfigure(self._canvas_window, width=e.width))
        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(int(-e.delta / 120), "units"))

        self._refresh_cards()

    # ── Card List Rendering ─────────────────────────────────────────────────

    def _refresh_cards(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._thumbs.clear()

        for idx, seg in enumerate(self._project.segments):
            card = self._make_card(idx, seg)
            card.pack(fill="x", padx=6, pady=3)

        add_btn = ttk.Button(self._inner, text=tr("composer.add_segment"),
                             command=self._add_segment)
        add_btn.pack(pady=10)

        self._inner.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _make_card(self, idx: int, seg: MediaSegment) -> ttk.LabelFrame:
        card = ttk.LabelFrame(self._inner, text=f"  #{idx + 1}  ", padding=6)

        collapsed = ttk.Frame(card)
        collapsed.pack(fill="x")
        self._build_collapsed(collapsed, idx, seg)

        if seg.id in self._expanded:
            exp = ttk.Frame(card, padding=(0, 6, 0, 0))
            exp.pack(fill="x")
            self._build_expanded(exp, seg)

        return card

    def _build_collapsed(self, parent: ttk.Frame, idx: int, seg: MediaSegment):
        thumb = tk.Label(parent, bg="#cccccc", width=12, height=4, relief="flat")
        thumb.pack(side="left", padx=(0, 8))
        if seg.image_path and os.path.isfile(seg.image_path) and _PIL_OK:
            try:
                img = Image.open(seg.image_path)
                img.thumbnail((96, 64), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._thumbs[seg.id] = photo
                thumb.configure(image=photo, width=96, height=64)
            except Exception:
                pass

        info = ttk.Frame(parent)
        info.pack(side="left", fill="x", expand=True)
        preview_text = seg.text.replace("\n", " ")
        if len(preview_text) > 50:
            preview_text = preview_text[:50] + "…"
        if not preview_text:
            preview_text = tr("composer.no_text")
        ttk.Label(info, text=preview_text, anchor="w").pack(fill="x")

        if seg.audio_path and os.path.isfile(seg.audio_path):
            audio_label = os.path.basename(seg.audio_path)
            audio_color = "#666"
        else:
            audio_label = tr("composer.no_audio")
            audio_color = "#c97400"
        ttk.Label(info, text=audio_label, foreground=audio_color,
                  anchor="w").pack(fill="x")

        btns = ttk.Frame(parent)
        btns.pack(side="right")
        ttk.Button(btns, text="↑", width=3,
                   command=lambda i=idx: self._move_segment(i, -1)).pack(side="left")
        ttk.Button(btns, text="↓", width=3,
                   command=lambda i=idx: self._move_segment(i, 1)).pack(side="left")
        edit_text = tr("composer.btn_fold") if seg.id in self._expanded else tr("composer.btn_edit")
        ttk.Button(btns, text=edit_text,
                   command=lambda s=seg: self._toggle_expand(s.id)).pack(side="left", padx=4)
        ttk.Button(btns, text=tr("composer.btn_delete"),
                   command=lambda i=idx: self._delete_segment(i)).pack(side="left")

    def _build_expanded(self, parent: ttk.Frame, seg: MediaSegment):
        # Image row
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=tr("composer.field_image") + ":", width=8,
                  anchor="w").pack(side="left")
        ttk.Label(row,
                  text=os.path.basename(seg.image_path) if seg.image_path else "—",
                  foreground="#555").pack(side="left", padx=(0, 6))
        ttk.Button(row, text=tr("composer.btn_change"),
                   command=lambda s=seg: self._pick_image(s)).pack(side="left", padx=2)
        ttk.Button(row, text=tr("composer.btn_clear"),
                   command=lambda s=seg: self._clear_image(s)).pack(side="left")

        # Text row
        ttk.Label(parent, text=tr("composer.field_text") + ":",
                  anchor="w").pack(fill="x", pady=(4, 2))
        txt = tk.Text(parent, height=4, wrap="word")
        txt.insert("1.0", seg.text)
        txt.pack(fill="x")
        txt.bind("<FocusOut>", lambda e, s=seg, w=txt: self._save_text(s, w))

        # Audio row
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=tr("composer.field_audio") + ":", width=8,
                  anchor="w").pack(side="left")
        aud_label = ttk.Label(
            row,
            text=os.path.basename(seg.audio_path) if seg.audio_path else "—",
            foreground="#555")
        aud_label.pack(side="left", padx=(0, 6))
        ttk.Button(row, text=tr("composer.btn_upload"),
                   command=lambda s=seg: self._pick_audio(s)).pack(side="left", padx=2)
        ttk.Button(row, text=tr("composer.btn_gen_audio"),
                   command=lambda s=seg: self._generate_audio_single(s)).pack(side="left")

        ttk.Button(parent, text=tr("composer.btn_done"),
                   command=lambda s=seg: self._toggle_expand(s.id)
                   ).pack(anchor="e", pady=(6, 0))

    # ── Interactions ────────────────────────────────────────────────────────

    def _toggle_expand(self, seg_id: str):
        if seg_id in self._expanded:
            self._expanded.discard(seg_id)
        else:
            self._expanded.add(seg_id)
        self._refresh_cards()

    def _add_segment(self):
        self._project.segments.append(MediaSegment.new())
        self._refresh_cards()
        self._schedule_save()

    def _delete_segment(self, idx: int):
        segs = self._project.segments
        if 0 <= idx < len(segs):
            self._expanded.discard(segs[idx].id)
            segs.pop(idx)
            self._refresh_cards()
            self._schedule_save()

    def _move_segment(self, idx: int, direction: int):
        segs = self._project.segments
        target = idx + direction
        if 0 <= target < len(segs):
            segs[idx], segs[target] = segs[target], segs[idx]
            self._refresh_cards()
            self._schedule_save()

    def _save_text(self, seg: MediaSegment, widget: tk.Text):
        new_text = widget.get("1.0", "end-1c")
        if new_text != seg.text:
            seg.text = new_text
            self._schedule_save()

    def _pick_image(self, seg: MediaSegment):
        path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                       ("All files", "*.*")])
        if path:
            seg.image_path = path
            self._refresh_cards()
            self._schedule_save()

    def _clear_image(self, seg: MediaSegment):
        seg.image_path = None
        self._refresh_cards()
        self._schedule_save()

    def _pick_audio(self, seg: MediaSegment):
        path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.aac"),
                       ("All files", "*.*")])
        if path:
            seg.audio_path = path
            self._refresh_cards()
            self._schedule_save()

    # ── Import ──────────────────────────────────────────────────────────────

    def _import_batch(self, kind: str):
        ext_map = {
            "text":  (_TEXT_EXTS, "Text files", "*.txt"),
            "audio": (_AUDIO_EXTS, "Audio files", "*.mp3 *.wav *.m4a *.aac"),
            "image": (_IMAGE_EXTS, "Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
        }
        exts, desc, pattern = ext_map[kind]

        mode = messagebox.askyesnocancel(
            tr("composer.import_how_title"),
            tr("composer.import_how_msg"))
        if mode is None:
            return
        if mode:  # Folder
            folder = filedialog.askdirectory(title=tr("composer.import_folder_title"))
            if not folder:
                return
            files = _list_folder(folder, exts)
        else:
            selected = filedialog.askopenfilenames(
                filetypes=[(desc, pattern), ("All files", "*.*")])
            if not selected:
                return
            files = _sorted_by_basename(list(selected))

        if not files:
            messagebox.showinfo(tr("composer.title"), tr("composer.info_no_files"))
            return

        segs = self._project.segments
        for i, fpath in enumerate(files):
            if i >= len(segs):
                segs.append(MediaSegment.new())
            seg = segs[i]
            if kind == "text":
                try:
                    seg.text = _read_text_file(fpath)
                except Exception as e:
                    self.log_error(f"Read text {fpath} failed: {e}")
            elif kind == "audio":
                seg.audio_path = fpath
            elif kind == "image":
                seg.image_path = fpath

        self._refresh_cards()
        self._schedule_save()
        self.log(f"Imported {len(files)} {kind} file(s).")

    # ── TTS ────────────────────────────────────────────────────────────────

    def _generate_audio_single(self, seg: MediaSegment):
        if not seg.text.strip():
            messagebox.showwarning(tr("composer.title"), tr("composer.warn_no_text"))
            return
        voice_id = self._voice_var.get().strip()
        if not voice_id:
            messagebox.showwarning(tr("composer.title"), tr("composer.warn_no_voice"))
            return
        if self._working:
            return
        self._working = True
        self.set_busy()
        threading.Thread(target=self._tts_worker, args=([seg], voice_id),
                         daemon=True).start()

    def _generate_all_audio(self):
        missing = [s for s in self._project.segments
                   if s.text.strip()
                   and (not s.audio_path or not os.path.isfile(s.audio_path))]
        if not missing:
            messagebox.showinfo(tr("composer.title"), tr("composer.info_no_missing"))
            return
        voice_id = self._voice_var.get().strip()
        if not voice_id:
            messagebox.showwarning(tr("composer.title"), tr("composer.warn_no_voice"))
            return
        if self._working:
            return
        self._working = True
        self.set_busy()
        threading.Thread(target=self._tts_worker, args=(missing, voice_id),
                         daemon=True).start()

    def _tts_worker(self, segments: list[MediaSegment], voice_id: str):
        audio_dir = user_data.path("audio")
        os.makedirs(audio_dir, exist_ok=True)
        try:
            for i, seg in enumerate(segments):
                self.log(f"TTS [{i + 1}/{len(segments)}] {seg.id[:8]}…")
                out = os.path.join(audio_dir, f"{seg.id}.mp3")
                _tts.synthesize_text(seg.text, out, voice_id=voice_id)
                seg.audio_path = out
            self.master.after(0, self._refresh_cards)
            self._schedule_save()
            self.set_done()
            self.log(f"TTS done for {len(segments)} segment(s).")
        except Exception as e:
            self.set_error(f"TTS failed: {e}")
        finally:
            self._working = False

    # ── Composition ─────────────────────────────────────────────────────────

    def _start_compose(self):
        segs = self._project.segments
        if not segs:
            messagebox.showwarning(tr("composer.title"), tr("composer.warn_no_segments"))
            return
        missing = [i + 1 for i, s in enumerate(segs)
                   if not s.audio_path or not os.path.isfile(s.audio_path)]
        if missing:
            idxs = ", ".join(str(i) for i in missing[:8])
            if not messagebox.askyesno(
                    tr("composer.title"),
                    tr("composer.ask_missing_audio").format(idxs=idxs)):
                return

        out_path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All files", "*.*")],
            initialfile="composer_output.mp4")
        if not out_path:
            return
        self._project.output_path = out_path

        if self._working:
            return
        self._working = True
        self.set_busy()
        threading.Thread(target=self._compose_worker, daemon=True).start()

    def _compose_worker(self):
        proj = self._project
        tmp_dir = tempfile.mkdtemp(prefix="vc_composer_")
        tmp_videos: list[str] = []

        black_frame = None
        if _PIL_OK:
            black_frame = os.path.join(tmp_dir, "__black.png")
            Image.new("RGB", proj.resolution, (0, 0, 0)).save(black_frame)

        try:
            for i, seg in enumerate(proj.segments):
                if not seg.audio_path or not os.path.isfile(seg.audio_path):
                    self.log(f"Skip segment {i + 1}: missing audio")
                    continue

                image = seg.image_path if (
                    seg.image_path and os.path.isfile(seg.image_path)
                ) else black_frame
                if not image:
                    self.log(f"Skip segment {i + 1}: no image (PIL missing)")
                    continue

                out_mp4 = os.path.join(tmp_dir, f"{i:04d}.mp4")
                self.log(f"Composing #{i + 1}/{len(proj.segments)}…")
                _vcompose.compose_chapter(
                    image=image,
                    audio=seg.audio_path,
                    srt=None,
                    output=out_mp4,
                    width=proj.resolution[0],
                    height=proj.resolution[1],
                )
                tmp_videos.append(out_mp4)

            if not tmp_videos:
                raise RuntimeError("No segments composed — check audio files.")

            self.log("Concatenating segments…")
            _vconcat.concat_videos(tmp_videos, proj.output_path)
            self.log(f"Done → {proj.output_path}")
            self.set_done()
            self.master.after(
                0, lambda: messagebox.showinfo(
                    tr("composer.title"),
                    tr("composer.info_done").format(path=proj.output_path)))
        except Exception as e:
            self.set_error(f"Compose failed: {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            self._working = False

    # ── Project Persistence ─────────────────────────────────────────────────

    def _schedule_save(self):
        if self._save_timer is not None:
            try:
                self.master.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.master.after(1500, self._do_save)

    def _do_save(self):
        self._save_timer = None
        try:
            os.makedirs(os.path.dirname(_AUTOSAVE_PATH), exist_ok=True)
            self._project.voice_id = self._voice_var.get()
            self._project.save(_AUTOSAVE_PATH)
        except Exception as e:
            self.log_error(f"Auto-save failed: {e}")

    def _try_restore(self):
        if not os.path.isfile(_AUTOSAVE_PATH):
            return
        try:
            preview = ComposerProject.load(_AUTOSAVE_PATH)
        except Exception:
            return
        if not preview.segments:
            return
        if messagebox.askyesno(
                tr("composer.title"),
                tr("composer.ask_restore").format(n=len(preview.segments))):
            self._project = preview
            self._voice_var.set(self._project.voice_id)
            self._refresh_cards()
