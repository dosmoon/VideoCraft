"""Clip hook & outro components — separate specs, shared style helper.

Two registered specs: clip_hook_card (compiles to hook_text primitive)
and clip_outro_card (compiles to outro_text primitive). Each instance
dict carries its own text and the full style field set; the renderer
reads the same flat style dict shape build_clip_timeline used to emit
inline, so byte-shape stays stable.

Per-candidate text (the AI-generated or user-edited hook / outro
text) is filled into the instance dict by `hookoutro_adapters_from_style`
at render time — there is no engine-level ctx side-channel.

Both specs share `_card_style_dict()` for the font / color / bg /
stroke fields (matches HookOutroStyle for hook AND outro). The
position field differs (hook_position vs outro_position) and the
time-window math differs ([0, duration] vs [end-duration, end]).
"""

from __future__ import annotations

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec

from . import ComponentDictAdapter, register


KIND_HOOK = "clip_hook_card"
KIND_OUTRO = "clip_outro_card"


# ── default_instance ───────────────────────────────────────────────────────

def _default_hook_instance(_duration: float) -> dict:
    return {
        "kind": KIND_HOOK,
        "id": "hook",
        "name": "hook card",
        "enabled": True,
        "text": "",
        "font": "Microsoft YaHei",
        "size": 48,
        "color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 70,
        "stroke_color": "#000000",
        "stroke_width": 3,
        "box_padding": 10,
        "position": "upper-third",
        "duration_sec": 5.0,
    }


def _default_outro_instance(_duration: float) -> dict:
    return {
        "kind": KIND_OUTRO,
        "id": "outro",
        "name": "outro card",
        "enabled": True,
        "text": "",
        "font": "Microsoft YaHei",
        "size": 48,
        "color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 70,
        "stroke_color": "#000000",
        "stroke_width": 3,
        "box_padding": 10,
        "position": "lower-third",
        "duration_sec": 5.0,
    }


# ── style dict — matches what build_clip_timeline emitted pre-5.3 ─────────

def _card_style_dict(instance: dict, position_role: str) -> dict:
    """Pack flat style dict the renderer's drawtext_filter consumes.

    `position_role` is "hook" or "outro"; the renderer expects
    hook_position / outro_position keys (not a generic "position"),
    so we stamp both — only the role-matching one is actually read
    but keeping both keeps byte-equality with the pre-5.3 dict shape.
    """
    return {
        "font": instance.get("font", "Microsoft YaHei"),
        "size": int(instance.get("size", 48)),
        "color": instance.get("color", "#FFFFFF"),
        "bg_color": instance.get("bg_color", "#000000"),
        "bg_opacity": int(instance.get("bg_opacity", 70)),
        "stroke_color": instance.get("stroke_color", "#000000"),
        "stroke_width": int(instance.get("stroke_width", 3)),
        "box_padding": int(instance.get("box_padding", 10)),
        # Stamp the role-specific position the renderer looks up
        "hook_position": (instance.get("position", "upper-third")
                            if position_role == "hook" else "upper-third"),
        "outro_position": (instance.get("position", "lower-third")
                             if position_role == "outro" else "lower-third"),
        "hook_duration_sec": (float(instance.get("duration_sec", 5.0))
                                if position_role == "hook" else 5.0),
        "outro_duration_sec": (float(instance.get("duration_sec", 5.0))
                                 if position_role == "outro" else 5.0),
    }


# ── compile — hook ─────────────────────────────────────────────────────────

def _compile_hook(instance: dict, clip_range: ClipRange,
                   _ctx: CompileContext) -> list[Element]:
    text = (instance.get("text") or "").strip()
    duration = float(instance.get("duration_sec", 0.0))
    if not text or duration <= 0:
        return []
    end = min(clip_range.duration_sec, duration)
    if end <= 0:
        return []
    return [Element(
        kind="hook_text",
        start_sec=0.0,
        end_sec=end,
        data={"text": instance.get("text", ""),
               "style": _card_style_dict(instance, "hook")},
    )]


# ── compile — outro ────────────────────────────────────────────────────────

def _compile_outro(instance: dict, clip_range: ClipRange,
                    _ctx: CompileContext) -> list[Element]:
    text = (instance.get("text") or "").strip()
    duration = float(instance.get("duration_sec", 0.0))
    if not text or duration <= 0:
        return []
    start = max(0.0, clip_range.duration_sec - duration)
    if clip_range.duration_sec <= start:
        return []
    return [Element(
        kind="outro_text",
        start_sec=start,
        end_sec=clip_range.duration_sec,
        data={"text": instance.get("text", ""),
               "style": _card_style_dict(instance, "outro")},
    )]


# ── Seeder — legacy HookOutroStyle + per-candidate text → adapters ─────────

def hookoutro_adapters_from_style(
    style: CompositionStyle,
    *,
    hook_text: str = "",
    outro_text: str = "",
) -> list[ComponentDictAdapter]:
    """Build at most two transient adapters — one hook, one outro —
    using the legacy HookOutroStyle as the style template and the
    per-candidate texts as the data fill-ins. Empty text → no adapter
    for that role (matches pre-5.3 behaviour where empty hook_text or
    outro_text simply produced no Element).

    Step 5.3 — temporary bridge. Retires with Step 5.5 alongside
    StylePanel's hook/outro form.
    """
    ho = style.hook_outro
    adapters: list[ComponentDictAdapter] = []

    if hook_text and ho.hook_duration_sec > 0:
        adapters.append(ComponentDictAdapter({
            "kind": KIND_HOOK,
            "id": "hook",
            "name": "hook",
            "enabled": True,
            "text": hook_text,
            "font": ho.font,
            "size": int(ho.size),
            "color": ho.color,
            "bg_color": ho.bg_color,
            "bg_opacity": int(ho.bg_opacity),
            "stroke_color": ho.stroke_color,
            "stroke_width": int(ho.stroke_width),
            "box_padding": int(ho.box_padding),
            "position": ho.hook_position,
            "duration_sec": float(ho.hook_duration_sec),
        }))

    if outro_text and ho.outro_duration_sec > 0:
        adapters.append(ComponentDictAdapter({
            "kind": KIND_OUTRO,
            "id": "outro",
            "name": "outro",
            "enabled": True,
            "text": outro_text,
            "font": ho.font,
            "size": int(ho.size),
            "color": ho.color,
            "bg_color": ho.bg_color,
            "bg_opacity": int(ho.bg_opacity),
            "stroke_color": ho.stroke_color,
            "stroke_width": int(ho.stroke_width),
            "box_padding": int(ho.box_padding),
            "position": ho.outro_position,
            "duration_sec": float(ho.outro_duration_sec),
        }))

    return adapters


# ── register ───────────────────────────────────────────────────────────────

register(ComponentSpec(
    kind=KIND_HOOK,
    name_key="clip.component.hook_card.name",
    add_label_key="clip.component.hook_card.add",
    multi_instance=False,
    default_z=90,
    default_instance=_default_hook_instance,
    build_property_panel=None,    # lands with 5.5
    compile=_compile_hook,
))

register(ComponentSpec(
    kind=KIND_OUTRO,
    name_key="clip.component.outro_card.name",
    add_label_key="clip.component.outro_card.add",
    multi_instance=False,
    default_z=90,
    default_instance=_default_outro_instance,
    build_property_panel=None,    # lands with 5.5
    compile=_compile_outro,
))
