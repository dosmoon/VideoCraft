"""Smoke test for pywebview alone — no embedding, no Tk.

Tries three things in sequence (close window to advance to next):
  1. Load https://www.example.com  (proves WebView2 works at all)
  2. Load file:///<our html>       (proves file:// loading works)
  3. Inline HTML string             (proves pywebview render works without URL)
"""

import os
import sys
import webview


def main():
    html_path = os.path.abspath("verify_webview_step1.html")
    file_url = "file:///" + html_path.replace("\\", "/")

    print("Test 1: example.com")
    w = webview.create_window("smoke 1 — example.com", "https://www.example.com",
                               width=900, height=600)
    webview.start(debug=True)

    print("Test 2: local html via file:// URL")
    print(f"  URL = {file_url}")
    w = webview.create_window("smoke 2 — file://", file_url,
                               width=900, height=600)
    webview.start(debug=True)

    print("Test 3: inline html")
    inline = ("<html><body style='background:#0a0;color:#fff;font:30px sans'>"
              "<h1>HELLO FROM PYWEBVIEW</h1></body></html>")
    w = webview.create_window("smoke 3 — inline html", html=inline,
                               width=900, height=600)
    webview.start(debug=True)


if __name__ == "__main__":
    sys.exit(main())
