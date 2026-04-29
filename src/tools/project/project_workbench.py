"""
Project Workbench — manifest editor + scheduler.

Acts as a visual editor over `<project>/.videocraft/manifests/<basename>.json`:
left panel lists manifests (with New / Delete), right panel renders one
StepCard per pipeline step with editable fields. Unknown fields are preserved
verbatim and shown read-only in each card's "raw" section so the workbench
never silently destroys hand-written data.

A3 decision: only the workbench writes to manifests. Tools opened from the
regular menu remain manifest-unaware.

M2 scope: Step 1 (download), Step 1.5 (segment select — single start/end),
Step 2 (ASR) are runnable end-to-end. Other steps are editor-only.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from tools.base import ToolBase
from i18n import tr
from project import Project
from core.asr import transcribe_audio
from core.translate import SUPPORTED_LANGUAGES, translate_srt_file
from core.video_ops import extract_clip
from core.burn_subs import burn_subtitles
from core.srt_ops import generate_subtitle_pack, write_subtitle_pack
from core.segment_model import load_from_file as load_segments_file
from core.video_concat import split_segments
from core.video_split import SplitMode
from core import burn_presets


# ── Burn preset bridge ───────────────────────────────────────────────────────
# Translates legacy subtitle_tool's preset schema to/from workbench step4_burn
# fields so that hard-won presets in ~/.videocraft/presets/subtitle_burn.json
# are usable directly. Legacy field names are kept in the preset store
# (cross-tool compatibility); workbench uses its own names internally.

_PRESET_TO_WB = {
    "watermark_text":          "wm_text",
    "watermark_color":         "wm_text_color",
    "watermark_fontsize":      "wm_text_fontsize",
    "watermark_txt_alpha":     "wm_text_alpha",
    "watermark_img_path":      "wm_image_path",
    "watermark_img_scale":     "wm_image_scale",
    "watermark_img_alpha":     "wm_image_alpha",
    "watermark_date_color":    "date_color",
    "watermark_date_fontsize": "date_fontsize",
    "watermark_date_alpha":    "date_alpha",
    "sub1_fontsize":   "sub1_fontsize",
    "sub1_color":      "sub1_color",
    "sub2_fontsize":   "sub2_fontsize",
    "sub2_color":      "sub2_color",
    "split_sub1":      "sub1_split",
    "sub1_max_chars":  "sub1_max_chars",
    "sub1_is_chinese": "sub1_is_chinese",
    "split_sub2":      "sub2_split",
    "sub2_max_chars":  "sub2_max_chars",
    "sub2_is_chinese": "sub2_is_chinese",
    "orientation":     "orientation",
    "encode_preset":   "encode_preset",
}
_WB_TO_PRESET = {v: k for k, v in _PRESET_TO_WB.items()}


def _apply_preset_to_burn(preset: dict, burn: dict) -> dict:
    """Merge a preset dict into a step4_burn dict. Returns the burn dict
    (mutated). Honors legacy "show" toggles by clearing the corresponding
    workbench field when False — workbench uses empty-string-as-disabled."""
    for pkey, wkey in _PRESET_TO_WB.items():
        if pkey in preset:
            burn[wkey] = preset[pkey]
    # Master toggles → empty-string convention
    show_wm = preset.get("watermark_show", True)
    wm_type = preset.get("watermark_type", "image")
    if not show_wm:
        burn["wm_text"] = ""
        burn["wm_image_path"] = ""
    else:
        if wm_type == "image":
            burn["wm_text"] = ""        # image mode hides text
        else:
            burn["wm_image_path"] = ""  # text mode hides image
    if not preset.get("watermark_show_date", False):
        burn["date_text"] = ""
    return burn


def _burn_to_preset(burn: dict) -> dict:
    """Inverse: build a preset dict from current step4_burn fields. Derives
    legacy 'show' toggles from the empty-string convention."""
    out: dict = {}
    for wkey, pkey in _WB_TO_PRESET.items():
        if wkey in burn:
            out[pkey] = burn[wkey]
    has_text = bool(str(burn.get("wm_text", "") or "").strip())
    has_img = bool(str(burn.get("wm_image_path", "") or "").strip())
    out["watermark_show"] = has_text or has_img
    out["watermark_type"] = "image" if has_img else "text"
    out["watermark_show_date"] = bool(str(burn.get("date_text", "") or "").strip())
    return out


# Lemonfox upload limit (and a generally safe ASR upload size).
_ASR_MAX_BYTES = 100 * 1024 * 1024
# Bitrate ladder used when the prepared mp3 is still over the size limit.
_AUDIO_BITRATE_LADDER = ["128k", "64k", "32k", "16k"]


def _video_duration_seconds(path: str) -> float:
    """ffprobe → duration in seconds. 0.0 if unreadable."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        return float(out.stdout.strip()) if out.returncode == 0 else 0.0
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return 0.0


def _ffmpeg_to_mp3(src: str, dst: str, bitrate: str) -> None:
    """Re-encode any audio/video to a mp3 at the given bitrate (mono, 22kHz).
    Mono + 22k is more than enough for ASR and roughly halves the bitrate
    again on top of the nominal value."""
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vn",
        "-ac", "1",
        "-ar", "22050",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        dst,
    ]
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-500:]}")


