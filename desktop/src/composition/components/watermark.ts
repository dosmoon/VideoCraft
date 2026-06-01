/**
 * Watermark components — text and image, each a single full-duration overlay.
 *
 * Unifies creations/clip/components/watermark.py and
 * creations/news_desk/components/{text,image}_watermark.py. Divergences
 * resolved (pre-alpha, no legacy):
 *   - all *_pct fields are float fractions (news_desk's stored ints dropped).
 *   - text size/opacity keys are `text_fontsize_pct` / `text_opacity`
 *     (news_desk's `fontsize_pct` / `opacity` dropped).
 *   - image scale key is `image_scale` (news_desk's `scale_pct` dropped).
 *   - text watermark no longer emits spurious image_* style keys.
 */

import { clip, type Track } from "../ir.js";
import { packOverlaySegments } from "../assemble.js";
import type { CompileContext, VideoComponent } from "./contract.js";
import type { FieldSpec } from "./fieldSpec.js";

export type WatermarkPosition = "top-left" | "top-right" | "bottom-left" | "bottom-right";

// ── Shared edit-UI bits (anchor dropdown + margins) ─────────────────────────

const ANCHOR_OPTIONS = ["top-left", "top-right", "bottom-left", "bottom-right"] as const;
const ANCHOR_LABEL_KEYS: Record<string, string> = {
  "top-left": "watermark.anchor.top_left",
  "top-right": "watermark.anchor.top_right",
  "bottom-left": "watermark.anchor.bottom_left",
  "bottom-right": "watermark.anchor.bottom_right",
};

const positionField: FieldSpec = {
  key: "position",
  control: "select",
  labelKey: "watermark.anchor",
  options: ANCHOR_OPTIONS,
  optionLabelKeys: ANCHOR_LABEL_KEYS,
};
// Margins are fractions of the frame; shown as % (Tk convention), hint-bounded [0, 0.2].
const marginFields: FieldSpec[] = [
  { key: "margin_x_pct", control: "number", labelKey: "watermark.margin_x", min: 0, max: 0.2, display: { factor: 100, step: 0.5, suffix: "%" } },
  { key: "margin_y_pct", control: "number", labelKey: "watermark.margin_y", min: 0, max: 0.2, display: { factor: 100, step: 0.5, suffix: "%" } },
];

// ── Text watermark ─────────────────────────────────────────────────────────

export interface TextWatermarkInstance {
  enabled: boolean;
  text: string;
  textFontsizePct: number; // fraction of target_h
  textColor: string;
  textOpacity: number; // 0..100
  position: WatermarkPosition;
  marginXPct: number; // fraction of target_w
  marginYPct: number; // fraction of target_h
}

export const textWatermark: VideoComponent<TextWatermarkInstance> = {
  kind: "text_watermark",

  defaultInstance(): TextWatermarkInstance {
    return {
      enabled: true,
      text: "",
      textFontsizePct: 0.033,
      textColor: "#FFFFFF",
      textOpacity: 70,
      position: "top-right",
      marginXPct: 0.025,
      marginYPct: 0.025,
    };
  },

  compile(instance: TextWatermarkInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || instance.text.trim() === "") return [];
    const c = clip({
      kind: "text_watermark",
      durationSec: ctx.durationSec,
      style: {
        text_fontsize_pct: instance.textFontsizePct,
        text_color: instance.textColor,
        text_opacity: instance.textOpacity,
        position: instance.position,
        margin_x_pct: instance.marginXPct,
        margin_y_pct: instance.marginYPct,
      },
      data: { text: instance.text },
    });
    return [packOverlaySegments([{ startSec: 0, endSec: ctx.durationSec, clip: c }])];
  },
};

/** Edit-UI fields (wire snake keys; both plugins share these post-normalisation). */
export const textWatermarkFields: readonly FieldSpec[] = [
  { key: "name", control: "text", labelKey: "watermark.name" },
  { key: "text", control: "text", labelKey: "watermark.text" },
  { key: "text_fontsize_pct", control: "number", labelKey: "watermark.fontsize", min: 0, max: 0.5, display: { factor: 1080, step: 1, suffix: "px" } },
  { key: "text_color", control: "color", labelKey: "watermark.color" },
  { key: "text_opacity", control: "number", labelKey: "watermark.opacity", min: 0, max: 100, display: { factor: 1, step: 1, suffix: "%" } },
  positionField,
  ...marginFields,
];

// ── Image watermark ──────────────────────────────────────────────────────────

export interface ImageWatermarkInstance {
  enabled: boolean;
  imagePath: string;
  imageScale: number; // fraction of target_w
  imageOpacity: number; // 0..100
  position: WatermarkPosition;
  marginXPct: number; // fraction of target_w
  marginYPct: number; // fraction of target_h
}

export const imageWatermark: VideoComponent<ImageWatermarkInstance> = {
  kind: "image_watermark",

  defaultInstance(): ImageWatermarkInstance {
    return {
      enabled: true,
      imagePath: "",
      imageScale: 0.15,
      imageOpacity: 100,
      position: "top-right",
      marginXPct: 0.025,
      marginYPct: 0.025,
    };
  },

  compile(instance: ImageWatermarkInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || instance.imagePath.trim() === "") return [];
    const c = clip({
      kind: "image_watermark",
      durationSec: ctx.durationSec,
      style: {
        image_scale: instance.imageScale,
        image_opacity: instance.imageOpacity,
        position: instance.position,
        margin_x_pct: instance.marginXPct,
        margin_y_pct: instance.marginYPct,
      },
      data: { image_path: instance.imagePath },
    });
    return [packOverlaySegments([{ startSec: 0, endSec: ctx.durationSec, clip: c }])];
  },
};

/** Edit-UI fields (wire snake keys; both plugins share these post-normalisation). */
export const imageWatermarkFields: readonly FieldSpec[] = [
  { key: "name", control: "text", labelKey: "watermark.name" },
  { key: "image_path", control: "image", labelKey: "watermark.image_file" },
  { key: "image_scale", control: "number", labelKey: "watermark.scale", min: 0.02, max: 0.5, display: { factor: 100, step: 1, suffix: "%" } },
  { key: "image_opacity", control: "number", labelKey: "watermark.opacity", min: 0, max: 100, display: { factor: 1, step: 1, suffix: "%" } },
  positionField,
  ...marginFields,
];
