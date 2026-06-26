/**
 * News-desk component definitions — wire-shape defaults (ADR-0008 TS port of
 * `src/creations/news_desk/component_defs.py`).
 *
 * Addable-kind list (registration order + multi_instance) + each kind's default
 * instance dict in the news_desk WIRE shape. Canonical fraction sizes (fraction
 * of target_h/w), matching the merged TS contract — NOT absolute px. The owner
 * assigns the unique `id` (defaults intentionally omit it).
 */

export type ComponentDict = Record<string, unknown>;

function subtitle(): ComponentDict {
  return {
    kind: "subtitle",
    name: "字幕",
    enabled: true,
    srt_path: "",
    position: "bottom",
    block_margin_pct: 0.09, // fraction of target_h (9%)
    fontsize_pct: 0.026, // fraction of target_h (28px @ 1080)
    color: "#FFFF00",
    is_chinese: true,
    stroke_color: "#000000",
    stroke_pct: 0.002, // fraction of target_h (2px @ 1080)
    bg_enabled: true,
    bg_color: "#000000",
    bg_opacity: 55, // int 0–100
  };
}

function textWatermark(): ComponentDict {
  return {
    kind: "text_watermark",
    name: "文字水印",
    enabled: true,
    text: "",
    text_fontsize_pct: 0.026, // fraction of target_h (28px @ 1080)
    text_color: "#FFFFFF",
    text_opacity: 70, // int 0–100
    position: "top-right",
    margin_x_pct: 0.025, // fraction of target_w (2.5%)
    margin_y_pct: 0.025, // fraction of target_h
  };
}

function imageWatermark(): ComponentDict {
  return {
    kind: "image_watermark",
    name: "图片水印",
    enabled: true,
    image_path: "",
    image_scale: 0.15, // fraction of target_w (15%)
    image_opacity: 100, // int 0–100
    position: "top-right",
    margin_x_pct: 0.025,
    margin_y_pct: 0.025,
  };
}

function chapter(): ComponentDict {
  return {
    kind: "chapter",
    name: "章节",
    enabled: true,
    modes: { top_strip: true, start_card: false },
    style: {
      top_strip: { bg_color: "#1E40AF", text_color: "#FFFFFF", fontsize: 26 },
      start_card: {
        title_color: "#FFFFFF",
        title_fontsize: 40,
        body_color: "#E5E7EB",
        body_fontsize: 22,
        bg_color: "#0F1B2C",
        bg_opacity: 55,
        accent_color: "#DC2626",
        duration_sec: 6,
      },
    },
    schedule: [], // filled from material chapters at import
    titles: [], // AI-suggested video titles, filled from analysis titles[] at import
  };
}

function dubbing(): ComponentDict {
  return {
    kind: "dubbing",
    name: "配音",
    enabled: true,
    audio_path: "",
    gain_db: 0,
    source_gain_db: 0,
    offset_sec: 0,
    mode: "replace",
  };
}

const FACTORIES: Record<string, () => ComponentDict> = {
  chapter,
  subtitle,
  text_watermark: textWatermark,
  image_watermark: imageWatermark,
  dubbing,
};

export interface AddableKind {
  kind: string;
  multi_instance: boolean;
}

/** Registration order = [+ Add] menu order. Chapter is a singleton. */
export const ADDABLE: AddableKind[] = [
  { kind: "chapter", multi_instance: false },
  { kind: "subtitle", multi_instance: true },
  { kind: "text_watermark", multi_instance: true },
  { kind: "image_watermark", multi_instance: true },
  { kind: "dubbing", multi_instance: false },
];

export function defaultInstance(kind: string): ComponentDict {
  const factory = FACTORIES[kind];
  if (!factory) throw new Error(`unknown component kind: ${kind}`);
  return factory();
}