def _prep_audio_for_asr(src: str, dst: str, on_status) -> str:
    """Produce an mp3 ≤ _ASR_MAX_BYTES suitable for ASR upload.

    Always re-encodes through ffmpeg (even mp3 input) — that way the size
    is predictable and we don't depend on whatever bitrate the source
    came at. Walks the bitrate ladder until the file fits."""
    last_err = None
    for br in _AUDIO_BITRATE_LADDER:
        on_status(tr("tool.project_workbench.status.audio_prep_encoding", br=br))
        try:
            _ffmpeg_to_mp3(src, dst, br)
        except Exception as e:
            last_err = e
            continue
        size = os.path.getsize(dst)
        on_status(tr("tool.project_workbench.status.audio_prep_done",
                     br=br, mb=size // (1024 * 1024)))
        if size <= _ASR_MAX_BYTES:
            return dst
    if last_err:
        raise last_err
    raise RuntimeError(
        f"Audio still over {_ASR_MAX_BYTES // (1024*1024)}MB at lowest "
        f"bitrate ({_AUDIO_BITRATE_LADDER[-1]}); split the source first")


# ── Styling ──────────────────────────────────────────────────────────────────
# All colors / fonts go through this dict so they can be tweaked centrally
# without hunting down literals scattered through widget builders.

S = {
    "canvas_bg":   "#eef1f6",
    "card_bg":     "#ffffff",
    "card_border": "#cbd5e1",
    "header_bg":   "#f1f5f9",   # card title strip
    "section_bg":  "#f8fafc",   # section header strip (slight tint)
    "section_rule":"#94a3b8",   # divider above each section
    "label_fg":    "#475569",
    "value_fg":    "#0f172a",
    "raw_bg":      "#f1f5f9",
    "raw_fg":      "#334155",
    "section_fg":  "#64748b",
    "dirty_fg":    "#d97706",
    "title_font":   ("Segoe UI", 12, "bold"),
    "label_font":   ("Segoe UI", 9),
    "value_font":   ("Segoe UI", 10),
    "section_font": ("Segoe UI", 9, "italic"),
    "section_header_font": ("Segoe UI", 10, "bold"),
    "mono_font":    ("Consolas", 9),
}


# ── Step config ──────────────────────────────────────────────────────────────

_STEPS: list[tuple[str, str]] = [
    ("step1_download",  "tool.project_workbench.step.download"),
    ("step1_5_select",  "tool.project_workbench.step.select"),
    ("step2_asr",       "tool.project_workbench.step.asr"),
    ("step3_translate", "tool.project_workbench.step.translate"),
    ("step4_burn",      "tool.project_workbench.step.burn"),
    ("step5_pack",      "tool.project_workbench.step.pack"),
    ("step6_split",     "tool.project_workbench.step.split"),
]

# Display number for each step — 1.5 is intentionally not in the natural order,
# so we hard-map labels here instead of using enumerate().
_STEP_DISPLAY_NUM: dict[str, str] = {
    "step1_download":  "1",
    "step1_5_select":  "2",
    "step2_asr":       "3",
    "step3_translate": "4",
    "step4_burn":      "5",
    "step5_pack":      "6",
    "step6_split":     "7",
}

# Known fields (rendered with widgets). Anything else lands in raw section.
_KNOWN_FIELDS: dict[str, list[str]] = {
    "step1_download":  ["enabled", "status", "source", "output"],
    "step1_5_select":  ["enabled", "status", "source", "start", "end", "output"],
    "step2_asr":       ["enabled", "status", "language", "source", "output"],
    "step3_translate": ["enabled", "status", "source_lang", "targets",
                        "source_srt", "output"],
    # step4_burn fields are rendered with section headers (see _build_step_card
    # special case). The order here matches the section grouping.
    "step4_burn":      ["enabled", "status", "source_video", "orientation",
                        "sub1_path", "sub1_fontsize", "sub1_color",
                        "sub1_split", "sub1_max_chars", "sub1_is_chinese",
                        "sub2_path", "sub2_fontsize", "sub2_color",
                        "sub2_split", "sub2_max_chars", "sub2_is_chinese",
                        "wm_text", "wm_text_color", "wm_text_fontsize", "wm_text_alpha",
                        "wm_image_path", "wm_image_scale", "wm_image_alpha",
                        "date_text", "date_color", "date_fontsize", "date_alpha",
                        "encode_preset", "output"],
    "step5_pack":      ["enabled", "status", "source_srt", "output"],
    "step6_split":     ["enabled", "status", "source_video", "segments_file",
                        "split_mode", "output"],
}

# Field type per (step, field). Drives widget choice in _add_field.
_FIELD_TYPE: dict[tuple[str, str], str] = {
    ("step1_download", "source"):        "url_or_path",
    ("step1_download", "output"):        "readonly_list",
    ("step1_5_select", "source"):        "filepath",
    ("step1_5_select", "start"):         "time",
    ("step1_5_select", "end"):           "time",
    ("step1_5_select", "output"):        "readonly_list",
    ("step2_asr", "language"):           "lang",
    ("step2_asr", "source"):             "filepath",
    ("step2_asr", "output"):             "readonly_list",
    ("step3_translate", "source_lang"):  "lang",
    ("step3_translate", "targets"):      "lang_one_list",
    ("step3_translate", "source_srt"):   "filepath",
    ("step3_translate", "output"):       "readonly_list",
    ("step4_burn", "source_video"):      "filepath",
    ("step4_burn", "orientation"):       "preset",
    ("step4_burn", "sub1_path"):         "filepath",
    ("step4_burn", "sub1_fontsize"):     "int",
    ("step4_burn", "sub1_color"):        "color",
    ("step4_burn", "sub1_split"):        "bool",
    ("step4_burn", "sub1_max_chars"):    "int",
    ("step4_burn", "sub1_is_chinese"):   "bool",
    ("step4_burn", "sub2_path"):         "filepath",
    ("step4_burn", "sub2_fontsize"):     "int",
    ("step4_burn", "sub2_color"):        "color",
    ("step4_burn", "sub2_split"):        "bool",
    ("step4_burn", "sub2_max_chars"):    "int",
    ("step4_burn", "sub2_is_chinese"):   "bool",
    ("step4_burn", "wm_text"):           "string",
    ("step4_burn", "wm_text_color"):     "color",
    ("step4_burn", "wm_text_fontsize"):  "int",
    ("step4_burn", "wm_text_alpha"):     "int",
    ("step4_burn", "wm_image_path"):     "filepath",
    ("step4_burn", "wm_image_scale"):    "float",
    ("step4_burn", "wm_image_alpha"):    "int",
    ("step4_burn", "date_text"):         "date",
    ("step4_burn", "date_color"):        "color",
    ("step4_burn", "date_fontsize"):     "int",
    ("step4_burn", "date_alpha"):        "int",
    ("step4_burn", "encode_preset"):     "preset",
    ("step4_burn", "output"):            "readonly_list",
    ("step5_pack", "source_srt"):        "filepath",
    ("step5_pack", "output"):            "readonly_list",
    ("step6_split", "source_video"):     "filepath",
    ("step6_split", "segments_file"):    "filepath",
    ("step6_split", "split_mode"):       "preset",
    ("step6_split", "output"):           "readonly_list",
}

# Range / default config for int / float / color / enum field types.
_FIELD_CONFIG: dict[tuple[str, str], dict] = {
    ("step4_burn", "sub1_fontsize"):    {"low": 8, "high": 128, "default": 32},
    ("step4_burn", "sub2_fontsize"):    {"low": 8, "high": 128, "default": 28},
    ("step4_burn", "sub1_color"):       {"default": "#FFFFFF"},
    ("step4_burn", "sub2_color"):       {"default": "#CCCCCC"},
    ("step4_burn", "sub1_max_chars"):   {"low": 6, "high": 120, "default": 18},
    ("step4_burn", "sub2_max_chars"):   {"low": 6, "high": 120, "default": 42},
    ("step4_burn", "sub1_split"):       {"default": True},
    ("step4_burn", "sub2_split"):       {"default": True},
    ("step4_burn", "sub1_is_chinese"):  {"default": True},
    ("step4_burn", "sub2_is_chinese"):  {"default": False},
    ("step4_burn", "wm_text_color"):    {"default": "#FFFFFF"},
    ("step4_burn", "wm_text_fontsize"): {"low": 8, "high": 128, "default": 28},
    ("step4_burn", "wm_text_alpha"):    {"low": 0, "high": 100, "default": 80},
    ("step4_burn", "wm_image_scale"):   {"low": 0.05, "high": 0.5,
                                          "step": 0.05, "default": 0.1},
    ("step4_burn", "wm_image_alpha"):   {"low": 0, "high": 100, "default": 80},
    ("step4_burn", "date_color"):       {"default": "#FFFFFF"},
    ("step4_burn", "date_fontsize"):    {"low": 8, "high": 128, "default": 24},
    ("step4_burn", "date_alpha"):       {"low": 0, "high": 100, "default": 80},
    ("step4_burn", "encode_preset"):    {"choices": ["ultrafast", "superfast",
                                                     "veryfast", "faster",
                                                     "fast", "medium"],
                                          "default": "veryfast"},
    ("step4_burn", "orientation"):      {"choices": ["auto", "horizontal", "vertical"],
                                          "default": "auto"},
    ("step6_split", "split_mode"):      {"choices": ["keyframe_snap", "fast", "accurate"],
                                          "default": "keyframe_snap"},
}

# Inline hints rendered under specific fields to explain auto-chain behavior.
# Without this, users see empty filepath fields and worry the chain won't
# actually fill them at run time.
_FIELD_HINTS: dict[tuple[str, str], str] = {
    ("step2_asr", "source"):           "tool.project_workbench.hint.chain_video",
    ("step3_translate", "source_srt"): "tool.project_workbench.hint.chain_srt",
    ("step4_burn", "source_video"):    "tool.project_workbench.hint.chain_video",
    ("step4_burn", "sub1_path"):       "tool.project_workbench.hint.burn_sub1",
    ("step4_burn", "sub2_path"):       "tool.project_workbench.hint.burn_sub2",
    ("step5_pack", "source_srt"):      "tool.project_workbench.hint.chain_srt",
    ("step6_split", "source_video"):   "tool.project_workbench.hint.chain_video",
    ("step6_split", "segments_file"):  "tool.project_workbench.hint.chain_segments",
}


# Section structure for step4_burn (very long card — broken into groups for
# readability). Each entry: (section_label_key, [field_names_in_order]).
_BURN_SECTIONS = [
    ("tool.project_workbench.section.video",
     ["source_video", "orientation"]),
    ("tool.project_workbench.section.sub1",
     ["sub1_path", "sub1_fontsize", "sub1_color",
      "sub1_split", "sub1_max_chars", "sub1_is_chinese"]),
    ("tool.project_workbench.section.sub2",
     ["sub2_path", "sub2_fontsize", "sub2_color",
      "sub2_split", "sub2_max_chars", "sub2_is_chinese"]),
    ("tool.project_workbench.section.wm_text",
     ["wm_text", "wm_text_color", "wm_text_fontsize", "wm_text_alpha"]),
    ("tool.project_workbench.section.wm_image",
     ["wm_image_path", "wm_image_scale", "wm_image_alpha"]),
    ("tool.project_workbench.section.date",
     ["date_text", "date_color", "date_fontsize", "date_alpha"]),
    ("tool.project_workbench.section.encode",
     ["encode_preset"]),
    ("tool.project_workbench.section.output",
     ["output"]),
]

_STATUS_VALUES = ["pending", "running", "done", "failed"]

# Steps that can be run from the workbench in M2.
_RUNNABLE_STEPS = {"step1_download", "step1_5_select", "step2_asr",
                   "step3_translate", "step4_burn", "step5_pack", "step6_split"}

def _parse_hms(s: str) -> tuple[int, int, int]:
    """Parse 'HH:MM:SS' (or sloppy variants) → (h, m, s). Returns (0,0,0) on
    junk input — Spinbox callers will overwrite with the clamped value."""
    parts = (s or "").strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]), int(parts[1]), int(float(parts[2]))
        if len(parts) == 2:
            return 0, int(parts[0]), int(float(parts[1]))
        if len(parts) == 1 and parts[0]:
            sec = int(float(parts[0]))
            return sec // 3600, (sec % 3600) // 60, sec % 60
    except ValueError:
        pass
    return 0, 0, 0


_LANG_CHOICES: list[tuple[str, str]] = [
    (iso, f"{iso} — {names[0]}") for iso, names in SUPPORTED_LANGUAGES.items()
]
_LANG_DISPLAY_TO_ISO = {disp: iso for iso, disp in _LANG_CHOICES}
_LANG_ISO_TO_DISPLAY = {iso: disp for iso, disp in _LANG_CHOICES}


