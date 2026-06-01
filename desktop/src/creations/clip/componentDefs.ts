/**
 * Clip component definitions — wire-shape default instances (ADR-0008 TS port).
 *
 * Faithful port of `src/creations/clip/component_defs.py`: the addable-kind list
 * (registration order + multi_instance gating) and each kind's default instance
 * dict in the PLUGIN WIRE shape (snake_case keys, kind = "clip_subtitle" …).
 *
 * NB: these are the clip plugin's wire defaults, NOT the canonical component
 * library defaults in `composition/components/*` (which are camelCase and feed
 * compile→OTIO). The config owner stores these wire dicts verbatim; mapping.ts
 * converts wire→canonical at assembly time. So porting clip genuinely needs this
 * file — the canonical defaults already in TS are a different layer.
 */

/** A stored component instance is an opaque wire dict (mirrors Python list[dict]). */
export type ComponentDict = Record<string, unknown>;

function subtitle(): ComponentDict {
  return {
    kind: "clip_subtitle",
    id: "sub1",
    name: "subtitle",
    enabled: true,
    language: "",
    fontsize_pct: 0.05,
    color: "#FFFFFF",
    bold: false,
    is_chinese: false,
    bg_color: "#000000",
    bg_opacity: 0,
    bg_padding_x_pct: 0.0,
    stroke_color: "#000000",
    stroke_pct: 0.002,
    position: "bottom",
    block_margin_pct: 0.09,
  };
}

function textWatermark(): ComponentDict {
  return {
    kind: "clip_text_watermark",
    id: "wm_text",
    name: "text watermark",
    enabled: true,
    text: "",
    text_fontsize_pct: 0.033,
    text_color: "#FFFFFF",
    text_opacity: 70,
    position: "top-right",
    margin_x_pct: 0.025,
    margin_y_pct: 0.025,
  };
}

function imageWatermark(): ComponentDict {
  return {
    kind: "clip_image_watermark",
    id: "wm_image",
    name: "image watermark",
    enabled: true,
    image_path: "",
    image_scale: 0.15,
    image_opacity: 100,
    position: "top-right",
    margin_x_pct: 0.025,
    margin_y_pct: 0.025,
  };
}

function hookCard(): ComponentDict {
  return {
    kind: "clip_hook_card",
    id: "hook",
    name: "hook card",
    enabled: true,
    text: "",
    font: "Microsoft YaHei",
    size_pct: 0.05,
    color: "#FFFFFF",
    bg_color: "#000000",
    bg_opacity: 70,
    stroke_color: "#000000",
    stroke_pct: 0.003,
    box_padding_pct: 0.012,
    position: "upper-third",
    duration_sec: 5.0,
  };
}

function outroCard(): ComponentDict {
  return {
    kind: "clip_outro_card",
    id: "outro",
    name: "outro card",
    enabled: true,
    text: "",
    font: "Microsoft YaHei",
    size_pct: 0.05,
    color: "#FFFFFF",
    bg_color: "#000000",
    bg_opacity: 70,
    stroke_color: "#000000",
    stroke_pct: 0.003,
    box_padding_pct: 0.012,
    position: "lower-third",
    duration_sec: 5.0,
  };
}

const FACTORIES: Record<string, () => ComponentDict> = {
  clip_subtitle: subtitle,
  clip_text_watermark: textWatermark,
  clip_image_watermark: imageWatermark,
  clip_hook_card: hookCard,
  clip_outro_card: outroCard,
};

export interface AddableKind {
  kind: string;
  multi_instance: boolean;
}

/** Registration order = [+ Add] menu order (mirrors the Tk specs' register()). */
export const ADDABLE: AddableKind[] = [
  { kind: "clip_subtitle", multi_instance: true },
  { kind: "clip_text_watermark", multi_instance: true },
  { kind: "clip_image_watermark", multi_instance: true },
  { kind: "clip_hook_card", multi_instance: false },
  { kind: "clip_outro_card", multi_instance: false },
];

/** A fresh default instance dict for `kind`. Throws on an unknown kind. */
export function defaultInstance(kind: string): ComponentDict {
  const factory = FACTORIES[kind];
  if (!factory) throw new Error(`unknown component kind: ${kind}`);
  return factory();
}
