"""Tk widget that embeds a Chromium WebView2 surface via a child process.

Why two processes: pywebview demands the main thread on Windows, and so does
Tk. Putting them in separate processes lets each own its main loop. The
parent (Tk) finds the child's HWND by a unique title, strips its frame
decorations, and SetParents it into a Tk Frame. The child renders the actual
page; the parent drives it via stdin/stdout JSON.

Why this exists: Tk Canvas + GPU video is impossible — VLC's HWND surface is
opaque to Tk overlays, and pure-Python decode capping at ~16 fps. WebView2
gives us GPU decode + GPU compositor + DOM-level overlay layering for free.

Public API (callable from the Tk thread):
  WebPreviewFrame(parent, on_message=cb)
    .load_url(url)
    .load_html(html)
    .evaluate_js(code)
    .destroy()                    # also kills the child process
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from typing import Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool
kernel32.GetCurrentThreadId.restype = wt.DWORD

# ── Focus-grab workaround helper ───────────────────────────────────────────

# Any Tk Entry / Text / Spinbox sharing a top-level with the embedded
# WebView2 child needs its <Button-1> shimmed to focus_force() — without
# it, Win32 keyboard focus stays in the WebView's input thread even
# after a click into a Tk widget, and keystrokes go nowhere. The
# AttachThreadInput merge done in _embed() routes input correctly once
# focus is on the right widget; it cannot itself force the focus shift.
# Returning None (not "break") preserves Tk's normal click handling for
# cursor placement / selection.

_FOCUSABLE_CLASS_NAMES = ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox",
                          "Combobox", "TCombobox")


def _force_focus_on_click(event) -> None:
    try:
        event.widget.focus_force()
    except Exception:
        pass


def attach_focus_grab_fix(container: tk.Widget) -> None:
    """Walk `container`'s widget subtree and install the WebView2 focus
    shim on every Entry / Text / Spinbox / Combobox descendant.

    Call this after the container's UI has been built. Idempotent on
    individual widgets — `bind(..., add="+")` chains rather than
    replaces. New widgets added later are NOT covered; call again or
    bind manually for those.
    """
    def _walk(w: tk.Widget) -> None:
        cls = w.winfo_class()
        if cls in _FOCUSABLE_CLASS_NAMES:
            w.bind("<Button-1>", _force_focus_on_click, add="+")
        for child in w.winfo_children():
            _walk(child)
    _walk(container)


GWL_STYLE     = -16
WS_CAPTION    = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_CHILD      = 0x40000000
WS_POPUP      = 0x80000000
WS_BORDER     = 0x00800000
WS_DLGFRAME   = 0x00400000
WS_SYSMENU    = 0x00080000

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def _find_window_by_title(title: str) -> int | None:
    found: list[int] = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == title:
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = ctypes.c_bool


def setup_dpi_aware() -> bool:
    """Mark this process per-monitor DPI aware. MUST be called before any
    Tk window is created. Returns True on success.

    Required when this widget is used: WebView2 children render at physical
    pixels and SetParent across DPI awareness boundaries breaks sizing. The
    cleanest fix is to make the host process aware too. After this call, Tk
    coordinates also become physical — fonts will look smaller; compensate
    via tk scaling if needed:

        root.tk.call('tk', 'scaling', user32.GetDpiForSystem() / 72.0)
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR
        return True
    except Exception:
        try:
            user32.SetProcessDPIAware()
            return True
        except Exception:
            return False


_HOST_SCRIPT = os.path.join(os.path.dirname(__file__), "web_preview_host.py")