class ProjectWorkbenchApp(ToolBase):
    def __init__(self, master, initial_file: str | None = None,
                 initial_basename: str | None = None):
        self.master = master
        master.title(tr("tool.project_workbench.title"))
        master.geometry("1100x720")

        self.project: Project | None = None
        self._buffer: dict | None = None
        self._current_basename: str | None = None
        self._dirty: bool = False
        self._busy: bool = False
        self._current_step: str | None = None

        self._field_vars: list = []
        self._suppress_dirty: bool = False
        # Per-step Run buttons populated by _build_step_card.
        self._run_buttons: dict[str, tk.Button] = {}
        # Run-all chain queue. Non-empty means we're running multiple steps;
        # _finish_step pops the next one on success and aborts on failure.
        self._chain: list[str] = []

        self._build_ui()

        if initial_file and os.path.isdir(initial_file):
            self._load_project(initial_file)
        if initial_basename:
            self.load_manifest(initial_basename)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Hub-embedded layout: a single column. Manifest list / new / delete
        # live in the Hub sidebar's "Project" tab; this widget is the editor
        # surface only — title bar, status banner, scrollable cards.
        m = self.master
        m.columnconfigure(0, weight=1)
        m.rowconfigure(1, weight=1)

        top = tk.Frame(m)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        top.columnconfigure(1, weight=1)
        tk.Label(top, text=tr("tool.project_workbench.label_project")).grid(
            row=0, column=0, sticky="w")
        self._project_var = tk.StringVar(value=tr("tool.project_workbench.no_project"))
        tk.Label(top, textvariable=self._project_var, fg="#555", anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        # Status var still drives the banner. When embedded, no extra
        # bottom-of-frame status label — the Hub log panel covers that role.
        self._status_var = tk.StringVar(value="")

        right = tk.Frame(m)
        right.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        self._build_right_panel(right)
        self._status_var.trace_add(
            "write", lambda *_: self._banner_var.set(self._status_var.get()))

    def _build_right_panel(self, right) -> None:
        tb = tk.Frame(right)
        tb.pack(fill="x", padx=8, pady=(4, 4))
        self._title_var = tk.StringVar(value=tr("tool.project_workbench.select_hint"))
        tk.Label(tb, textvariable=self._title_var, font=("Segoe UI", 12, "bold"),
                 anchor="w").pack(side="left", fill="x", expand=True)
        self._dirty_lbl = tk.Label(tb, text="", fg=S["dirty_fg"],
                                   font=("Segoe UI", 9, "bold"))
        self._dirty_lbl.pack(side="left", padx=(8, 0))
        self._save_btn = tk.Button(tb, text=tr("tool.project_workbench.save"),
                                   command=self._on_save, state="disabled")
        self._save_btn.pack(side="right", padx=(4, 0))
        self._reload_btn = tk.Button(tb, text=tr("tool.project_workbench.reload"),
                                     command=self._on_reload, state="disabled")
        self._reload_btn.pack(side="right")
        self._run_all_btn = tk.Button(tb, text=tr("tool.project_workbench.run_all"),
                                      command=self._on_run_all, state="disabled",
                                      bg="#2563eb", fg="white", activebackground="#1d4ed8",
                                      activeforeground="white", relief="flat", padx=10)
        self._run_all_btn.pack(side="right", padx=(0, 8))

        # Prominent status banner (above the scrollable cards).
        banner = tk.Frame(right, bg="#eff6ff", height=36)
        banner.pack(fill="x", padx=8, pady=(2, 4))
        banner.pack_propagate(False)
        self._banner_var = tk.StringVar(value="")
        self._banner_lbl = tk.Label(banner, textvariable=self._banner_var,
                                    bg="#eff6ff", fg="#1d4ed8",
                                    font=("Segoe UI", 10, "bold"),
                                    anchor="w", padx=10)
        self._banner_lbl.pack(fill="both", expand=True)

        scroll_wrap = tk.Frame(right, bd=1, relief="sunken")
        scroll_wrap.pack(fill="both", expand=True, padx=8, pady=4)
        canvas = tk.Canvas(scroll_wrap, highlightthickness=0, bg=S["canvas_bg"])
        vsb = ttk.Scrollbar(scroll_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._cards_canvas = canvas
        self._cards_frame = tk.Frame(canvas, bg=S["canvas_bg"])
        self._cards_window = canvas.create_window((0, 0), window=self._cards_frame,
                                                   anchor="nw")
        self._cards_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(self._cards_window, width=e.width)
        )
        # Mousewheel: only scroll the form when (a) the pointer is over the
        # canvas region (Enter/Leave toggles a global binding) and (b) the
        # event widget isn't an interactive control that owns its own wheel
        # behaviour — without this guard, hovering a combobox/spinbox while
        # scrolling drags the whole form along, which is jarring.
        _NO_FORM_SCROLL = (ttk.Combobox, tk.Spinbox, ttk.Spinbox, tk.Text)

        def _on_wheel(e):
            if isinstance(e.widget, _NO_FORM_SCROLL):
                return
            canvas.yview_scroll(int(-e.delta / 120), "units")

        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

    # ── Project / manifest loading ───────────────────────────────────────────

    def _load_project(self, folder: str) -> None:
        """Legacy bootstrap when the workbench is launched standalone with an
        initial folder (no Hub driving it). Hub-managed instances use
        set_project() instead."""
        try:
            self.set_project(Project.open(folder))
        except Exception as e:
            self.set_error(f"Open project failed: {e}")

    def set_project(self, project: "Project | None") -> None:
        """Hub calls this when the active project changes (open / close /
        switch). Clears any open manifest from the previous project."""
        self.project = project
        self._project_var.set(project.folder if project else
                              tr("tool.project_workbench.no_project"))
        self.load_manifest(None)

    def load_manifest(self, basename: "str | None") -> bool:
        """Public API used by Hub when the sidebar selects a manifest. Pass
        None to enter the empty state (e.g. project closed). Returns False
        if the user cancelled because of unsaved dirty buffer."""
        if basename == self._current_basename:
            return True
        if self._dirty and self._current_basename is not None:
            choice = self._ask_save_discard_cancel()
            if choice is None:
                return False
            if choice is True and not self._save_buffer():
                return False
        if basename is None or self.project is None:
            self._clear_right_panel()
            return True
        data = self.project.load_manifest(basename)
        if data is None:
            self.set_error(f"Failed to load manifest: {basename}")
            return False
        self._current_basename = basename
        self._buffer = data
        self._dirty = False
        self._update_dirty_indicator()
        self._title_var.set(f"basename: {basename}")
        self._render_step_cards()
        self._save_btn.config(state="normal")
        self._reload_btn.config(state="normal")
        return True

    def _clear_right_panel(self) -> None:
        self._current_basename = None
        self._buffer = None
        self._dirty = False
        self._update_dirty_indicator()
        self._title_var.set(tr("tool.project_workbench.select_hint"))
        self._clear_step_cards()
        self._save_btn.config(state="disabled")
        self._reload_btn.config(state="disabled")


    # ── Step card rendering ──────────────────────────────────────────────────

    def _clear_step_cards(self) -> None:
        for child in self._cards_frame.winfo_children():
            child.destroy()
        self._field_vars = []
        self._run_buttons = {}

    def _render_step_cards(self) -> None:
        self._clear_step_cards()
        if self._buffer is None:
            return
        # Seed step4_burn with the last-used preset when the user newly
        # enabled it but hasn't filled in any fields. Saves them from
        # re-tuning every preset value on every new manifest. Only happens
        # before the dirty-suppression block so it correctly marks dirty.
        self._maybe_seed_burn_from_preset()
        self._suppress_dirty = True
        try:
            for step_key, label_key in _STEPS:
                self._build_step_card(step_key, label_key)
        finally:
            self._suppress_dirty = False
        # Refresh all run buttons after populating
        for sk in _RUNNABLE_STEPS:
            self._refresh_run_state(sk)
        self._refresh_run_all_state()
        self._cards_canvas.yview_moveto(0)

    def _build_step_card(self, step_key: str, label_key: str) -> None:
        assert self._buffer is not None
        step = self._buffer.setdefault(step_key, {"enabled": False, "status": "pending"})

        # Outer card frame; running step gets a blue border for at-a-glance
        # progress visibility, done gets a subtle green tint.
        status = step.get("status", "pending")
        if status == "running":
            border, thickness = "#2563eb", 2
        elif status == "done":
            border, thickness = "#86efac", 1
        elif status == "failed":
            border, thickness = "#ef4444", 1
        else:
            border, thickness = S["card_border"], 1
        card = tk.Frame(self._cards_frame, bg=S["card_bg"],
                        highlightbackground=border,
                        highlightthickness=thickness)
        card.pack(fill="x", padx=10, pady=6)

        # Header bar: numbered title + Run button on a tinted strip
        header = tk.Frame(card, bg=S["header_bg"])
        header.pack(fill="x")
        num = _STEP_DISPLAY_NUM.get(step_key, "")
        title_text = (f"Step {num} · {tr(label_key)}"
                      if num else tr(label_key))
        tk.Label(header, text=title_text, bg=S["header_bg"],
                 fg=S["value_fg"], font=S["title_font"], anchor="w").pack(
            side="left", padx=12, pady=8)
        if step_key in _RUNNABLE_STEPS:
            run_label_key = {
                "step1_download":  "tool.project_workbench.run_download",
                "step1_5_select":  "tool.project_workbench.run_select",
                "step2_asr":       "tool.project_workbench.run_asr",
                "step3_translate": "tool.project_workbench.run_translate",
                "step4_burn":      "tool.project_workbench.run_burn",
                "step5_pack":      "tool.project_workbench.run_pack",
                "step6_split":     "tool.project_workbench.run_split",
            }[step_key]
            btn = tk.Button(header, text=tr(run_label_key),
                            command=lambda sk=step_key: self._on_run_step(sk))
            btn.pack(side="right", padx=10, pady=6)
            self._run_buttons[step_key] = btn

        # Subtle divider between header strip and body
        tk.Frame(card, bg=S["card_border"], height=1).pack(fill="x")

        # Body
        body = tk.Frame(card, bg=S["card_bg"])
        body.pack(fill="x", padx=10, pady=(6, 8))
        body.columnconfigure(1, weight=1)

        row = [0]
        def next_row() -> int:
            r = row[0]; row[0] += 1; return r

        # Common fields
        self._add_bool_field(body, next_row(), step_key, "enabled",
                             tr("tool.project_workbench.field.enabled"))
        self._add_enum_field(body, next_row(), step_key, "status",
                             tr("tool.project_workbench.field.status"),
                             _STATUS_VALUES)

        # Per-step known fields. step4_burn is special-cased with section
        # headers because of its 20+ fields; other steps render flat.
        known = _KNOWN_FIELDS.get(step_key, ["enabled", "status"])
        if step_key == "step4_burn":
            # Preset picker bar above all sections.
            preset_holder = tk.Frame(body, bg=S["card_bg"])
            preset_holder.grid(row=next_row(), column=0, columnspan=2,
                                sticky="ew", pady=(2, 4))
            self._build_burn_preset_picker(preset_holder)
            for section_label_key, section_fields in _BURN_SECTIONS:
                row[0] = self._add_section_header(body, row[0],
                                                   tr(section_label_key))
                for fname in section_fields:
                    if fname not in known:
                        continue
                    label = tr(f"tool.project_workbench.field.{fname}")
                    self._add_field(body, next_row(), step_key, fname, label)
        else:
            for fname in known:
                if fname in ("enabled", "status"):
                    continue
                label = tr(f"tool.project_workbench.field.{fname}")
                self._add_field(body, next_row(), step_key, fname, label)

        # Raw section: any unknown keys
        leftover = {k: v for k, v in step.items() if k not in known}
        if leftover:
            self._add_raw_section(body, next_row(), leftover)

    # ── Field widgets ────────────────────────────────────────────────────────

    def _label_cell(self, parent, r: int, label: str) -> None:
        tk.Label(parent, text=label, bg=S["card_bg"], fg=S["label_fg"],
                 font=S["label_font"], anchor="e").grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=2)

    def _add_field(self, parent, r: int, step_key: str, fname: str,
                   label: str) -> None:
        ftype = _FIELD_TYPE.get((step_key, fname), "string")
        if ftype == "lang":
            self._add_lang_field(parent, r, step_key, fname, label)
        elif ftype == "filepath":
            self._add_filepath_field(parent, r, step_key, fname, label)
        elif ftype == "readonly_list":
            self._add_readonly_list_field(parent, r, step_key, fname, label)
        elif ftype == "bool":
            self._add_bool_field(parent, r, step_key, fname, label)
        elif ftype == "time":
            self._add_time_field(parent, r, step_key, fname, label)
        elif ftype == "csv_iso":
            self._add_csv_iso_field(parent, r, step_key, fname, label)
        elif ftype == "lang_one_list":
            self._add_lang_one_list_field(parent, r, step_key, fname, label)
        elif ftype == "int":
            self._add_int_field(parent, r, step_key, fname, label)
        elif ftype == "float":
            self._add_float_field(parent, r, step_key, fname, label)
        elif ftype == "color":
            self._add_color_field(parent, r, step_key, fname, label)
        elif ftype == "date":
            self._add_date_field(parent, r, step_key, fname, label)
        elif ftype == "url_or_path":
            self._add_url_or_path_field(parent, r, step_key, fname, label)
        elif ftype == "preset":
            self._add_preset_field(parent, r, step_key, fname, label)
        else:
            self._add_string_field(parent, r, step_key, fname, label)

    def _add_bool_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        cfg = _FIELD_CONFIG.get((step_key, field), {})
        default = cfg.get("default", False)
        var = tk.BooleanVar(value=bool(step.get(field, default)))
        cb = tk.Checkbutton(parent, text=label, variable=var,
                            bg=S["card_bg"], fg=S["value_fg"],
                            activebackground=S["card_bg"],
                            font=S["value_font"], anchor="w")
        cb.grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_enum_field(self, parent, r: int, step_key: str, field: str,
                        label: str, choices: list[str]) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur = str(step.get(field, choices[0]))
        if cur not in choices:
            choices = [cur] + choices
        var = tk.StringVar(value=cur)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var, values=choices,
                          state="readonly", width=14, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_lang_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur_iso = step.get(field) or "auto"
        display = _LANG_ISO_TO_DISPLAY.get(cur_iso, cur_iso)
        var = tk.StringVar(value=display)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var,
                          values=[d for _, d in _LANG_CHOICES],
                          state="readonly", width=24, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        def on_write(*_):
            iso = _LANG_DISPLAY_TO_ISO.get(var.get(), var.get())
            self._on_field_change(step_key, field, iso)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_filepath_field(self, parent, r: int, step_key: str, field: str,
                            label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.StringVar(value=str(step.get(field, "")))
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        def browse():
            initial = var.get() or self._browse_initial_dir()
            if os.path.isfile(initial):
                initial = os.path.dirname(initial)
            path = filedialog.askopenfilename(initialdir=initial)
            if path:
                var.set(path)
        tk.Button(wrap, text=tr("tool.project_workbench.browse"),
                  command=browse).grid(row=0, column=1, padx=(4, 0))
        hint_key = _FIELD_HINTS.get((step_key, field))
        if hint_key:
            tk.Label(wrap, text=tr(hint_key), bg=S["card_bg"],
                     fg=S["section_fg"], font=S["section_font"],
                     anchor="w", justify="left").grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_time_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        """Three Spinboxes (HH MM SS) → "HH:MM:SS" string in the buffer.
        tkinter has no time picker; spinboxes make valid input the only
        possibility, so the user never has to wonder about the format."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        h, m, s = _parse_hms(str(step.get(field, "00:00:00")))
        h_var = tk.StringVar(value=f"{h:02d}")
        m_var = tk.StringVar(value=f"{m:02d}")
        s_var = tk.StringVar(value=f"{s:02d}")
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="w", pady=2)
        sb_kw = dict(width=3, font=S["mono_font"], justify="center", format="%02.0f")
        sh = tk.Spinbox(wrap, from_=0, to=23, textvariable=h_var, **sb_kw)
        sh.pack(side="left")
        tk.Label(wrap, text=":", bg=S["card_bg"], fg=S["value_fg"],
                 font=S["mono_font"]).pack(side="left")
        sm = tk.Spinbox(wrap, from_=0, to=59, textvariable=m_var, **sb_kw)
        sm.pack(side="left")
        tk.Label(wrap, text=":", bg=S["card_bg"], fg=S["value_fg"],
                 font=S["mono_font"]).pack(side="left")
        ss = tk.Spinbox(wrap, from_=0, to=59, textvariable=s_var, **sb_kw)
        ss.pack(side="left")
        tk.Label(wrap, text="  HH:MM:SS", bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"]).pack(side="left", padx=(6, 0))

        def update(*_):
            try:
                hv = max(0, min(23, int(h_var.get() or 0)))
                mv = max(0, min(59, int(m_var.get() or 0)))
                sv = max(0, min(59, int(s_var.get() or 0)))
            except ValueError:
                return
            value = f"{hv:02d}:{mv:02d}:{sv:02d}"
            self._on_field_change(step_key, field, value)
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        h_var.trace_add("write", update)
        m_var.trace_add("write", update)
        s_var.trace_add("write", update)
        self._field_vars.extend([h_var, m_var, s_var])

    def _add_lang_one_list_field(self, parent, r: int, step_key: str,
                                 field: str, label: str) -> None:
        """Single-language picker that stores the value as a list[str] of one
        ISO code (so the schema field stays list-shaped for forward compat
        with future multi-target support)."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur = step.get(field, [])
        cur_iso = (cur[0] if isinstance(cur, list) and cur else
                   (cur if isinstance(cur, str) else "auto"))
        display = _LANG_ISO_TO_DISPLAY.get(cur_iso, cur_iso)
        var = tk.StringVar(value=display)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var,
                          values=[d for _, d in _LANG_CHOICES],
                          state="readonly", width=24, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        def on_write(*_):
            iso = _LANG_DISPLAY_TO_ISO.get(var.get(), var.get())
            self._on_field_change(step_key, field, [iso] if iso else [])
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_int_field(self, parent, r: int, step_key: str, field: str,
                       label: str) -> None:
        assert self._buffer is not None
        cfg = _FIELD_CONFIG.get((step_key, field), {})
        low, high, default = cfg.get("low", 0), cfg.get("high", 200), cfg.get("default", 0)
        cur = int(self._buffer[step_key].get(field, default) or default)
        var = tk.IntVar(value=cur)
        self._label_cell(parent, r, f"{label}:")
        sb = tk.Spinbox(parent, from_=low, to=high, textvariable=var,
                        width=8, font=S["value_font"], justify="right")
        sb.grid(row=r, column=1, sticky="w", pady=2)
        def on_write(*_):
            try:
                self._on_field_change(step_key, field, int(var.get()))
            except (ValueError, tk.TclError):
                pass
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_float_field(self, parent, r: int, step_key: str, field: str,
                         label: str) -> None:
        assert self._buffer is not None
        cfg = _FIELD_CONFIG.get((step_key, field), {})
        low, high = cfg.get("low", 0.0), cfg.get("high", 1.0)
        step_v, default = cfg.get("step", 0.05), cfg.get("default", 0.0)
        cur = float(self._buffer[step_key].get(field, default) or default)
        var = tk.DoubleVar(value=cur)
        self._label_cell(parent, r, f"{label}:")
        sb = tk.Spinbox(parent, from_=low, to=high, increment=step_v,
                        format="%.2f", textvariable=var,
                        width=8, font=S["value_font"], justify="right")
        sb.grid(row=r, column=1, sticky="w", pady=2)
        def on_write(*_):
            try:
                self._on_field_change(step_key, field, float(var.get()))
            except (ValueError, tk.TclError):
                pass
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_color_field(self, parent, r: int, step_key: str, field: str,
                         label: str) -> None:
        """#RRGGBB hex entry with a colored swatch + native color picker.
        Click the swatch (or the … button) to open tkinter.colorchooser."""
        assert self._buffer is not None
        cfg = _FIELD_CONFIG.get((step_key, field), {})
        default = cfg.get("default", "#FFFFFF")
        cur = str(self._buffer[step_key].get(field, default) or default)
        var = tk.StringVar(value=cur)
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="w", pady=2)
        swatch = tk.Frame(wrap, width=18, height=18, bg=cur,
                          highlightbackground="#9ca3af", highlightthickness=1,
                          cursor="hand2")
        swatch.pack(side="left")
        swatch.pack_propagate(False)
        ent = tk.Entry(wrap, textvariable=var, width=10, font=S["mono_font"])
        ent.pack(side="left", padx=(6, 0))

        def pick_color(*_):
            try:
                initial = var.get().strip() or default
                _, hex_color = colorchooser.askcolor(
                    color=initial, parent=self.master, title=label)
            except tk.TclError:
                hex_color = None
            if hex_color:
                var.set(hex_color.upper())

        tk.Button(wrap, text="…", width=2, command=pick_color).pack(
            side="left", padx=(4, 0))
        # Click the swatch to open picker too.
        swatch.bind("<Button-1>", pick_color)

        def on_write(*_):
            v = var.get().strip()
            self._on_field_change(step_key, field, v)
            if len(v) == 7 and v.startswith("#"):
                try:
                    int(v[1:], 16)
                    swatch.config(bg=v)
                except (ValueError, tk.TclError):
                    pass
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_preset_field(self, parent, r: int, step_key: str, field: str,
                          label: str) -> None:
        assert self._buffer is not None
        cfg = _FIELD_CONFIG.get((step_key, field), {})
        choices = cfg.get("choices", [])
        default = cfg.get("default", choices[0] if choices else "")
        cur = str(self._buffer[step_key].get(field, default) or default)
        if cur not in choices and cur:
            choices = [cur] + list(choices)
        var = tk.StringVar(value=cur)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var, values=choices,
                          state="readonly", width=14, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        var.trace_add("write",
                      lambda *_: self._on_field_change(step_key, field, var.get()))
        self._field_vars.append(var)

    def _add_section_header(self, parent, r: int, label: str) -> int:
        """Draws a tinted band with a bold label. Returns next row index."""
        tk.Frame(parent, bg=S["section_rule"], height=2).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        band = tk.Frame(parent, bg=S["section_bg"])
        band.grid(row=r + 1, column=0, columnspan=2, sticky="ew",
                  pady=(0, 4))
        tk.Label(band, text=label, bg=S["section_bg"], fg=S["value_fg"],
                 font=S["section_header_font"], anchor="w").pack(
            side="left", padx=8, pady=3)
        return r + 2

    def _add_csv_iso_field(self, parent, r: int, step_key: str, field: str,
                           label: str) -> None:
        """List of ISO language codes shown as CSV in an Entry. Stored as a
        list[str] in the buffer. Empty entries are dropped."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur = step.get(field, [])
        if isinstance(cur, str):
            cur_str = cur
        else:
            cur_str = ", ".join(str(x) for x in (cur or []))
        var = tk.StringVar(value=cur_str)
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        tk.Label(wrap, text="  e.g.  zh, ja, fr",
                 bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"]).grid(row=0, column=1, padx=(6, 0))
        def on_write(*_):
            items = [tok.strip() for tok in var.get().split(",") if tok.strip()]
            self._on_field_change(step_key, field, items)
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_string_field(self, parent, r: int, step_key: str, field: str,
                          label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.StringVar(value=str(step.get(field, "")))
        self._label_cell(parent, r, f"{label}:")
        ent = tk.Entry(parent, textvariable=var, font=S["value_font"])
        ent.grid(row=r, column=1, sticky="ew", pady=2)
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_date_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        """Free-text date entry + 'Today' button + 'Clear' button. Stored as
        whatever string the user types (legacy field is freeform — could be
        '2026-04-29' or '2026年4月29日'). Empty string disables date overlay."""
        from datetime import date as _date
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.StringVar(value=str(step.get(field, "")))
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        tk.Button(wrap, text=tr("tool.project_workbench.date_today"),
                  command=lambda: var.set(_date.today().isoformat())).grid(
            row=0, column=1, padx=(4, 0))
        tk.Button(wrap, text=tr("tool.project_workbench.date_clear"),
                  command=lambda: var.set("")).grid(
            row=0, column=2, padx=(4, 0))
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_url_or_path_field(self, parent, r: int, step_key: str, field: str,
                               label: str) -> None:
        """Single entry that accepts either a URL (http/https) or a local file
        path. Browse button helps pick a local file. Worker dispatches based
        on the http/https prefix."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.StringVar(value=str(step.get(field, "")))
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        def browse():
            initial = self._browse_initial_dir()
            path = filedialog.askopenfilename(initialdir=initial)
            if path:
                var.set(path)
        tk.Button(wrap, text=tr("tool.project_workbench.browse"),
                  command=browse).grid(row=0, column=1, padx=(4, 0))
        tk.Label(wrap, text=tr("tool.project_workbench.hint.url_or_path"),
                 bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"], anchor="w", justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_readonly_list_field(self, parent, r: int, step_key: str, field: str,
                                 label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        items = step.get(field, []) or []
        if not isinstance(items, list):
            items = [str(items)]
        self._label_cell(parent, r, f"{label}:")
        if not items:
            tk.Label(parent, text="—", bg=S["card_bg"], fg="#9ca3af",
                     font=S["value_font"], anchor="w").grid(
                row=r, column=1, sticky="w", pady=2)
            return
        text = tk.Text(parent, height=min(len(items), 4), bg=S["raw_bg"],
                       fg=S["raw_fg"], relief="flat", wrap="none",
                       font=S["mono_font"], borderwidth=0)
        for it in items:
            text.insert("end", f"{it}\n")
        text.configure(state="disabled")
        text.grid(row=r, column=1, sticky="ew", pady=2)

    def _add_raw_section(self, parent, r: int, leftover: dict) -> None:
        sep = tk.Frame(parent, bg=S["card_border"], height=1)
        sep.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        tk.Label(parent, text=tr("tool.project_workbench.raw_fields"),
                 bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"], anchor="w").grid(
            row=r + 1, column=0, columnspan=2, sticky="w")
        text_widget = tk.Text(parent, height=min(8, max(2, len(leftover) + 1)),
                              bg=S["raw_bg"], fg=S["raw_fg"],
                              relief="flat", wrap="none",
                              font=S["mono_font"], borderwidth=0)
        text_widget.insert("1.0", json.dumps(leftover, ensure_ascii=False, indent=2))
        text_widget.configure(state="disabled")
        text_widget.grid(row=r + 2, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    # ── Buffer / dirty ───────────────────────────────────────────────────────

    def _on_field_change(self, step_key: str, field: str, value) -> None:
        if self._suppress_dirty or self._buffer is None:
            return
        step = self._buffer.setdefault(step_key, {})
        step[field] = value
        self._mark_dirty()
        # Field changes can flip Run All eligibility (e.g. user enables a
        # step or pastes a URL); refresh the umbrella button alongside
        # per-step buttons (which are refreshed by their own traces).
        self._refresh_run_all_state()
        # Cross-step visibility: enabling/disabling step1_download or
        # step1_5_select changes the resolved chain for downstream steps,
        # so refresh ALL runnable buttons, not just this step's.
        for sk in _RUNNABLE_STEPS:
            self._refresh_run_state(sk)

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_dirty_indicator()

    def _update_dirty_indicator(self) -> None:
        self._dirty_lbl.config(text=(tr("tool.project_workbench.dirty") if self._dirty else ""))

    def _ask_save_discard_cancel(self) -> bool | None:
        return messagebox.askyesnocancel(
            tr("tool.project_workbench.confirm_unsaved_title"),
            tr("tool.project_workbench.confirm_unsaved_msg").format(
                name=self._current_basename or "?"),
        )

    # ── Save / Reload ────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        self._save_buffer()

    def _save_buffer(self) -> bool:
        if self.project is None or self._buffer is None or self._current_basename is None:
            return False
        try:
            self.project.save_manifest(self._current_basename, self._buffer)
            self._dirty = False
            self._update_dirty_indicator()
            self._status_var.set(tr("tool.project_workbench.saved").format(
                name=self._current_basename))
            return True
        except Exception as e:
            self.set_error(f"Save failed: {e}")
            return False

    def _on_reload(self) -> None:
        if self._current_basename is None:
            return
        if self._dirty:
            if not messagebox.askyesno(
                tr("tool.project_workbench.confirm_reload_title"),
                tr("tool.project_workbench.confirm_reload_msg"),
            ):
                return
        # Force-reload bypassing the same-basename early-return + dirty check
        bn = self._current_basename
        self._dirty = False
        self._current_basename = None
        self.load_manifest(bn)

    # ── Hub-facing helpers ───────────────────────────────────────────────────

    @property
    def current_basename(self) -> "str | None":
        return self._current_basename

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def confirm_discard(self) -> bool:
        """Returns True if it's safe to navigate away from / mutate the
        currently open manifest. Either clean, or user chose Save (success)
        or Discard. Returns False on Cancel or save failure."""
        if not self._dirty or self._current_basename is None:
            return True
        choice = self._ask_save_discard_cancel()
        if choice is None:
            return False
        if choice is True:
            return self._save_buffer()
        # Discard branch — clear the dirty flag so subsequent load_manifest
        # doesn't re-prompt the user.
        self._dirty = False
        self._update_dirty_indicator()
        return True

    # ── Input resolution (auto-chain) ────────────────────────────────────────

    # Order of steps that produce media that downstream steps consume.
    _MEDIA_CHAIN = ["step1_download", "step1_5_select"]

    def _resolve_input(self, step_key: str) -> str | None:
        """Resolve the input file path for a runnable step.

        Resolution order:
          1. Explicit non-empty `source` on this step (manual override)
          2. Most recent prior step in _MEDIA_CHAIN that is enabled+done with
             output[0] populated
          3. None — caller must surface an error

        step1_download is the canonical seed (URL or local path); there is
        no top-level source fallback anymore.
        """
        if self._buffer is None:
            return None
        # 1) self override (e.g. step2_asr.source)
        own = str(self._buffer.get(step_key, {}).get("source", "")).strip()
        # step1_download.source IS the input itself, not a downstream override
        if own and step_key != "step1_download":
            return self._abspath(own)
        # 2) walk back through media chain (only steps strictly before this one)
        for sk in reversed(self._MEDIA_CHAIN):
            if sk == step_key:
                continue
            if self._step_index(sk) >= self._step_index(step_key):
                continue
            step = self._buffer.get(sk, {}) or {}
            if step.get("enabled") and step.get("status") == "done":
                outs = step.get("output", []) or []
                if outs:
                    return self._abspath(str(outs[0]))
        return None

    def _resolve_segments_file(self, step_key: str) -> str | None:
        """Find the segments .txt this step should consume.

        1. Explicit `segments_file` on this step (override)
        2. step5_pack output's `-segments.txt` when enabled+done
        3. None
        """
        if self._buffer is None:
            return None
        own = str(self._buffer.get(step_key, {}).get("segments_file", "")).strip()
        if own:
            return self._abspath(own)
        pack = self._buffer.get("step5_pack", {}) or {}
        if pack.get("enabled") and pack.get("status") == "done":
            for path in (pack.get("output", []) or []):
                if str(path).lower().endswith("-segments.txt"):
                    return self._abspath(str(path))
        return None

    def _resolve_video_input(self, step_key: str) -> str | None:
        """Like _resolve_input but reads `source_video` (used by step4_burn,
        which has both source_video and source_srt and can't reuse the
        generic `source` field name)."""
        if self._buffer is None:
            return None
        own = str(self._buffer.get(step_key, {}).get("source_video", "")).strip()
        if own:
            return self._abspath(own)
        return self._resolve_input(step_key)

    def _resolve_srt_input(self, step_key: str) -> str | None:
        """Find the SRT this step should consume.

        1. Explicit `source_srt` on this step (override)
        2. Most recent SRT producer strictly before this step (step3_translate
           preferred when done, otherwise step2_asr) — gives burn the
           translated SRT when translation has run, the original otherwise
        3. Top-level `source` if it points at a .srt file (lets users feed
           an existing SRT straight in without running ASR)
        4. None
        """
        if self._buffer is None:
            return None
        own = str(self._buffer.get(step_key, {}).get("source_srt", "")).strip()
        if own:
            return self._abspath(own)
        # Walk SRT producers from most-recent to least-recent, restricted to
        # steps strictly before step_key.
        srt_producers = ["step3_translate", "step2_asr"]
        my_idx = self._step_index(step_key)
        for sk in srt_producers:
            if self._step_index(sk) >= my_idx:
                continue
            step = self._buffer.get(sk, {}) or {}
            if step.get("enabled") and step.get("status") == "done":
                for path in (step.get("output", []) or []):
                    if str(path).lower().endswith(".srt"):
                        return self._abspath(str(path))
        return None

    @staticmethod
    def _step_index(step_key: str) -> int:
        for i, (sk, _) in enumerate(_STEPS):
            if sk == step_key:
                return i
        return 999

    def _abspath(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        if self.project is None:
            return path
        return os.path.join(self.project.folder, path)

    # ── Step run dispatch ────────────────────────────────────────────────────

    def _refresh_run_all_state(self) -> None:
        if self._buffer is None or self._busy:
            self._run_all_btn.config(state="disabled")
            return
        # Enable if at least one runnable enabled step is pending or failed.
        pending = [sk for sk in _RUNNABLE_STEPS
                   if (self._buffer.get(sk, {}) or {}).get("enabled")
                   and (self._buffer.get(sk, {}) or {}).get("status") in ("pending", "failed")]
        self._run_all_btn.config(state=("normal" if pending else "disabled"))

    def _on_run_all(self) -> None:
        if (self.project is None or self._buffer is None
                or self._current_basename is None or self._busy):
            return
        if self._dirty:
            if not messagebox.askyesno(
                tr("tool.project_workbench.confirm_save_before_run_title"),
                tr("tool.project_workbench.confirm_save_before_run_msg"),
            ):
                return
            if not self._save_buffer():
                return
        # Build queue in step order
        queue: list[str] = []
        for sk, _ in _STEPS:
            if sk not in _RUNNABLE_STEPS:
                continue
            step = self._buffer.get(sk, {}) or {}
            if step.get("enabled") and step.get("status") in ("pending", "failed"):
                queue.append(sk)
        if not queue:
            return
        self._chain = queue
        self._run_chain_next()

    def _run_chain_next(self) -> None:
        """Pop the next step off the chain and run it."""
        if not self._chain:
            return
        step_key = self._chain.pop(0)
        self._on_run_step(step_key)

    def _check_run_prereqs(self, step_key: str) -> str | None:
        """Return None if step is runnable, else a human-readable reason
        explaining what's blocking. Used by both _refresh_run_state (sets
        button state) and _on_run_step (shows messagebox to clarify when
        button was clicked while not runnable)."""
        if self._buffer is None:
            return "no manifest loaded"
        if self._busy:
            return "another step is currently running"
        step = self._buffer.get(step_key, {}) or {}
        if not bool(step.get("enabled")):
            return f"{step_key}.enabled is False"
        status = step.get("status")
        if status not in ("pending", "failed"):
            return (f"{step_key}.status = {status!r} (only 'pending' or "
                    f"'failed' can run; reset to 'pending' to re-run)")
        if step_key == "step1_download":
            src = str(step.get("source", "")).strip()
            if not src:
                return "step1_download.source is empty (URL or local path)"
            if not src.lower().startswith(("http://", "https://")):
                if not os.path.exists(src):
                    return f"local file not found: {src}"
        elif step_key == "step1_5_select":
            if str(step.get("start", "")) == str(step.get("end", "")):
                return "start == end (need a non-zero clip duration)"
            if self._resolve_input(step_key) is None:
                return ("no input video — set step1_download / step1_5_select"
                        ".source / top-level source")
        elif step_key == "step2_asr":
            if self._resolve_input(step_key) is None:
                return ("no input audio — set step1_download / "
                        "step1_5_select / step2_asr.source / top-level source")
        elif step_key == "step3_translate":
            if not (step.get("targets") or []):
                return "step3_translate.targets is empty"
            if self._resolve_srt_input(step_key) is None:
                return "no input SRT — run step2_asr or set step3_translate.source_srt"
        elif step_key == "step4_burn":
            if self._resolve_video_input(step_key) is None:
                return "no input video"
            # No-subs case allowed (watermark-only burn).
        elif step_key == "step5_pack":
            if self._resolve_srt_input(step_key) is None:
                return "no input SRT — run step2_asr or set step5_pack.source_srt"
        elif step_key == "step6_split":
            if self._resolve_video_input(step_key) is None:
                return "no input video"
            if self._resolve_segments_file(step_key) is None:
                return ("no segments file — run step5_pack first or set "
                        "step6_split.segments_file")
        return None

    def _refresh_run_state(self, step_key: str) -> None:
        """Visually hint runnability — but the button is always clickable.
        On click, _on_run_step re-validates and shows a precise error if
        prerequisites aren't met (so users never face a silent disabled
        button without knowing why)."""
        btn = self._run_buttons.get(step_key)
        if btn is None:
            return
        reason = self._check_run_prereqs(step_key)
        if reason is None:
            # Ready: blue/white, obviously clickable (matches Run All visual).
            btn.config(bg="#2563eb", fg="white",
                       activebackground="#1d4ed8", activeforeground="white",
                       relief="flat")
        else:
            # Faded look (still clickable). On click user sees the reason.
            btn.config(bg="#e5e7eb", fg="#9ca3af",
                       activebackground="#d1d5db", activeforeground="#6b7280",
                       relief="flat")

    def _on_run_step(self, step_key: str) -> None:
        if (self.project is None or self._buffer is None
                or self._current_basename is None or self._busy):
            return
        # Re-validate at click time and surface the specific reason on
        # failure (much clearer than a silently-disabled button).
        reason = self._check_run_prereqs(step_key)
        if reason is not None:
            messagebox.showinfo(
                tr("tool.project_workbench.run_blocked_title"),
                tr("tool.project_workbench.run_blocked_msg").format(
                    step=step_key, reason=reason),
            )
            return
        if self._dirty:
            if not messagebox.askyesno(
                tr("tool.project_workbench.confirm_save_before_run_title"),
                tr("tool.project_workbench.confirm_save_before_run_msg"),
            ):
                return
            if not self._save_buffer():
                return

        basename = self._current_basename
        if step_key == "step1_download":
            self._run_download(basename)
        elif step_key == "step1_5_select":
            self._run_select(basename)
        elif step_key == "step2_asr":
            self._run_asr(basename)
        elif step_key == "step3_translate":
            self._run_translate(basename)
        elif step_key == "step4_burn":
            self._run_burn(basename)
        elif step_key == "step5_pack":
            self._run_pack(basename)
        elif step_key == "step6_split":
            self._run_split(basename)

    def _step_prefix(self, step_key: str | None = None) -> str:
        """Returns '[Step N · Label] ' for the current/given step, else ''."""
        sk = step_key if step_key is not None else self._current_step
        if not sk:
            return ""
        for k, label_key in _STEPS:
            if k == sk:
                num = _STEP_DISPLAY_NUM.get(k, "")
                return (f"[Step {num} · {tr(label_key)}] "
                        if num else f"[{tr(label_key)}] ")
        return ""

    def _step_status(self, msg: str) -> None:
        """Set status with the current step's prefix prepended."""
        self._status_var.set(self._step_prefix() + msg)

    def _begin_busy(self, step_key: str, basename: str, status_msg: str) -> dict:
        """Mark step running on disk, refresh UI, and return the manifest."""
        assert self.project is not None
        manifest = self.project.load_manifest(basename) or {}
        step = manifest.setdefault(step_key, {})
        step["status"] = "running"
        manifest[step_key] = step
        self.project.save_manifest(basename, manifest)
        self._buffer = manifest
        self._busy = True
        self._current_step = step_key
        self.set_busy()
        self._status_var.set(self._step_prefix(step_key) + status_msg)
        self._render_step_cards()
        return manifest

    def _finish_step(self, step_key: str, basename: str, status: str,
                     updates: dict, msg: str) -> None:
        self._busy = False
        if self.project is None:
            return
        manifest = self.project.load_manifest(basename) or {}
        step = manifest.setdefault(step_key, {})
        step["status"] = status
        for k, v in updates.items():
            if v is None:
                step.pop(k, None)
            else:
                step[k] = v
        manifest[step_key] = step
        self.project.save_manifest(basename, manifest)
        self._status_var.set(self._step_prefix(step_key) + msg)
        self._current_step = None
        if status == "done":
            self.set_done()
        elif status == "failed":
            self.set_error(msg)
            self._abort_chain()
        if self._current_basename == basename:
            self._buffer = manifest
            self._dirty = False
            self._update_dirty_indicator()
            self._render_step_cards()
        # Advance chain on success
        if status == "done" and self._chain:
            self.master.after(50, self._run_chain_next)

    def _abort_chain(self) -> None:
        if self._chain:
            self._chain = []
            self._status_var.set(tr("tool.project_workbench.chain_aborted"))

    # ── Step 1: Download ─────────────────────────────────────────────────────

    def _run_download(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step1_download"]
        source = str(step.get("source", "")).strip()
        if not source:
            messagebox.showerror("Error", "step1_download.source is empty")
            return
        # Local-file mode: source is a path on disk → just register it.
        # No copy / no re-encode (large videos shouldn't be duplicated).
        if not source.lower().startswith(("http://", "https://")):
            if not os.path.exists(source):
                messagebox.showerror("Error", f"Source file not found:\n{source}")
                return
            self._begin_busy("step1_download", basename,
                             f"Register local source: {basename}")
            self._finish_step("step1_download", basename, "done",
                              {"output": [self._project_relpath(source)],
                               "title": None, "error": None},
                              tr("tool.project_workbench.status.download_done",
                                 basename=basename))
            return
        # URL mode: yt-dlp download into the manifest's unit folder. Raw
        # download takes the `_raw` suffix so step2's trimmed unit can
        # occupy the canonical `<basename>.mp4` slot (which is what every
        # downstream step consumes).
        out_template = os.path.join(self.project.unit_dir(basename),
                                    f"{basename}_raw.%(ext)s")
        self._begin_busy("step1_download", basename, f"Download running: {basename}")
        threading.Thread(
            target=self._download_worker,
            args=(basename, source, out_template),
            daemon=True,
        ).start()

    def _download_worker(self, basename: str, url: str, out_template: str) -> None:
        try:
            import yt_dlp

            # progress_hook fires from yt-dlp's worker; marshal back to UI.
            def hook(d):
                if d.get("status") == "downloading":
                    pct = (d.get("_percent_str") or "?").strip()
                    speed = (d.get("_speed_str") or "").strip()
                    eta = (d.get("_eta_str") or "").strip()
                    msg = tr("tool.project_workbench.status.download_progress",
                             basename=basename, pct=pct, speed=speed, eta=eta)
                    self.master.after(0, self._step_status, msg)
                elif d.get("status") == "finished":
                    self.master.after(0, self._step_status,
                                      tr("tool.project_workbench.status.download_merging",
                                         basename=basename))

            opts = {
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "outtmpl": out_template,
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "retries": 5,
                "fragment_retries": 5,
                "progress_hooks": [hook],
            }
            self.master.after(0, self._step_status,
                              tr("tool.project_workbench.status.download_start",
                                 basename=basename))
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fpath = ydl.prepare_filename(info)
            mp4 = os.path.splitext(fpath)[0] + ".mp4"
            raw_path = mp4 if os.path.exists(mp4) else fpath
            outputs = [self._project_relpath(raw_path)]

            self.master.after(0, self._finish_step, "step1_download", basename,
                              "done", {"output": outputs, "title": info.get("title")},
                              tr("tool.project_workbench.status.download_done",
                                 basename=basename))
        except Exception as e:
            self.master.after(0, self._finish_step, "step1_download", basename,
                              "failed", {"error": str(e)},
                              tr("tool.project_workbench.status.download_failed",
                                 basename=basename, e=e))

    # ── Step 1.5: Select segment (single start/end clip) ─────────────────────

    def _run_select(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step1_5_select"]
        start = str(step.get("start", "")).strip()
        end = str(step.get("end", "")).strip()
        if not (start and end) or start == end:
            messagebox.showerror("Error", "step1_5_select needs valid start / end")
            return
        source = self._resolve_input("step1_5_select")
        if not source:
            messagebox.showerror("Error",
                "Cannot resolve input — set step1_download or top-level source")
            self._abort_chain()
            return
        if not os.path.exists(source):
            messagebox.showerror("Error", f"Source not found:\n{source}")
            self._abort_chain()
            return
        # step2 produces the canonical processing unit — exactly one output
        # in the unit folder, named `<basename>.<ext>`. Multi-output flows
        # (e.g. several variants of the same source) belong in separate
        # manifests; otherwise the chain semantics break down because every
        # downstream resolver assumes output[0] is "the" working file.
        ext = os.path.splitext(source)[1] or ".mp4"
        output = os.path.join(self.project.unit_dir(basename), f"{basename}{ext}")
        self._begin_busy("step1_5_select", basename, f"Clip running: {basename}")
        threading.Thread(
            target=self._select_worker,
            args=(basename, source, start, end, output),
            daemon=True,
        ).start()

    def _select_worker(self, basename: str, source: str, start: str, end: str,
                       output: str) -> None:
        try:
            extract_clip(source, start, end, output_path=output,
                         progress_callback=lambda m: self.master.after(
                             0, self._step_status,
                             tr("tool.project_workbench.status.clip_progress",
                                basename=basename, msg=m)))
            rel = self._project_relpath(output)
            self.master.after(0, self._finish_step, "step1_5_select", basename,
                              "done", {"output": [rel]},
                              tr("tool.project_workbench.status.clip_done",
                                 basename=basename))
        except Exception as e:
            self.master.after(0, self._finish_step, "step1_5_select", basename,
                              "failed", {"error": str(e)},
                              tr("tool.project_workbench.status.clip_failed",
                                 basename=basename, e=e))

    # ── Step 2: ASR ──────────────────────────────────────────────────────────

    def _run_asr(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        asr = self._buffer["step2_asr"]
        source = self._resolve_input("step2_asr")
        if not source:
            messagebox.showerror("Error",
                "Cannot resolve input for ASR — set step1_download, step1_5_select, or top-level source")
            self._abort_chain()
            return
        if not os.path.exists(source):
            messagebox.showerror("Error", f"Source not found:\n{source}")
            self._abort_chain()
            return
        lang_iso = asr.get("language") or None
        suffix = lang_iso or "auto"
        output_srt = os.path.join(self.project.unit_dir(basename),
                                  f"{basename}_{suffix}.srt")

        language_hint: str | None = None
        if lang_iso and lang_iso in SUPPORTED_LANGUAGES and lang_iso != "auto":
            language_hint = SUPPORTED_LANGUAGES[lang_iso][0]
        expected_iso = lang_iso if lang_iso != "auto" else None

        self._begin_busy("step2_asr", basename, f"ASR running: {basename}")
        threading.Thread(
            target=self._asr_worker,
            args=(basename, source, output_srt, expected_iso, language_hint),
            daemon=True,
        ).start()

    def _asr_worker(self, basename: str, source: str, output_srt: str,
                    expected_iso: str | None, language_hint: str | None) -> None:
        try:
            assert self.project is not None
            # Always normalize through ffmpeg → mp3 ≤100MB. Lemonfox's upload
            # cap is 100MB; even when the source is already an mp3, we don't
            # know its bitrate, so we re-encode for predictability.
            prep_path = os.path.join(self.project.unit_dir(basename),
                                     f"{basename}.mp3")
            on_status = lambda msg: self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.asr_audio_prep",
                   basename=basename, msg=msg))
            audio_path = _prep_audio_for_asr(source, prep_path, on_status)

            result = transcribe_audio(
                audio_path, output_srt,
                expected_lang_iso=expected_iso, language=language_hint,
                on_event=lambda evt, **kw: self.master.after(
                    0, self._step_status,
                    tr("tool.project_workbench.status.asr_progress",
                       basename=basename, evt=evt)),
            )
            outputs = []
            for path in (result.get("srt_path"), result.get("json_path")):
                if path:
                    outputs.append(self._project_relpath(path))
            # Also record the prepped audio so user can see / reuse it.
            outputs.append(self._project_relpath(audio_path))
            updates = {"output": outputs, "error": None}
            detected = result.get("detected_lang_iso")
            if detected:
                updates["detected_language"] = detected
            self.master.after(0, self._finish_step, "step2_asr", basename,
                              "done", updates,
                              tr("tool.project_workbench.status.asr_done",
                                 basename=basename))
        except Exception as e:
            self.master.after(0, self._finish_step, "step2_asr", basename,
                              "failed", {"error": str(e)},
                              tr("tool.project_workbench.status.asr_failed",
                                 basename=basename, e=e))

    # ── Step 3: Translate ────────────────────────────────────────────────────

    def _run_translate(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step3_translate"]
        targets = step.get("targets", []) or []
        if not targets:
            messagebox.showerror("Error", "step3_translate.targets is empty")
            return
        srt_in = self._resolve_srt_input("step3_translate")
        if not srt_in:
            messagebox.showerror("Error",
                "Cannot resolve SRT — set step2_asr or step3_translate.source_srt")
            self._abort_chain()
            return
        if not os.path.exists(srt_in):
            messagebox.showerror("Error", f"SRT not found:\n{srt_in}")
            self._abort_chain()
            return
        # Source language: explicit > step2's detected/configured > "auto"
        source_lang = str(step.get("source_lang") or "").strip()
        if not source_lang:
            asr = self._buffer.get("step2_asr", {}) or {}
            source_lang = (asr.get("detected_language")
                           or asr.get("language")
                           or "auto")
        self._begin_busy("step3_translate", basename,
                         f"Translate running: {basename}")
        threading.Thread(
            target=self._translate_worker,
            args=(basename, srt_in, source_lang, list(targets)),
            daemon=True,
        ).start()

    def _translate_worker(self, basename: str, srt_in: str,
                          source_lang: str, targets: list[str]) -> None:
        try:
            outputs: list[str] = []
            for tgt in targets:
                self.master.after(
                    0, self._step_status,
                    tr("tool.project_workbench.status.translate_start",
                       basename=basename, source=source_lang, target=tgt))
                progress_cb = lambda done, total, msg, t=tgt: self.master.after(
                    0, self._step_status,
                    tr("tool.project_workbench.status.translate_progress",
                       basename=basename, target=t, msg=msg))
                out = translate_srt_file(
                    srt_in,
                    source_lang=source_lang,
                    target_lang=tgt,
                    progress_cb=progress_cb,
                )
                # translate_srt_file names by language English name (e.g.
                # "Chinese.srt"); rename to match ASR convention
                # "<basename>_<iso>.srt" so the project's SRT files all
                # follow the same scheme.
                desired = os.path.join(os.path.dirname(out),
                                       f"{basename}_{tgt}.srt")
                if os.path.normpath(desired) != os.path.normpath(out):
                    if os.path.exists(desired):
                        os.remove(desired)
                    os.replace(out, desired)
                    out = desired
                outputs.append(self._project_relpath(out))
            self.master.after(0, self._finish_step, "step3_translate", basename,
                              "done", {"output": outputs, "error": None,
                                       "source_lang_used": source_lang},
                              tr("tool.project_workbench.status.translate_done",
                                 basename=basename))
        except Exception as e:
            self.master.after(0, self._finish_step, "step3_translate", basename,
                              "failed", {"error": str(e)},
                              tr("tool.project_workbench.status.translate_failed",
                                 basename=basename, e=e))

    # ── Step 4: Burn presets ─────────────────────────────────────────────────

    def _maybe_seed_burn_from_preset(self) -> None:
        if self._buffer is None:
            return
        burn = self._buffer.get("step4_burn") or {}
        fresh = set(burn.keys()) <= {"enabled", "status"}
        if not (fresh and burn.get("enabled")):
            return
        try:
            store = burn_presets.load_store()
            name = burn_presets.get_last_used(store)
            preset = burn_presets.get_preset(store, name)
        except Exception:
            return
        if not preset:
            return
        _apply_preset_to_burn(preset, burn)
        self._buffer["step4_burn"] = burn
        self._mark_dirty()
        self._status_var.set(tr(
            "tool.project_workbench.burn_preset_applied").format(name=name))

    def _build_burn_preset_picker(self, parent) -> None:
        """Top of the burn card: dropdown + Apply / Save As / Delete buttons.
        Reads / writes the same preset store the legacy subtitle_tool uses."""
        try:
            store = burn_presets.load_store()
            names = burn_presets.list_preset_names(store)
            current = burn_presets.get_last_used(store)
        except Exception:
            store, names, current = burn_presets._empty_store(), ["Default"], "Default"

        bar = tk.Frame(parent, bg=S["card_bg"])
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        tk.Label(bar, text=tr("tool.project_workbench.field.preset") + ":",
                 bg=S["card_bg"], fg=S["label_fg"], font=S["label_font"]).pack(side="left")
        var = tk.StringVar(value=current)
        cb = ttk.Combobox(bar, textvariable=var, values=names,
                          state="readonly", width=20, font=S["value_font"])
        cb.pack(side="left", padx=(6, 4))
        tk.Button(bar, text=tr("tool.project_workbench.preset_apply"),
                  command=lambda: self._on_apply_burn_preset(var.get())).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.project_workbench.preset_save_as"),
                  command=self._on_save_burn_preset_as).pack(side="left", padx=2)
        tk.Button(bar, text=tr("tool.project_workbench.preset_delete"),
                  command=lambda: self._on_delete_burn_preset(var.get())).pack(side="left", padx=2)
        self._field_vars.append(var)

    def _on_apply_burn_preset(self, name: str) -> None:
        if self._buffer is None or not name:
            return
        try:
            store = burn_presets.load_store()
            preset = burn_presets.get_preset(store, name)
        except Exception as e:
            messagebox.showerror("Error", f"Load presets failed: {e}")
            return
        if not preset:
            messagebox.showerror("Error", f"Preset not found: {name}")
            return
        burn = self._buffer.setdefault("step4_burn", {})
        _apply_preset_to_burn(preset, burn)
        burn_presets.set_last_used(store, name)
        try:
            burn_presets.save_store(store)
        except Exception:
            pass
        self._mark_dirty()
        self._status_var.set(tr(
            "tool.project_workbench.burn_preset_applied").format(name=name))
        self._render_step_cards()

    def _on_save_burn_preset_as(self) -> None:
        if self._buffer is None:
            return
        burn = self._buffer.get("step4_burn") or {}
        name = simpledialog.askstring(
            tr("tool.project_workbench.preset_save_as"),
            tr("tool.project_workbench.preset_save_prompt"),
            parent=self.master,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        try:
            store = burn_presets.load_store()
            burn_presets.upsert_preset(store, name, _burn_to_preset(burn))
            burn_presets.set_last_used(store, name)
            burn_presets.save_store(store)
        except Exception as e:
            messagebox.showerror("Error", f"Save preset failed: {e}")
            return
        self._status_var.set(tr(
            "tool.project_workbench.burn_preset_saved").format(name=name))
        self._render_step_cards()

    def _on_delete_burn_preset(self, name: str) -> None:
        if not name or name == burn_presets.BUILTIN_DEFAULT_NAME:
            messagebox.showerror("Error",
                                 tr("tool.project_workbench.preset_default_protected"))
            return
        if not messagebox.askyesno(
                tr("tool.project_workbench.preset_delete"),
                tr("tool.project_workbench.preset_delete_confirm").format(name=name)):
            return
        try:
            store = burn_presets.load_store()
            ok = burn_presets.delete_preset(store, name)
            if ok:
                burn_presets.save_store(store)
        except Exception as e:
            messagebox.showerror("Error", f"Delete failed: {e}")
            return
        self._render_step_cards()

    # ── Step 4: Burn subtitles ───────────────────────────────────────────────

    def _srt_from_step(self, step_key: str) -> str | None:
        """First .srt in a done step's output list, abs path. None otherwise."""
        if self._buffer is None:
            return None
        s = self._buffer.get(step_key, {}) or {}
        if not (s.get("enabled") and s.get("status") == "done"):
            return None
        for path in (s.get("output", []) or []):
            if str(path).lower().endswith(".srt"):
                return self._abspath(str(path))
        return None

    def _resolve_burn_sub1(self) -> str | None:
        """Sub1 (top, translated). Returned only when bilingual (both ASR and
        translate done) — a lone subtitle should sit on the bottom track, so
        single-language case routes to sub2 instead. User override always wins.
        """
        if self._buffer is None:
            return None
        own = str(self._buffer.get("step4_burn", {}).get("sub1_path", "")).strip()
        if own:
            return self._abspath(own)
        asr = self._srt_from_step("step2_asr")
        tr_ = self._srt_from_step("step3_translate")
        if asr and tr_:
            return tr_
        return None

    def _resolve_burn_sub2(self) -> str | None:
        """Sub2 (bottom, original). Bilingual case: ASR. Single-language case:
        whichever SRT exists (translation alone or ASR alone) — lone subtitle
        always goes to bottom track. User override always wins.
        """
        if self._buffer is None:
            return None
        own = str(self._buffer.get("step4_burn", {}).get("sub2_path", "")).strip()
        if own:
            return self._abspath(own)
        asr = self._srt_from_step("step2_asr")
        tr_ = self._srt_from_step("step3_translate")
        if asr and tr_:
            return asr
        # Single-language fallback: prefer translation, then ASR
        if tr_:
            return tr_
        if asr:
            return asr
        return None

    def _run_burn(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step4_burn"]
        video = self._resolve_video_input("step4_burn")
        sub1 = self._resolve_burn_sub1()
        sub2 = self._resolve_burn_sub2()

        if not video:
            messagebox.showerror("Error",
                "Cannot resolve video — set step1_download / step1_5_select "
                "/ step4_burn.source_video / top-level source")
            self._abort_chain()
            return
        for path, name in ((video, "video"), (sub1, "sub1"), (sub2, "sub2")):
            if path and not os.path.exists(path):
                messagebox.showerror("Error", f"{name} not found:\n{path}")
                self._abort_chain()
                return

        # Output: <project>/<basename>_subbed_<tag>.mp4 with tag = inferred
        # ISO from sub1 (and +sub2 ISO when bilingual), matching the legacy
        # naming convention (Video_zh+en.mp4 → here qa_subbed_zh+en.mp4).
        tags = []
        for p in (sub1, sub2):
            if not p:
                continue
            stem = os.path.splitext(os.path.basename(p))[0]
            import re
            m = re.search(r"_([a-z]{2,5})$", stem)
            if m and m.group(1) not in tags:
                tags.append(m.group(1))
        suffix = "_" + "+".join(tags) if tags else ""
        output = os.path.join(self.project.unit_dir(basename),
                              f"{basename}_subbed{suffix}.mp4")

        # Resolve image watermark path (relative to project)
        wm_image_path = str(step.get("wm_image_path", "")).strip()
        if wm_image_path:
            wm_image_path = self._abspath(wm_image_path)
            if not os.path.exists(wm_image_path):
                wm_image_path = ""  # silently disable bad image — better than failing

        # bool fields default-true when key absent — splitting on by default
        # because un-split long lines blow past frame edges; better to wrap
        # by default and let users untick if they really don't want it.
        def b(key, default):
            v = step.get(key, default)
            return bool(v) if v is not None else default

        kwargs = dict(
            sub1_path=sub1,
            sub1_fontsize=int(step.get("sub1_fontsize", 32) or 32),
            sub1_color=str(step.get("sub1_color", "#FFFFFF") or "#FFFFFF"),
            sub1_split=b("sub1_split", True),
            sub1_max_chars=int(step.get("sub1_max_chars", 18) or 18),
            sub1_is_chinese=b("sub1_is_chinese", True),
            sub2_path=sub2,
            sub2_fontsize=int(step.get("sub2_fontsize", 28) or 28),
            sub2_color=str(step.get("sub2_color", "#CCCCCC") or "#CCCCCC"),
            sub2_split=b("sub2_split", True),
            sub2_max_chars=int(step.get("sub2_max_chars", 42) or 42),
            sub2_is_chinese=b("sub2_is_chinese", False),
            orientation=str(step.get("orientation", "auto") or "auto"),
            wm_text=str(step.get("wm_text", "") or ""),
            wm_text_color=str(step.get("wm_text_color", "#FFFFFF") or "#FFFFFF"),
            wm_text_fontsize=int(step.get("wm_text_fontsize", 28) or 28),
            wm_text_alpha=int(step.get("wm_text_alpha", 80) or 80),
            wm_image_path=wm_image_path,
            wm_image_scale=float(step.get("wm_image_scale", 0.1) or 0.1),
            wm_image_alpha=int(step.get("wm_image_alpha", 80) or 80),
            show_date=bool(str(step.get("date_text", "") or "").strip()),
            date_text=str(step.get("date_text", "") or ""),
            date_color=str(step.get("date_color", "#FFFFFF") or "#FFFFFF"),
            date_fontsize=int(step.get("date_fontsize", 24) or 24),
            date_alpha=int(step.get("date_alpha", 80) or 80),
            encode_preset=str(step.get("encode_preset", "veryfast") or "veryfast"),
        )

        self._begin_busy("step4_burn", basename, f"Burn running: {basename}")
        threading.Thread(
            target=self._burn_worker,
            args=(basename, video, output, kwargs),
            daemon=True,
        ).start()

    def _burn_worker(self, basename: str, video: str, output: str,
                     kwargs: dict) -> None:
        # core/burn_subs sends English action keys; translate them via i18n.
        # Unknown keys pass through verbatim for forward compatibility.
        def translate_inner(action: str) -> str:
            # `encoding 42%` → translate `encoding`, append ` 42%`
            head, _, tail = action.partition(" ")
            key = f"tool.project_workbench.status.burn.{head}"
            translated = tr(key)
            base = translated if translated != key else head
            return f"{base} {tail}" if tail else base

        try:
            on_status = lambda msg: self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.burn_progress",
                   basename=basename, msg=translate_inner(msg)))
            burn_subtitles(video, output, on_status=on_status, **kwargs)
            self.master.after(0, self._finish_step, "step4_burn", basename,
                              "done", {"output": [self._project_relpath(output)],
                                       "error": None},
                              tr("tool.project_workbench.status.burn_done",
                                 basename=basename))
        except Exception as e:
            self.master.after(0, self._finish_step, "step4_burn", basename,
                              "failed", {"error": str(e)},
                              tr("tool.project_workbench.status.burn_failed",
                                 basename=basename, e=e))

    # ── Step 5: Subtitle pack ────────────────────────────────────────────────

    def _run_pack(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        srt_in = self._resolve_srt_input("step5_pack")
        if not srt_in:
            messagebox.showerror("Error",
                "Cannot resolve SRT — set step2_asr / step3_translate / "
                "step5_pack.source_srt")
            self._abort_chain()
            return
        if not os.path.exists(srt_in):
            messagebox.showerror("Error", f"SRT not found:\n{srt_in}")
            self._abort_chain()
            return
        # Output base: <project>/<basename>_pack — write_subtitle_pack will
        # append .json / -titles.txt / -segments.txt / -refined.txt
        base = os.path.join(self.project.unit_dir(basename), f"{basename}_pack")
        self._begin_busy("step5_pack", basename, f"Pack running: {basename}")
        threading.Thread(
            target=self._pack_worker,
            args=(basename, srt_in, base),
            daemon=True,
        ).start()

    def _pack_worker(self, basename: str, srt_in: str, base: str) -> None:
        try:
            self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.pack_ai", basename=basename))
            # tier= is a no-op in the router since commit 58e6414 (drop tier
            # dimension). Routing is task-based now: subtitle.post is
            # configured per-task in the AI Console.
            pack = generate_subtitle_pack(srt_in)
            self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.pack_writing", basename=basename))
            paths = write_subtitle_pack(pack, base)
            outputs = [self._project_relpath(p) for p in
                       (paths.get("json"), paths.get("titles"),
                        paths.get("segments"), paths.get("refined")) if p]
            self.master.after(0, self._finish_step, "step5_pack", basename,
                              "done", {"output": outputs, "error": None},
                              tr("tool.project_workbench.status.pack_done",
                                 basename=basename))
        except Exception as e:
            self.master.after(0, self._finish_step, "step5_pack", basename,
                              "failed", {"error": str(e)},
                              tr("tool.project_workbench.status.pack_failed",
                                 basename=basename, e=e))

    # ── Step 6: Long-video split ─────────────────────────────────────────────

    def _run_split(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step6_split"]
        video = self._resolve_video_input("step6_split")
        seg_file = self._resolve_segments_file("step6_split")
        if not video:
            messagebox.showerror("Error", "no input video for step6_split")
            self._abort_chain()
            return
        if not seg_file:
            messagebox.showerror("Error", "no segments file for step6_split")
            self._abort_chain()
            return
        if not os.path.exists(video):
            messagebox.showerror("Error", f"Video not found:\n{video}")
            self._abort_chain()
            return
        if not os.path.exists(seg_file):
            messagebox.showerror("Error", f"Segments file not found:\n{seg_file}")
            self._abort_chain()
            return
        try:
            segments = load_segments_file(seg_file)
        except Exception as e:
            messagebox.showerror("Error", f"Parse segments failed: {e}")
            self._abort_chain()
            return
        if not segments:
            messagebox.showerror("Error", "Segments file is empty")
            self._abort_chain()
            return
        mode_str = str(step.get("split_mode", "keyframe_snap")).lower()
        mode_map = {"keyframe_snap": SplitMode.KEYFRAME_SNAP,
                    "fast": SplitMode.FAST,
                    "accurate": SplitMode.ACCURATE}
        mode = mode_map.get(mode_str, SplitMode.KEYFRAME_SNAP)
        out_dir = os.path.join(self.project.unit_dir(basename), "splits")
        self._begin_busy(
            "step6_split", basename,
            tr("tool.project_workbench.status.split_start", basename=basename))
        threading.Thread(
            target=self._split_worker,
            args=(basename, video, segments, mode, out_dir),
            daemon=True,
        ).start()

    def _split_worker(self, basename: str, video: str, segments: list,
                      mode, out_dir: str) -> None:
        try:
            self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.split_probing",
                   basename=basename))
            duration = _video_duration_seconds(video)
            if duration <= 0:
                raise RuntimeError("Cannot read video duration via ffprobe")
            on_probe = lambda: self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.split_keyframes",
                   basename=basename))
            progress = lambda done, total: self.master.after(
                0, self._step_status,
                tr("tool.project_workbench.status.split_progress",
                   basename=basename, done=done, total=total))
            outputs = split_segments(
                video, segments, list(range(len(segments))),
                duration, out_dir,
                progress_cb=progress, mode=mode, on_probe_start=on_probe,
            )
            rel = [self._project_relpath(p) for p in outputs]
            self.master.after(
                0, self._finish_step, "step6_split", basename, "done",
                {"output": rel, "error": None, "count": len(outputs)},
                tr("tool.project_workbench.status.split_done",
                   basename=basename, count=len(outputs)))
        except Exception as e:
            self.master.after(
                0, self._finish_step, "step6_split", basename, "failed",
                {"error": str(e)},
                tr("tool.project_workbench.status.split_failed",
                   basename=basename, e=e))

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _browse_initial_dir(self) -> str:
        """Initial directory for filedialog Browse buttons. Prefers the
        current manifest's unit folder so users land on artifacts they're
        likely picking; falls back to project root, then empty string."""
        if self.project is None:
            return ""
        if self._current_basename:
            try:
                return self.project.unit_dir(self._current_basename)
            except Exception:
                pass
        return self.project.folder

    def _project_relpath(self, path: str) -> str:
        if self.project is None:
            return path
        try:
            return os.path.relpath(path, self.project.folder).replace("\\", "/")
        except ValueError:
            return path
