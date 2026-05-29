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

export type WatermarkPosition = "top-left" | "top-right" | "bottom-left" | "bottom-right";

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