class WebPreviewFrame(tk.Frame):
    def __init__(self, master: tk.Misc,
                 on_message: Callable[[dict], None] | None = None,
                 on_loaded: Callable[[], None] | None = None,
                 initial_url: str = "about:blank",
                 **kwargs):
        super().__init__(master, bg="black", highlightthickness=0, **kwargs)
        self._on_message = on_message
        self._on_loaded = on_loaded
        self._child: subprocess.Popen | None = None
        self._wv_hwnd: int | None = None
        self._title = f"vcraft-webpreview-{os.getpid()}-{id(self):x}"
        self._stdout_thread: threading.Thread | None = None
        self._destroyed = False
        self._attached_thread: int | None = None  # see _embed()
        # Commands are written to the child's stdin from a dedicated writer
        # thread, never the Tk main thread. A busy/slow child (GUI thread
        # tied up playing video) stops draining stdin; a blocking write on
        # the Tk thread would then fill the pipe buffer and freeze the
        # whole UI (made fatal by the AttachThreadInput input-queue merge).
        self._send_q: "queue.Queue[str | None]" = queue.Queue()
        self._writer_thread: threading.Thread | None = None
        # SetParent must happen AFTER the page's first paint, else
        # Chromium reparents a blank surface (random blank previews under
        # load, esp. with several webviews spawning at once). Gate _embed
        # on BOTH the HWND being found AND the page "loaded" event, with a
        # timeout fallback so a missing event can't strand the preview.
        self._pending_hwnd: int | None = None
        self._page_loaded = False
        self._embedded = False

        self.bind("<Configure>", self._on_configure)
        # Defer spawn until the frame has a real HWND
        self.after(0, lambda: self._spawn(initial_url))

    # ── public API ────────────────────────────────────────────────────────

    def load_url(self, url: str) -> None:
        self._send({"cmd": "load_url", "url": url})

    def load_html(self, html: str) -> None:
        self._send({"cmd": "load_html", "html": html})

    def evaluate_js(self, code: str) -> None:
        self._send({"cmd": "eval", "code": code})

    def destroy(self) -> None:
        # Detach BEFORE asking the child to quit so a still-living thread
        # is on the other end of AttachThreadInput. Detaching against a
        # gone thread is a no-op but logs noise on some Windows builds.
        if self._attached_thread is not None:
            try:
                user32.AttachThreadInput(
                    self._attached_thread,
                    kernel32.GetCurrentThreadId(),
                    False,
                )
            except Exception:
                pass
            self._attached_thread = None
        # Enqueue the graceful quit while _send still accepts it, then
        # mark destroyed and wake the writer with a sentinel.
        self._send({"cmd": "quit"})
        self._destroyed = True
        try:
            self._send_q.put_nowait(None)
        except Exception:
            pass
        if self._child is not None:
            try:
                self._child.wait(timeout=1.0)
            except Exception:
                try:
                    self._child.terminate()
                except Exception:
                    pass
        super().destroy()

    # ── internals ─────────────────────────────────────────────────────────

    def _spawn(self, initial_url: str) -> None:
        if self._destroyed:
            return
        self.update_idletasks()
        py = sys.executable
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        # After we cross-process SetParent the WebView2 window into a Tk
        # frame, the overlay <canvas> draws correctly (JS runs, the crop
        # box is even draggable — cursor changes, drag works) but its
        # pixels don't show: the GPU-accelerated 2D-canvas compositing
        # layer isn't presented to the reparented surface. Video (a
        # separate video layer) and DOM/input are unaffected — hence the
        # random "video shows, overlay gone". Forcing the canvas to render
        # in software makes it paint into the normal (presented) document
        # layer instead of its own GPU texture. Occlusion calc is also
        # disabled as a cheap belt-and-suspenders. WebView2 reads this env
        # var for extra Chromium args.
        extra_args = (
            "--disable-accelerated-2d-canvas"
            " --disable-features=CalculateNativeWinOcclusion"
        )
        existing = env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "").strip()
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            f"{existing} {extra_args}".strip() if existing else extra_args)
        # The host script needs `import webview`, so its sys.path doesn't
        # need our src/ on it — it uses the venv's site-packages. Run it
        # directly by file path.
        self._child = subprocess.Popen(
            [py, _HOST_SCRIPT, self._title, initial_url],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            bufsize=1, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        self._stdout_thread = threading.Thread(
            target=self._read_stdout, daemon=True)
        self._stdout_thread.start()
        self._writer_thread = threading.Thread(
            target=self._write_loop, daemon=True)
        self._writer_thread.start()
        # Poll for the HWND on the Tk thread
        self.after(100, self._poll_for_hwnd, time.time() + 15.0)

    def _write_loop(self) -> None:
        """Drain the send queue to the child's stdin. Runs off the Tk
        thread so a slow child can never block the UI on a full pipe."""
        stdin = self._child.stdin if self._child else None
        if stdin is None:
            return
        while True:
            line = self._send_q.get()
            if line is None or self._destroyed:   # sentinel = shut down
                return
            try:
                stdin.write(line)
                stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                return

    def _poll_for_hwnd(self, deadline: float) -> None:
        if self._destroyed:
            return
        hwnd = _find_window_by_title(self._title)
        if hwnd:
            self._pending_hwnd = hwnd
            # Embed once the page has painted (loaded event). Fallback:
            # if "loaded" never arrives, embed anyway after a grace period
            # so the preview can't be stranded blank.
            self._maybe_embed()
            self.after(2500, self._embed_fallback)
            return
        if time.time() < deadline:
            self.after(100, self._poll_for_hwnd, deadline)

    def _mark_page_loaded(self) -> None:
        self._page_loaded = True
        self._maybe_embed()

    def _maybe_embed(self) -> None:
        if self._destroyed or self._embedded:
            return
        if self._pending_hwnd is None or not self._page_loaded:
            return
        # One more frame for Chromium to actually paint after DOM-load,
        # then reparent.
        self.after(120, lambda: self._embed(self._pending_hwnd))

    def _embed_fallback(self) -> None:
        if self._destroyed or self._embedded or self._pending_hwnd is None:
            return
        # "loaded" never showed up — embed anyway rather than leave the
        # preview permanently detached.
        self._embed(self._pending_hwnd)

    def _embed(self, wv_hwnd: int) -> None:
        if self._destroyed or self._embedded:
            return
        self._embedded = True
        self._wv_hwnd = wv_hwnd
        style = user32.GetWindowLongW(wv_hwnd, GWL_STYLE)
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_POPUP | WS_BORDER
                   | WS_DLGFRAME | WS_SYSMENU)
        style |= WS_CHILD
        user32.SetWindowLongW(wv_hwnd, GWL_STYLE, style)
        user32.SetParent(wv_hwnd, self.winfo_id())
        self._reposition()
        self._attach_input_queue(wv_hwnd)

    def _attach_input_queue(self, wv_hwnd: int) -> None:
        """Merge the WebView's input queue into Tk's.

        Without this, any Tk Entry / Text widget sharing a top-level
        window with the embedded WebView cannot receive keyboard input:
        Win32 keyboard focus is *per-thread*, and SetParent across
        processes leaves the two threads with independent focus state.
        Tk's SetFocus(entry_hwnd) silently doesn't propagate to the
        active input thread (still the WebView's), so WM_KEYDOWN never
        reaches the Entry.
        AttachThreadInput merges the two queues so focus changes route
        keystrokes to the actually-focused window across processes.
        Trade-off: input handling becomes synchronous between threads;
        a hung WebView blocks Tk input. Acceptable — a hung WebView is
        a fatal condition for this UI anyway.
        """
        wv_thread = user32.GetWindowThreadProcessId(wv_hwnd, None)
        tk_thread = kernel32.GetCurrentThreadId()
        if wv_thread == 0 or wv_thread == tk_thread:
            return
        if user32.AttachThreadInput(wv_thread, tk_thread, True):
            self._attached_thread = wv_thread

    def _reposition(self) -> None:
        if self._wv_hwnd is None:
            return
        # Caller must have made the process DPI aware via setup_dpi_aware()
        # before Tk init. Then winfo_width/height are physical pixels and
        # match the WebView child's coordinate system directly.
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        user32.MoveWindow(self._wv_hwnd, 0, 0, w, h, True)

    def _on_configure(self, _e=None) -> None:
        self._reposition()

    def _send(self, msg: dict) -> None:
        # Enqueue only — the writer thread does the (potentially blocking)
        # pipe write. Never block the Tk main thread here.
        if self._child is None or self._destroyed:
            return
        try:
            self._send_q.put_nowait(json.dumps(msg, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _read_stdout(self) -> None:
        assert self._child is not None and self._child.stdout is not None
        for line in self._child.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = msg.get("event")
            # Marshal back to Tk thread
            if event == "message" and self._on_message is not None:
                self.after(0, self._on_message, msg.get("data"))
            elif event == "loaded":
                # Drive embed gating regardless of whether an external
                # on_loaded callback is registered.
                self.after(0, self._mark_page_loaded)
                if self._on_loaded is not None:
                    self.after(0, self._on_loaded)
