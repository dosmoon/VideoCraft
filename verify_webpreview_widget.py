"""Verify the WebPreviewFrame wrapper from src/ui/web_preview.py.

Embeds the same Step 1 HTML, but via the encapsulated widget with stdin/stdout
IPC. Demonstrates load_url, evaluate_js, and on_message round-trip.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ui.web_preview import WebPreviewFrame, setup_dpi_aware  # noqa: E402

# Must run before any Tk window is created.
setup_dpi_aware()


def main():
    root = tk.Tk()
    root.title("VideoCraft – WebPreviewFrame test")
    root.geometry("1200x820")

    info_var = tk.StringVar(value="(no message yet)")

    bar = ttk.Frame(root)
    bar.pack(fill="x", padx=8, pady=4)
    ttk.Label(bar, textvariable=info_var, foreground="#0a7").pack(side="left")

    def on_msg(data):
        info_var.set(f"JS → Py: {data}")

    def on_loaded():
        info_var.set("page loaded")

    html_path = os.path.abspath("verify_webview_step1.html")
    file_url = "file:///" + html_path.replace("\\", "/")

    web = WebPreviewFrame(root, on_message=on_msg, on_loaded=on_loaded,
                          initial_url=file_url)
    web.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # Demo: poke a message from JS back through the IPC bridge
    def poke():
        web.evaluate_js(
            "window.pywebview.api.notify({hello: 'from JS', t: Date.now()});")
    ttk.Button(bar, text="ping JS → Py", command=poke).pack(side="right")

    def on_close():
        web.destroy()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
