"""Standalone pywebview host process. Spawned by verify_webview_step2.py.

Single responsibility: open a frameless WebView2 window with the given title
and URL, on the main thread (which pywebview demands). The parent process
finds this window's HWND by title and reparents it via Win32 SetParent.

Usage: python verify_webview_host.py <title> <url>
"""

import sys
import webview


def main():
    if len(sys.argv) != 3:
        print("usage: webview_host.py <title> <url>", file=sys.stderr)
        sys.exit(1)
    title, url = sys.argv[1], sys.argv[2]
    webview.create_window(title, url, width=1100, height=700,
                           frameless=True, easy_drag=False)
    webview.start(gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
