"""Crop rectangle picker on a static video keyframe.

Aspect ratio is configurable per instance via set_aspect_ratio(); defaults
to 9:16 portrait. Used by the clip-script workbench to let the user frame
the output crop window over a representative chapter keyframe.

Why a thumbnail and not a VLC overlay: on Windows VLC takes over the
embedded surface's HWND (see ui/vlc_player.py:_bind_surface), and any
tk.Canvas placed on top has its mouse events absorbed by the VLC child
window. Drawing the crop rect on a static keyframe (extracted via
ffmpeg) sidesteps the problem and works regardless of VLC availability.

Usage:
    overlay = CropOverlay(parent, on_change=lambda r: print(r))
    overlay.pack(fill="both", expand=True)
    overlay.set_aspect_ratio(9, 16)              # optional; default 9:16
    overlay.set_image(pil_image, video_w=1920, video_h=1080)
    overlay.set_rect({"x": 0.1, "y": 0.0, "w": 0.5625, "h": 1.0})
    rect = overlay.get_rect()    # normalized {x, y, w, h} in 0..1
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


_HANDLE_PX = 8


class CropOverlay(tk.Frame):
    """Static-image canvas with a draggable / resizable rectangle of a
    fixed aspect ratio (default 9:16).

    Resizing from any handle keeps the locked aspect; the longest
    dimension follows the cursor and the other is derived.

    Coordinates exposed via get_rect() / set_rect() are normalized to the
    *original video* dimensions (0..1), independent of how the thumbnail
    is scaled inside the canvas.
    """

    def __init__(self, master: tk.Misc,
                 on_change: Callable[[dict], None] | None = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        self._on_change = on_change
        # Aspect ratio = width / height; default 9:16 portrait.
        self._aspect_ratio = 9.0 / 16.0
        self._video_w = 0
        self._video_h = 0
        self._image_pil = None
        self._image_tk = None
        # Image render rectangle inside the canvas (after scaling to fit).
        self._img_x0 = 0
        self._img_y0 = 0
        self._img_w = 0
        self._img_h = 0
        # Crop rect in *image-pixel* coords (relative to the original video).
        self._rect = {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
        # Drag state
        self._drag_mode: str | None = None     # "move" | "resize" | None
        self._drag_anchor: tuple[float, float] | None = None
        self._drag_start_rect: dict | None = None

        self._canvas = tk.Canvas(self, bg="#222", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", self._on_resize)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        if not _PIL_OK:
            self._canvas.create_text(
                10, 10, anchor="nw",
                text="Pillow not installed — install Pillow to use crop UI",
                fill="#ccc",
            )

    # ── Public API ────────────────────────────────────────────────────────

    def set_aspect_ratio(self, w_ratio: int, h_ratio: int) -> None:
        """Update the locked aspect of the crop rect. Re-clamps any
        existing rect to honor the new ratio."""
        new_ar = max(0.001, float(w_ratio) / max(0.001, float(h_ratio)))
        if abs(new_ar - self._aspect_ratio) < 1e-6:
            return
        self._aspect_ratio = new_ar
        # Re-clamp any existing rect to honor the new aspect.
        if self._video_w > 0 and self._rect["w"] > 0:
            self._clamp_rect()
            self._redraw()
            self._notify()

    def set_image(self, pil_image, video_w: int, video_h: int) -> None:
        """Load a PIL image as the backdrop. video_w/h are the *source video*
        dimensions used for normalized rect output."""
        if not _PIL_OK:
            return
        self._image_pil = pil_image
        self._video_w = max(1, int(video_w))
        self._video_h = max(1, int(video_h))
        # Reset to a center 9:16 rect on first load if no rect set yet.
        if self._rect["w"] == 0 or self._rect["h"] == 0:
            self.reset_to_center()
        self._redraw()

    def set_rect(self, normalized: dict) -> None:
        """Set the crop rect from normalized {x, y, w, h} 0..1 coords
        (relative to source video)."""
        if not normalized or self._video_w == 0:
            return
        self._rect = {
            "x": float(normalized.get("x", 0)) * self._video_w,
            "y": float(normalized.get("y", 0)) * self._video_h,
            "w": float(normalized.get("w", 1)) * self._video_w,
            "h": float(normalized.get("h", 1)) * self._video_h,
        }
        self._clamp_rect()
        self._redraw()
        self._notify()

    def get_rect(self) -> dict:
        """Return normalized {x, y, w, h} 0..1 in source-video coords."""
        if self._video_w == 0 or self._video_h == 0:
            return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        return {
            "x": max(0.0, min(1.0, self._rect["x"] / self._video_w)),
            "y": max(0.0, min(1.0, self._rect["y"] / self._video_h)),
            "w": max(0.0, min(1.0, self._rect["w"] / self._video_w)),
            "h": max(0.0, min(1.0, self._rect["h"] / self._video_h)),
        }

    def reset_to_center(self) -> None:
        """Center crop: largest rect at the locked aspect that fits in the
        source video."""
        if self._video_w <= 0 or self._video_h <= 0:
            return
        target_ar = self._aspect_ratio
        cur_ar = self._video_w / self._video_h
        if cur_ar > target_ar:
            new_w = self._video_h * target_ar
            self._rect = {
                "x": (self._video_w - new_w) / 2.0, "y": 0.0,
                "w": new_w, "h": float(self._video_h),
            }
        else:
            new_h = self._video_w / target_ar
            self._rect = {
                "x": 0.0, "y": (self._video_h - new_h) / 2.0,
                "w": float(self._video_w), "h": new_h,
            }
        self._redraw()
        self._notify()

    # ── Layout / drawing ──────────────────────────────────────────────────

    def _on_resize(self, _event) -> None:
        self._redraw()

    def _redraw(self) -> None:
        self._canvas.delete("all")
        if not _PIL_OK or self._image_pil is None:
            return
        cw = max(1, self._canvas.winfo_width())
        ch = max(1, self._canvas.winfo_height())
        # Fit image into canvas preserving AR
        img_ar = self._video_w / self._video_h
        canvas_ar = cw / ch
        if img_ar > canvas_ar:
            self._img_w = cw
            self._img_h = int(cw / img_ar)
        else:
            self._img_h = ch
            self._img_w = int(ch * img_ar)
        self._img_x0 = (cw - self._img_w) // 2
        self._img_y0 = (ch - self._img_h) // 2
        try:
            scaled = self._image_pil.resize(
                (max(1, self._img_w), max(1, self._img_h)),
                Image.LANCZOS,
            )
            self._image_tk = ImageTk.PhotoImage(scaled)
            self._canvas.create_image(self._img_x0, self._img_y0,
                                      anchor="nw", image=self._image_tk)
        except Exception:
            self._image_tk = None

        # Dim the area outside the crop rect to make the selection pop
        if self._rect["w"] > 0 and self._rect["h"] > 0:
            cx0, cy0, cx1, cy1 = self._rect_canvas_coords()
            # Four dim rectangles around the crop
            dim = "#000000"
            self._canvas.create_rectangle(
                self._img_x0, self._img_y0,
                self._img_x0 + self._img_w, cy0,
                fill=dim, stipple="gray50", outline="")
            self._canvas.create_rectangle(
                self._img_x0, cy1,
                self._img_x0 + self._img_w, self._img_y0 + self._img_h,
                fill=dim, stipple="gray50", outline="")
            self._canvas.create_rectangle(
                self._img_x0, cy0, cx0, cy1,
                fill=dim, stipple="gray50", outline="")
            self._canvas.create_rectangle(
                cx1, cy0, self._img_x0 + self._img_w, cy1,
                fill=dim, stipple="gray50", outline="")
            # Crop border
            self._canvas.create_rectangle(
                cx0, cy0, cx1, cy1, outline="#ff5050", width=2)
            # Corner handles
            for hx, hy in ((cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)):
                self._canvas.create_rectangle(
                    hx - _HANDLE_PX // 2, hy - _HANDLE_PX // 2,
                    hx + _HANDLE_PX // 2, hy + _HANDLE_PX // 2,
                    fill="#ff5050", outline="white",
                )

    def _rect_canvas_coords(self) -> tuple[int, int, int, int]:
        """Convert the image-pixel rect to canvas coords."""
        if self._video_w == 0 or self._img_w == 0:
            return (0, 0, 0, 0)
        sx = self._img_w / self._video_w
        sy = self._img_h / self._video_h
        x0 = self._img_x0 + int(self._rect["x"] * sx)
        y0 = self._img_y0 + int(self._rect["y"] * sy)
        x1 = x0 + int(self._rect["w"] * sx)
        y1 = y0 + int(self._rect["h"] * sy)
        return (x0, y0, x1, y1)

    # ── Mouse handling ────────────────────────────────────────────────────

    def _hit_test(self, x: int, y: int) -> str | None:
        if self._rect["w"] == 0:
            return None
        cx0, cy0, cx1, cy1 = self._rect_canvas_coords()
        # Corners (resize)
        for hx, hy in ((cx1, cy1),):    # only bottom-right resize for now (simple)
            if abs(x - hx) <= _HANDLE_PX and abs(y - hy) <= _HANDLE_PX:
                return "resize"
        if cx0 <= x <= cx1 and cy0 <= y <= cy1:
            return "move"
        return None

    def _on_press(self, event) -> None:
        if not _PIL_OK or self._image_pil is None:
            return
        mode = self._hit_test(event.x, event.y)
        if mode is None:
            return
        self._drag_mode = mode
        self._drag_anchor = (event.x, event.y)
        self._drag_start_rect = dict(self._rect)

    def _on_drag(self, event) -> None:
        if self._drag_mode is None or self._drag_anchor is None \
                or self._drag_start_rect is None:
            return
        if self._video_w == 0 or self._img_w == 0:
            return
        sx = self._img_w / self._video_w
        sy = self._img_h / self._video_h
        dx_canvas = event.x - self._drag_anchor[0]
        dy_canvas = event.y - self._drag_anchor[1]
        dx_video = dx_canvas / sx
        dy_video = dy_canvas / sy
        if self._drag_mode == "move":
            self._rect = dict(self._drag_start_rect)
            self._rect["x"] += dx_video
            self._rect["y"] += dy_video
        elif self._drag_mode == "resize":
            # Resize from bottom-right; keep top-left anchored, lock 9:16 AR.
            new_w = max(40.0, self._drag_start_rect["w"] + dx_video)
            new_h = new_w / self._aspect_ratio
            if (self._drag_start_rect["y"] + new_h) > self._video_h:
                new_h = self._video_h - self._drag_start_rect["y"]
                new_w = new_h * self._aspect_ratio
            self._rect = dict(self._drag_start_rect)
            self._rect["w"] = new_w
            self._rect["h"] = new_h
        self._clamp_rect()
        self._redraw()

    def _on_release(self, _event) -> None:
        if self._drag_mode is not None:
            self._drag_mode = None
            self._drag_anchor = None
            self._drag_start_rect = None
            self._notify()

    def _clamp_rect(self) -> None:
        """Keep the rect inside the source video bounds + 9:16 aspect."""
        # Lock aspect: derive height from width
        if self._rect["w"] <= 0 or self._rect["h"] <= 0:
            return
        # If width is the constraint:
        self._rect["h"] = self._rect["w"] / self._aspect_ratio
        # Bound by video size; if too tall, cap height and recompute width
        if self._rect["h"] > self._video_h:
            self._rect["h"] = float(self._video_h)
            self._rect["w"] = self._rect["h"] * self._aspect_ratio
        if self._rect["w"] > self._video_w:
            self._rect["w"] = float(self._video_w)
            self._rect["h"] = self._rect["w"] / self._aspect_ratio
        # Clamp position
        max_x = max(0.0, self._video_w - self._rect["w"])
        max_y = max(0.0, self._video_h - self._rect["h"])
        self._rect["x"] = max(0.0, min(max_x, self._rect["x"]))
        self._rect["y"] = max(0.0, min(max_y, self._rect["y"]))

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change(self.get_rect())
            except Exception:
                pass


__all__ = ["CropOverlay"]
