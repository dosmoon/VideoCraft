"""Step 2 verification (rev 3): two-process architecture.

  Parent (this script): Tk main window. Contains a placeholder Frame.
  Child  (webview_host.py): runs pywebview on its own main thread.

Parent spawns child, finds its HWND by unique window title, strips frame
decorations, SetParent into the Tk Frame. Resize follows.

Run: myenv/Scripts/python.exe verify_webview_step2.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
import tkinter as tk

user32 = ctypes.windll.user32

# Match WebView2's DPI awareness (per-monitor v2). Without this, Tk reports
# logical pixels while the embedded WebView uses physical pixels, and our
# MoveWindow calls under-size the child — which is exactly the "renders in
# the top-left quadrant" symptom on scaled displays.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

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


def main() -> int:
    html = os.path.abspath("verify_webview_step1.html")
    if not os.path.exists(html):
        print(f"missing {html}")
        return 1

    file_url = "file:///" + html.replace("\\", "/")
    wv_title = f"vcraft-webview-{os.getpid()}"
    py = sys.executable
    host_script = os.path.abspath("verify_webview_host.py")

    # Spawn the WebView host
    child = subprocess.Popen([py, host_script, wv_title, file_url])

    # Tk shell
    root = tk.Tk()
    root.title("VideoCraft – two-process WebView embed")
    root.geometry("1200x800")

    info = tk.Label(root, text="waiting for WebView…", anchor="w", fg="#555")
    info.pack(fill="x", padx=8, pady=4)

    container = tk.Frame(root, bg="black", highlightthickness=0)
    container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    container.update()
    container_hwnd = container.winfo_id()

    # Wait for child window to appear
    wv_hwnd = None
    deadline = time.time() + 15.0
    while time.time() < deadline:
        wv_hwnd = _find_window_by_title(wv_title)
        if wv_hwnd:
            # Give the page a moment to render before reparenting; SetParent
            # mid-load can blank Chromium.
            time.sleep(0.6)
            break
        root.update()
        time.sleep(0.1)

    if not wv_hwnd:
        info.config(text="ERROR: WebView window not found", fg="red")
        root.mainloop()
        return 1

    style = user32.GetWindowLongW(wv_hwnd, GWL_STYLE)
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_POPUP | WS_BORDER
               | WS_DLGFRAME | WS_SYSMENU)
    style |= WS_CHILD
    user32.SetWindowLongW(wv_hwnd, GWL_STYLE, style)
    user32.SetParent(wv_hwnd, container_hwnd)

    def reposition(_e=None):
        w = container.winfo_width()
        h = container.winfo_height()
        if w > 1 and h > 1:
            user32.MoveWindow(wv_hwnd, 0, 0, w, h, True)

    container.bind("<Configure>", reposition)
    reposition()
    info.config(
        text=f"WebView pid={child.pid} HWND={wv_hwnd:#x} embedded",
        fg="#0a7")

    def on_close():
        try:
            child.terminate()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
