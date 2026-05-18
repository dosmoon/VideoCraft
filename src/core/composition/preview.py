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
    # Legacy CompositionStyle still carries integer-pixel size fields;
    # we convert each to its short-edge pct here (the canvas only reads
    # pct now). Single point of legacy-px → pct translation.
    sub = style.subtitle
    wm = style.watermark
    ho = style.hook_outro
    return {
        "subtitle": {
            "position": sub.position,
            "stroke_color": sub.stroke_color,
            "stroke_pct": int(sub.stroke_width) / 1080.0,
            "block_margin_pct": sub.block_margin_pct,
            "track_gap_pct": sub.track_gap_pct,
            "sub1": {
                "enabled": sub.sub1.enabled,
                "fontsize_pct": int(sub.sub1.fontsize) / 1080.0,
                "color": sub.sub1.color,
                "bold": sub.sub1.bold,
                "bg_color": sub.sub1.bg_color,
                "bg_opacity": sub.sub1.bg_opacity,
                "bg_padding_x_pct": sub.sub1.bg_padding_x_pct,
                "text": ("字幕预览第一行 sub1"
                         if sub.sub1.is_chinese
                         else "Subtitle preview line 1"),
            },
            "sub2": {
                "enabled": sub.sub2.enabled,
                "fontsize_pct": int(sub.sub2.fontsize) / 1080.0,
                "color": sub.sub2.color,
                "bold": sub.sub2.bold,
                "bg_color": sub.sub2.bg_color,
                "bg_opacity": sub.sub2.bg_opacity,
                "bg_padding_x_pct": sub.sub2.bg_padding_x_pct,
                "text": ("字幕预览第二行 sub2"
                         if sub.sub2.is_chinese
                         else "Subtitle preview line 2"),
            },
        },
        "watermark": {
            "enabled": wm.enabled,
            "type": wm.type,
            "text": wm.text or "@channel",
            "text_fontsize_pct": int(wm.text_fontsize) / 1080.0,
            "text_color": wm.text_color,
            "text_opacity": wm.text_opacity,
            "image_path": wm.image_path,
            "image_scale": wm.image_scale,
            "image_opacity": wm.image_opacity,
            "position": wm.position,
            "margin_x_pct": wm.margin_x_pct,
            "margin_y_pct": wm.margin_y_pct,
        },
        "hookOutro": {
            "size_pct":           int(ho.size) / 1080.0,
            "color":              ho.color,
            "bg_color":           ho.bg_color,
            "bg_opacity":         ho.bg_opacity,
            "stroke_color":       ho.stroke_color,
            "stroke_pct":         int(ho.stroke_width) / 1080.0,
            "box_padding_pct":    int(ho.box_padding) / 1080.0,
            "hook_position":      ho.hook_position,
            "outro_position":     ho.outro_position,
            "hook_duration_sec":  ho.hook_duration_sec,
            "outro_duration_sec": ho.outro_duration_sec,
        },
        "aspect": style.aspect_ratio(),   # [w, h] tuple → JSON array
        "output_mode": style.output.mode,
        # News-desk overlay style library — dict-of-dicts, the JS canvas
        # pulls per-class styling for visible overlays at draw time.
        "overlay_styles": dict(style.overlay_styles or {}),
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
                 on_time: Optional[Callable[[int], None]] = None,
                 width: int = 480, height: int = 540):
        # Late import keeps this module importable in headless contexts.
        from ui.web_preview import WebPreviewFrame

        self._parent = parent
        self._on_crop = on_crop_changed
        self._on_time = on_time
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

    def set_geometry(self, output) -> None:
        """Push just output mode + aspect — used by timeline-driven
        consumers (news_desk) that don't carry a CompositionStyle.
        Timeline elements (via set_timeline) drive everything else."""
        aspect = output.aspect_ratio()
        self._call_js(f"window.vc.setOutputMode({json.dumps(output.mode)})")
        self._call_js(f"window.vc.setAspect({aspect[0]}, {aspect[1]})")

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

    def seek(self, sec: float) -> None:
        """Move the preview <video> playhead to `sec` (seconds, source-video
        time). Out-of-range values are clamped to the loaded clip window
        on the JS side (see `setSource` / `setClipRange`)."""
        self._call_js(f"window.vc.seek({float(sec)})")

    def set_cues(self, cues: list[dict]) -> None:
        """Push the primary subtitle cue list directly to the JS overlay.

        Cue shape: `{start: float, end: float, text: str}`. Used by
        preview surfaces (e.g. chapter_editor) that show subtitles as a
        navigation aid rather than as part of a render-parity pipeline.

        For timeline-driven previews (clip / news_desk) prefer
        `set_timeline(...)` — it carries the same wrap pass libass uses
        at render time so preview ≡ render holds (ADR-0006 #6).
        """
        self._call_js(
            f"window.vc.setCues({json.dumps(cues, ensure_ascii=False)})")

    def set_crop(self, rect: Optional[dict]) -> None:
        """Set the crop rect explicitly. None = recenter at current aspect."""
        payload = "null" if rect is None else json.dumps(rect)
        self._call_js(f"window.vc.setCrop({payload})")

    def enable_crop_drag(self, on: bool) -> None:
        """Toggle whether the user can drag the crop rect. Style-tab preview
        sets True (global crop drag); clip-tab preview also sets True (per-
        clip crop drag); other surfaces would pass False."""
        self._call_js(f"window.vc.enableCropDrag({'true' if on else 'false'})")

    def set_timeline(self, timeline,
                       *, aspect: str = "16:9", short_edge: int = 1080) -> None:
        """PR 4 unified entry — take a CompositionTimeline and push the
        equivalent of the 5 legacy bridges (overlays / extra_subtitles /
        extra_watermarks / hook+outro / sub1+sub2) by translating the IR
        back into per-bridge payloads.

        The 5 legacy bridges stay callable for clip until PR 5; this
        method just sits on top of them for news_desk's timeline-driven
        push path. The double-translation will collapse to a single JS
        setTimeline entry when clip migrates and the bridges retire.

        `aspect` / `short_edge` feed prepare_subtitle_cues so the wrap
        budget matches what the libass render will use — same source-
        of-truth call as the legacy _push_preview path.
        """
        from .render import _element_to_watermark_style
        from .style import (
            ChapterHeroCardStyle, SubtitleLineStyle, TopicStripStyle,
        )

        overlay_dicts: list[dict] = []
        sub_payload: list[dict] = []
        wm_payload: list[dict] = []
        hook_text = ""
        outro_text = ""
        hook_style: Optional[dict] = None
        outro_style: Optional[dict] = None

        for track in timeline.tracks:
            if not track.enabled:
                continue
            elements_by_kind: dict[str, list] = {}
            for e in track.elements:
                elements_by_kind.setdefault(e.kind, []).append(e)

            for kind, elements in elements_by_kind.items():
                if kind == "topic_strip":
                    for e in elements:
                        overlay_dicts.append({
                            "kind": "topic_strip",
                            "topic_text": e.data.get("topic_text", ""),
                            "start_sec": e.start_sec,
                            "end_sec": e.end_sec,
                            "style_class": e.data.get("style_class", "default"),
                            "z_order": track.z_base + e.z_offset,
                        })
                elif kind == "chapter_hero_card":
                    for e in elements:
                        overlay_dicts.append({
                            "kind": "chapter_hero_card",
                            "title": e.data.get("title", ""),
                            "body": e.data.get("body", ""),
                            "start_sec": e.start_sec,
                            "end_sec": e.end_sec,
                            "style_class": e.data.get("style_class", "default"),
                            "inline_style": e.data.get("inline_style", {}) or {},
                            "z_order": track.z_base + e.z_offset,
                        })
                elif kind == "subtitle_cue":
                    sd = elements[0].style
                    # Apply the SAME wrap pass render uses so preview
                    # cue text matches what libass burns. Without this
                    # long cues overflow the preview frame while the
                    # burned mp4 wraps them — a silent preview≠render
                    # divergence.
                    from .render import wrap_subtitle_elements
                    wrapped = wrap_subtitle_elements(
                        elements, aspect_str=aspect, short_edge=short_edge)
                    # All visible sizes ride as pct of short edge; JS
                    # multiplies them by canvas short edge to get px.
                    anchor_pct = float(sd.get(
                        "effective_block_margin_pct",
                        sd.get("block_margin_pct", 0.09)))
                    sub_payload.append({
                        "line": {
                            "fontsize_pct": float(
                                sd.get("fontsize_pct", 0.05)),
                            "color": sd.get("color", "#FFFFFF"),
                            "bold": bool(sd.get("bold", False)),
                            "is_chinese": bool(sd.get("is_chinese", False)),
                            "bg_color": sd.get("bg_color", "#000000"),
                            "bg_opacity": int(sd.get("bg_opacity", 0)),
                            "bg_padding_x_pct": float(
                                sd.get("bg_padding_x_pct", 0.0)),
                            "stroke_color": sd.get("stroke_color", "#000000"),
                            "stroke_pct": float(
                                sd.get("stroke_pct", 0.002)),
                        },
                        "position": sd.get("position", "bottom"),
                        "block_margin_pct": anchor_pct,
                        "cues": [
                            {"start": c.start.total_seconds(),
                              "end": c.end.total_seconds(),
                              "text": c.content}
                            for c in wrapped
                        ],
                        "z_order": track.z_base,
                    })
                elif kind in ("text_watermark", "image_watermark"):
                    # Preview side passes pct verbatim — canvas does its
                    # own `pct * canvas_short_edge` math, unaware of the
                    # target_h short_edge value.
                    for e in elements:
                        sd = e.style or {}
                        wm_payload.append({
                            "enabled": True,
                            "type": ("image" if e.kind == "image_watermark"
                                       else "text"),
                            "text": str((e.data or {}).get("text", "")),
                            "text_fontsize_pct": float(sd.get(
                                "text_fontsize_pct", 0.033)),
                            "text_color": sd.get("text_color", "#FFFFFF"),
                            "text_opacity": int(sd.get("text_opacity", 70)),
                            "image_path": str((e.data or {}).get(
                                "image_path", "")),
                            "image_scale": float(sd.get("image_scale", 0.15)),
                            "image_opacity": int(sd.get("image_opacity", 100)),
                            "position": sd.get("position", "top-right"),
                            "margin_x_pct": float(sd.get(
                                "margin_x_pct", 0.025)),
                            "margin_y_pct": float(sd.get(
                                "margin_y_pct", 0.025)),
                            "z_order": track.z_base + e.z_offset,
                        })
                elif kind == "hook_text":
                    for e in elements:
                        t = str(e.data.get("text", ""))
                        if t:
                            hook_text = t
                            # Per timeline.py convention, visual style
                            # lives on Element.style (not data).
                            if isinstance(e.style, dict) and e.style:
                                hook_style = e.style
                elif kind == "outro_text":
                    for e in elements:
                        t = str(e.data.get("text", ""))
                        if t:
                            outro_text = t
                            if isinstance(e.style, dict) and e.style:
                                outro_style = e.style

        # Drive the existing bridges with the translated payloads. Legacy
        # sub1/sub2 stack stays empty — timeline tracks ride the N-track
        # extras path (each track anchors independently).
        self._call_js(
            f"window.vc.setOverlays({json.dumps(overlay_dicts, ensure_ascii=False)})")
        self._call_js(f"window.vc.setCues([])")
        self._call_js(f"window.vc.setCuesSecondary([])")
        self._call_js(
            f"window.vc.setExtraSubtitles({json.dumps(sub_payload, ensure_ascii=False)})")
        self._call_js(
            f"window.vc.setExtraWatermarks({json.dumps(wm_payload, ensure_ascii=False)})")
        if hook_text or outro_text:
            # Pre-wrap with the SAME helper render's drawtext_filter uses, so
            # the WebView preview shows the exact line breaks libass burns
            # (ADR-0006 invariant #6 — preview ≡ render single-source).
            from .text_layout import wrap_hook_outro
            from .fonts import hook_outro_font_path
            try:
                aw, ah = (int(p) for p in str(aspect).split(":", 1))
                aspect_tuple = (aw, ah)
            except (TypeError, ValueError):
                aspect_tuple = (16, 9)
            meta: dict = {"hook": hook_text, "outro": outro_text}
            # Per-component styling: clip's hook/outro instances each
            # carry their own bg_color/color/etc. Pass the style dicts
            # through so JS reads the user's actual styling instead of
            # the legacy global styleState.hookOutro defaults.
            if hook_style is not None:
                meta["hookStyle"] = hook_style
            if outro_style is not None:
                meta["outroStyle"] = outro_style
            # Font px = pct * target_h (engine-wide font sizing
            # convention). target_h is derived from aspect_tuple +
            # short_edge so preview and render compute it identically.
            from .layout import font_size_px
            aw, ah = aspect_tuple
            target_h = (short_edge if aw >= ah
                          else int(round(short_edge * ah / aw)))
            if hook_text and hook_style is not None:
                font_path = hook_outro_font_path(hook_style.get("font"))
                size = font_size_px(
                    float(hook_style.get("size_pct", 0.05)), target_h)
                meta["hookLines"] = wrap_hook_outro(
                    hook_text, aspect_tuple, font_path, size,
                    short_edge=short_edge)
            if outro_text and outro_style is not None:
                font_path = hook_outro_font_path(outro_style.get("font"))
                size = font_size_px(
                    float(outro_style.get("size_pct", 0.05)), target_h)
                meta["outroLines"] = wrap_hook_outro(
                    outro_text, aspect_tuple, font_path, size,
                    short_edge=short_edge)
            self._call_js(
                f"window.vc.setClipMeta({json.dumps(meta, ensure_ascii=False)})")

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
        mtype = msg.get("type")
        if mtype == "crop" and self._on_crop:
            try:
                self._on_crop(msg.get("rect") or {})
            except Exception:
                pass
        elif mtype == "time" and self._on_time:
            try:
                self._on_time(int(msg.get("t") or 0))
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
