"""Quick verification: PyAV → Tk Canvas playback with overlay rectangle.

Goal: prove that decoding video frames in Python and blitting them to a Tk
Canvas allows arbitrary overlays (the whole point of choosing PyAV over VLC's
opaque HWND surface). Reports achieved FPS so we know if it's viable for the
clip-script preview pane.

Run: myenv/Scripts/python.exe verify_pyav_canvas.py <video_path>
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk

import av
from PIL import Image, ImageTk


PREVIEW_W = 640  # downscale target — matches a typical clip-script preview pane


class PyAvPreview(tk.Frame):
    def __init__(self, master: tk.Misc, video_path: str):
        super().__init__(master)
        self.pack(fill="both", expand=True)

        self._container = av.open(video_path)
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"  # multi-threaded decode

        sw, sh = self._stream.codec_context.width, self._stream.codec_context.height
        scale = PREVIEW_W / sw
        self._vw = PREVIEW_W
        self._vh = int(sh * scale)
        src_fps = float(self._stream.average_rate or 25)
        # Cap preview at 30 fps — for crop/framing QA, smoother is wasted CPU.
        self._fps_target = min(src_fps, 30.0)
        self._src_fps = src_fps

        self._canvas = tk.Canvas(self, width=self._vw, height=self._vh,
                                 bg="black", highlightthickness=0)
        self._canvas.pack()

        # Overlay: a draggable framing rect drawn on the same Canvas.
        # If we can see this on top of every frame, HWND obstruction is solved.
        rx, ry = self._vw * 0.15, self._vh * 0.10
        rw, rh = self._vw * 0.70, self._vh * 0.80
        self._rect = self._canvas.create_rectangle(
            rx, ry, rx + rw, ry + rh, outline="#00ff88", width=3)
        self._label = self._canvas.create_text(
            self._vw // 2, 16, text="overlay rectangle (proves no obstruction)",
            fill="#00ff88", font=("", 10, "bold"))
        self._fps_text = self._canvas.create_text(
            8, 8, text="", fill="yellow", anchor="nw",
            font=("Consolas", 11, "bold"))

        self._photo: ImageTk.PhotoImage | None = None
        self._image_id = self._canvas.create_image(0, 0, anchor="nw")
        self._canvas.tag_raise(self._rect)
        self._canvas.tag_raise(self._label)
        self._canvas.tag_raise(self._fps_text)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Restart", command=self._restart).pack(side="left", padx=4)
        ttk.Button(bar, text="Quit",   command=master.destroy).pack(side="left")

        self._iter = self._container.decode(self._stream)
        self._frame_count = 0
        self._t_start = time.perf_counter()
        self._last_fps_update = self._t_start
        self._frames_since_update = 0

        self.after(0, self._tick)

    def _restart(self) -> None:
        self._container.seek(0)
        self._iter = self._container.decode(self._stream)
        self._frame_count = 0
        self._t_start = time.perf_counter()

    def _tick(self) -> None:
        # Pace by source PTS, not by decoded-frame count. Pull frames until
        # one whose PTS is at or past the current wall-clock elapsed; earlier
        # frames are dropped (catches up after slow ticks). PIL→PhotoImage is
        # the bottleneck — we do it once per tick.
        now = time.perf_counter()
        elapsed = now - self._t_start
        frame = None
        while True:
            try:
                f = next(self._iter)
            except StopIteration:
                if frame is None:
                    return
                break
            self._frame_count += 1
            frame = f
            pts = f.time if f.time is not None else (self._frame_count / self._src_fps)
            if pts >= elapsed:
                break

        # libswscale resize via PyAV — C-level, much faster than PIL.resize.
        scaled = frame.reformat(width=self._vw, height=self._vh, format="rgb24")
        img = Image.frombuffer("RGB", (self._vw, self._vh),
                                bytes(scaled.planes[0]), "raw", "RGB", 0, 1)
        self._photo = ImageTk.PhotoImage(img)
        self._canvas.itemconfig(self._image_id, image=self._photo)
        # keep overlay on top after each frame
        self._canvas.tag_raise(self._rect)
        self._canvas.tag_raise(self._label)
        self._canvas.tag_raise(self._fps_text)

        self._frames_since_update += 1
        now = time.perf_counter()
        if now - self._last_fps_update >= 0.5:
            measured = self._frames_since_update / (now - self._last_fps_update)
            self._canvas.itemconfig(
                self._fps_text,
                text=f"shown fps: {measured:5.1f}   target: {self._fps_target:.1f}   "
                     f"src: {self._src_fps:.0f}   size: {self._vw}x{self._vh}")
            self._last_fps_update = now
            self._frames_since_update = 0

        # Cap render rate at fps_target. Next tick fires no sooner than one
        # render slot from now, regardless of source PTS.
        delay_ms = max(1, int(1000.0 / self._fps_target))
        self.after(delay_ms, self._tick)


def main() -> int:
    if len(sys.argv) >= 2:
        path = sys.argv[1]
    else:
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Pick a video to test",
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All", "*.*")])
        root.destroy()
        if not path:
            print("no file picked")
            return 1

    print(f"Decoding {path}")
    root = tk.Tk()
    root.title("PyAV Canvas verification")
    PyAvPreview(root, path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
