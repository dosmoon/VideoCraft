/**
 * Subtitle component — source-anchored caption cues rippled through the
 * assembly's TimeMap (invariant #6) into one overlay track of subtitle_cue
 * clips, each carrying the instance's inlined style.
 *
 * Unifies creations/clip/components/subtitle.py and
 * creations/news_desk/components/subtitle.py. Divergences resolved:
 *   - block_margin_pct: float fraction everywhere (news_desk's int% dropped).
 *   - bg_opacity: a plain 0..100 field (news_desk's separate bg_enabled flag
 *     folded in — opacity 0 means no background).
 *   - SRT sourcing: the host parses the SRT and passes `ctx.cues` in source
 *     time; the component stays pure (no I/O).
 */

import type { Track } from "../ir.js";
import { deriveOverlayTrack, type SourceAnchoredCue } from "../timemap.js";
import type { CompileContext, VideoComponent } from "./contract.js";

export interface SubtitleInstance {
  enabled: boolean;
  /** Optional subtitle-track language code (host-supplied picker). */
  language: string;
  fontsizePct: number; // fraction of target_h
  color: string;
  bold: boolean;
  isChinese: boolean;
  bgColor: string;
  bgOpacity: number; // 0..100
  bgPaddingXPct: number; // fraction of target_h
  strokeColor: string;
  strokePct: number; // fraction of target_h
  position: "top" | "bottom";
  blockMarginPct: number; // fraction of target_h
}

/** Inline the instance into the subtitle_cue primitive's style contract. */
function subtitleStyle(i: SubtitleInstance): Record<string, unknown> {
  return {
    fontsize_pct: i.fontsizePct,
    color: i.color,
    bold: i.bold,
    is_chinese: i.isChinese,
    bg_color: i.bgColor,
    bg_opacity: i.bgOpacity,
    bg_padding_x_pct: i.bgPaddingXPct,
    stroke_color: i.strokeColor,
    stroke_pct: i.strokePct,
    position: i.position,
    block_margin_pct: i.blockMarginPct,
  };
}

export const subtitle: VideoComponent<SubtitleInstance> = {
  kind: "subtitle",

  defaultInstance(): SubtitleInstance {
    return {
      enabled: true,
      language: "",
      fontsizePct: 0.05,
      color: "#FFFFFF",
      bold: false,
      isChinese: false,
      bgColor: "#000000",
      bgOpacity: 0,
      bgPaddingXPct: 0,
      strokeColor: "#000000",
      strokePct: 0.002,
      position: "bottom",
      blockMarginPct: 0.09,
    };
  },

  compile(instance: SubtitleInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || !ctx.cues || ctx.cues.length === 0) return [];
    const style = subtitleStyle(instance);
    const cues: SourceAnchoredCue[] = ctx.cues.map((c) => ({
      kind: "subtitle_cue",
      sourceStart: c.sourceStart,
      sourceEnd: c.sourceEnd,
      style,
      data: { text: c.text },
    }));
    return [deriveOverlayTrack(cues, ctx.timeMap)];
  },
};
