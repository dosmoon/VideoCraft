"""Child process: hosts a pywebview WebView2 window on its main thread.

Spawned by WebPreviewFrame (parent process). Communicates with the parent
over stdin/stdout JSON lines:

  Parent → child commands (one JSON object per line on stdin):
    {"cmd": "load_url", "url": "..."}
    {"cmd": "load_html", "html": "..."}
    {"cmd": "eval", "code": "..."}
    {"cmd": "quit"}

  Child → parent events (one JSON object per line on stdout):
    {"event": "ready"}                       window object created
    {"event": "loaded"}                      page finished loading
    {"event": "message", "data": {...}}      JS called window.pywebview.api.notify(...)
    {"event": "closed"}                      user closed the window

The window is created frameless so the parent can SetParent it cleanly into
a Tk frame. Title is unique-per-process so the parent can find the HWND.

Run: python -m ui.web_preview_host <title> [<url>]
"""

from __future__ import annotations

import json
import sys
import threading

# Force UTF-8 for stdin/stdout regardless of Windows console code page —
# the parent sends JSON with ensure_ascii=False (may contain CJK), and a
# default GBK decode would silently mojibake the JSON payload, breaking
# evaluate_js calls without raising.
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import webview


def _emit(event: str, **fields) -> None:
    """Write one JSON line to stdout and flush."""
    payload = {"event": event}
    payload.update(fields)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class _Api:
    """Exposed to JavaScript as window.pywebview.api.

    JS calls window.pywebview.api.notify({...}) — this surfaces back to the
    parent process as {"event": "message", "data": {...}}.
    """

    def notify(self, data) -> None:
        _emit("message", data=data)


def _stdin_pump(window) -> None:
    """Read commands from parent stdin and dispatch to the WebView."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd = msg.get("cmd")
        try:
            if cmd == "load_url":
                window.load_url(msg["url"])
            elif cmd == "load_html":
                window.load_html(msg["html"])
            elif cmd == "eval":
                window.evaluate_js(msg["code"])
            elif cmd == "quit":
                window.destroy()
                return
        except Exception as e:
            _emit("error", message=f"{cmd}: {e}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: web_preview_host.py <title> [<url>]", file=sys.stderr)
        return 1
    title = sys.argv[1]
    url = sys.argv[2] if len(sys.argv) >= 3 else "about:blank"

    api = _Api()
    window = webview.create_window(
        title, url, width=1100, height=700,
        frameless=True, easy_drag=False, js_api=api)

    def on_loaded():
        _emit("loaded")

    def on_closed():
        _emit("closed")

    window.events.loaded += on_loaded
    window.events.closed += on_closed

    # Stdin reader runs alongside the GUI loop
    t = threading.Thread(target=_stdin_pump, args=(window,), daemon=True)
    t.start()

    _emit("ready")
    webview.start(gui="edgechromium", debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
