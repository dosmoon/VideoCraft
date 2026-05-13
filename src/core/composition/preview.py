"""WebView-backed video-level realtime preview for CompositionStyle.

Mirrors the same style schema that render.py consumes, so the WebView page
shows the same layout the ffmpeg render will produce — subtitle position,
hook/outro card, watermark, aspect crop. Pixel-level parity isn't promised
(CSS fonts vs libass), but layout-level parity is.

This module is a thin adapter: it owns the JSON serialization of the style
and the JS calls to drive the page. The page itself is
`src/ui/composition_preview.html`; the WebView2-in-tk plumbing is in
`src/ui/web_preview.py`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Callable, Optional

from .style import CompositionStyle


def style_to_web_dict(style: CompositionStyle) -> dict:
    """Translate CompositionStyle into the JSON shape vc.setStyle() expects.

    The page renders placeholder subtitle text; the real per-cue text is
    pushed separately via set_cues() so layout and content stay orthogonal.
    """
    sub = style.subtitle
    wm = style.watermark
    ho = style.hook_outro
    return {
        "subtitle": {
            "position": sub.position,
            "stroke_color": sub.stroke_color,
            "stroke_width": sub.stroke_width,
            "sub1": {
                "enabled": sub.sub1.enabled,
                "fontsize": sub.sub1.fontsize,
                "color": sub.sub1.color,
                "bold": sub.sub1.bold,
                "text": ("字幕预览第一行 sub1"
                         if sub.sub1.is_chinese
                         else "Subtitle preview line 1"),
            },
            "sub2": {
                "enabled": sub.sub2.enabled,
                "fontsize": sub.sub2.fontsize,
                "color": sub.sub2.color,
                "bold": sub.sub2.bold,
                "text": ("字幕预览第二行 sub2"
                         if sub.sub2.is_chinese
                         else "Subtitle preview line 2"),
            },
        },
        "watermark": {
            "enabled": wm.enabled,
            "type": wm.type,
            "text": wm.text or "@channel",
            "text_fontsize": wm.text_fontsize,
            "text_color": wm.text_color,
            "text_opacity": wm.text_opacity,
            "image_scale": wm.image_scale,
            "image_opacity": wm.image_opacity,
            "position": wm.position,
        },
        "hookOutro": {
            "size":               ho.size,
            "color":              ho.color,
            "bg_color":           ho.bg_color,
            "bg_opacity":         ho.bg_opacity,
            "stroke_color":       ho.stroke_color,
            "stroke_width":       ho.stroke_width,
            "box_padding":        ho.box_padding,
            "hook_position":      ho.hook_position,
            "outro_position":     ho.outro_position,
            "hook_duration_sec":  ho.hook_duration_sec,
            "outro_duration_sec": ho.outro_duration_sec,
        },
        "aspect": style.aspect_ratio(),   # [w, h] tuple → JSON array
        "output_mode": style.output.mode,
    }


# ── Tk widget wrapper ──────────────────────────────────────────────────────

# Late-imported (web_preview pulls in ctypes/subprocess) so style/render can
# be imported in headless test contexts without dragging WebView2 along.

class CompositionPreview:
    """Composition preview surface — wraps WebPreviewFrame + composition_preview.html.

    Lifecycle:
        preview = CompositionPreview(parent_frame, on_crop_changed=cb)
        preview.set_source(video_path, start_sec, end_sec)
        preview.set_style(style)              # whenever style changes
        preview.set_clip_meta(hook="...", outro="...")
        preview.destroy()                     # on tab close

    All public methods are safe to call before the page has finished
    loading; they're queued and replayed on `on_loaded`.
    """

    _HTML_REL = "ui/composition_preview.html"

    def __init__(self, parent,
                 on_crop_changed: Optional[Callable[[dict], None]] = None,
                 width: int = 480, height: int = 540):
        # Late import keeps this module importable in headless contexts.
        from ui.web_preview import WebPreviewFrame

        self._parent = parent
        self._on_crop = on_crop_changed
        self._loaded = False
        self._pending: list[str] = []

        # Resolve composition_preview.html via src/ root. Passing it as
        # initial_url (not a follow-up load_url call) is critical: the
        # WebView child is spawned asynchronously, and any command sent
        # before spawn completes is silently dropped by _send().
        here = os.path.dirname(os.path.abspath(__file__))    # src/core/composition
        src_root = os.path.normpath(os.path.join(here, "..", ".."))
        html_path = os.path.join(src_root, self._HTML_REL)
        initial_url = ("file:///" + html_path.replace("\\", "/")
                        if os.path.isfile(html_path) else "about:blank")

        self._frame = WebPreviewFrame(
            parent,
            on_message=self._on_message,
            on_loaded=self._on_loaded,
            initial_url=initial_url,
            width=width, height=height,
        )

    # ── public API ────────────────────────────────────────────────────────

    @property
    def widget(self):
        """Underlying tk Frame — pack/grid this where the preview should appear."""
        return self._frame

    def set_source(self, video_path: str,
                   start_sec: float = 0.0, end_sec: float = 0.0) -> None:
        """Point the <video> element at a source file and loop the given window.
        Pass start_sec=0, end_sec=0 to play the whole file."""
        url = "file:///" + video_path.replace("\\", "/")
        self._call_js(f"window.vc.setSource({json.dumps(url)}, "
                       f"{start_sec}, {end_sec})")

    def set_clip_range(self, start_sec: float, end_sec: float) -> None:
        self._call_js(f"window.vc.setClipRange({start_sec}, {end_sec})")

    def set_style(self, style: CompositionStyle) -> None:
        payload = style_to_web_dict(style)
        aspect = payload.pop("aspect")
        mode = payload.pop("output_mode", "reframe")
        # Push mode first so subsequent setAspect lands in the right
        # interpretation. In passthrough the JS ignores the aspect value
        # and uses the video element's natural dims instead.
        self._call_js(f"window.vc.setOutputMode({json.dumps(mode)})")
        self._call_js(f"window.vc.setAspect({aspect[0]}, {aspect[1]})")
        self._call_js(f"window.vc.setStyle({json.dumps(payload, ensure_ascii=False)})")

    def set_clip_meta(self, hook: str = "", outro: str = "",
                       hook_lines: Optional[list[str]] = None,
                       outro_lines: Optional[list[str]] = None) -> None:
        """Push hook/outro overlay state.

        Callers SHOULD pass `hook_lines` / `outro_lines` pre-computed via
        core.composition.text_layout.wrap_hook_outro — these are the exact
        lines the ffmpeg render will use, guaranteeing preview ≡ output
        layout. The raw `hook` / `outro` strings are still accepted as a
        fallback (JS will wrap them on its own; layout may diverge).
        """
        meta: dict = {"hook": hook, "outro": outro}
        if hook_lines is not None:
            meta["hookLines"] = hook_lines
        if outro_lines is not None:
            meta["outroLines"] = outro_lines
        self._call_js(f"window.vc.setClipMeta({json.dumps(meta, ensure_ascii=False)})")

    def set_cues(self, cues: list[dict]) -> None:
        """Push the primary (sub1) cue list for the current clip window.
        Each cue: {start: float, end: float, text: str}. Pass [] to
        clear and fall back to the placeholder text from style.subtitle.sub1.

        Callers should obtain `cues` from core.composition.prepare_subtitle_cues
        so the cue list reflects the same slice + max_chars wrap the
        ffmpeg burn will produce — preview ≡ render."""
        self._call_js(f"window.vc.setCues({json.dumps(cues, ensure_ascii=False)})")

    def set_cues_secondary(self, cues: list[dict]) -> None:
        """Push the secondary (sub2) cue list. Same shape and same source
        (prepare_subtitle_cues) as set_cues; drives the sub2 overlay.
        Without this call sub2 falls back to placeholder text — useful for
        clip-style previews, wrong for bilingual burn where both tracks
        carry real cues."""
        self._call_js(f"window.vc.setCuesSecondary({json.dumps(cues, ensure_ascii=False)})")

    def set_crop(self, rect: Optional[dict]) -> None:
        """Set the crop rect explicitly. None = recenter at current aspect."""
        payload = "null" if rect is None else json.dumps(rect)
        self._call_js(f"window.vc.setCrop({payload})")

    def enable_crop_drag(self, on: bool) -> None:
        """Toggle whether the user can drag the crop rect. Style-tab preview
        sets True (global crop drag); clip-tab preview also sets True (per-
        clip crop drag); other surfaces would pass False."""
        self._call_js(f"window.vc.enableCropDrag({'true' if on else 'false'})")

    def clear(self) -> None:
        self._call_js("window.vc.clear()")

    def destroy(self) -> None:
        try:
            self._frame.destroy()
        except Exception:
            pass

    # ── plumbing ──────────────────────────────────────────────────────────

    def _on_loaded(self) -> None:
        self._loaded = True
        for code in self._pending:
            try:
                self._frame.evaluate_js(code)
            except Exception:
                pass
        self._pending.clear()

    def _on_message(self, msg: dict) -> None:
        if msg.get("type") == "crop" and self._on_crop:
            try:
                self._on_crop(msg.get("rect") or {})
            except Exception:
                pass

    def _call_js(self, code: str) -> None:
        if not self._loaded:
            self._pending.append(code)
            return
        try:
            self._frame.evaluate_js(code)
        except Exception:
            pass
