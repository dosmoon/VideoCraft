/**
 * Chapter component — a singleton driven by a chapter schedule (source-time
 * rows). Two independently-toggled layers:
 *   - top_strip   → topic_strip clip spanning each chapter [start, end)
 *   - start_card  → chapter_hero_card clip for the first `durationSec` of each
 *
 * The two layers overlap in time, so they compile to *separate* overlay tracks
 * (a single relative track cannot hold overlapping clips). Schedule rows are
 * source-anchored and ripple through `ctx.timeMap` (invariant #6).
 *
 * Ports creations/news_desk/components/chapter.py. Improvement over the legacy
 * primitive contract: the per-instance style is *inlined onto the clip*
 * (foundation doc §2.5 "style inlined at compile — no late style-library
 * lookup at render"), instead of being looked up from an overlay_styles
 * registry by `style_class`.
 */

import type { Track } from "../ir.js";
import { deriveOverlayTrack, type SourceAnchoredCue } from "../timemap.js";
import type { CompileContext, VideoComponent } from "./contract.js";
import type { FieldSpec } from "./fieldSpec.js";

export interface ChapterRow {
  startSec: number; // source time
  endSec: number; // source time
  title: string;
  refined: string;
  keyPoints: string[];
}

export interface TopStripStyle {
  bgColor: string;
  textColor: string;
  fontsize: number; // px (legacy absolute; kept until layout normalisation)
}

export interface StartCardStyle {
  titleColor: string;
  titleFontsize: number;
  bodyColor: string;
  bodyFontsize: number;
  bgColor: string;
  bgOpacity: number; // 0..100
  accentColor: string;
  durationSec: number;
}

export interface ChapterInstance {
  enabled: boolean;
  modes: { topStrip: boolean; startCard: boolean };
  style: { topStrip: TopStripStyle; startCard: StartCardStyle };
  schedule: ChapterRow[];
}

export const chapter: VideoComponent<ChapterInstance> = {
  kind: "chapter",

  defaultInstance(): ChapterInstance {
    return {
      enabled: true,
      modes: { topStrip: true, startCard: false },
      style: {
        topStrip: { bgColor: "#1E40AF", textColor: "#FFFFFF", fontsize: 26 },
        startCard: {
          titleColor: "#FFFFFF",
          titleFontsize: 40,
          bodyColor: "#E5E7EB",
          bodyFontsize: 22,
          bgColor: "#0F1B2C",
          bgOpacity: 55,
          accentColor: "#DC2626",
          durationSec: 6,
        },
      },
      schedule: [],
    };
  },

  compile(instance: ChapterInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || instance.schedule.length === 0) return [];
    const tracks: Track[] = [];

    if (instance.modes.topStrip) {
      const s = instance.style.topStrip;
      const stripStyle = {
        bg_color: s.bgColor,
        text_color: s.textColor,
        fontsize: s.fontsize,
      };
      const cues: SourceAnchoredCue[] = instance.schedule
        .filter((row) => row.title.trim() !== "" && row.endSec > row.startSec)
        .map((row) => ({
          kind: "topic_strip",
          sourceStart: row.startSec,
          sourceEnd: row.endSec,
          style: stripStyle,
          data: { topic_text: row.title },
        }));
      if (cues.length > 0) tracks.push(deriveOverlayTrack(cues, ctx.timeMap));
    }

    if (instance.modes.startCard) {
      const s = instance.style.startCard;
      const cardStyle = {
        title_color: s.titleColor,
        title_fontsize: s.titleFontsize,
        body_color: s.bodyColor,
        body_fontsize: s.bodyFontsize,
        bg_color: s.bgColor,
        bg_opacity: s.bgOpacity,
        accent_color: s.accentColor,
      };
      const cues: SourceAnchoredCue[] = instance.schedule
        .filter((row) => (row.title.trim() !== "" || row.refined.trim() !== "") && row.endSec > row.startSec)
        .map((row) => ({
          kind: "chapter_hero_card",
          sourceStart: row.startSec,
          sourceEnd: Math.min(row.endSec, row.startSec + s.durationSec),
          style: cardStyle,
          data: { title: row.title, body: row.refined },
        }));
      if (cues.length > 0) tracks.push(deriveOverlayTrack(cues, ctx.timeMap));
    }

    return tracks;
  },
};

// Mode gates for the nested style fields (read the snake-case wire dict).
const stripOn = (c: Record<string, unknown>): boolean =>
  !!(c["modes"] as Record<string, unknown> | undefined)?.["top_strip"];
const cardOn = (c: Record<string, unknown>): boolean =>
  !!(c["modes"] as Record<string, unknown> | undefined)?.["start_card"];

/**
 * Edit-UI fields. Chapter nests (modes / style.top_strip / style.start_card), so
 * style fields use `path` (the editor re-sends the whole top-level sub-object to
 * survive update_component's shallow merge) and `visibleWhen` to gate by mode.
 * Reuses the existing news_desk.chapter.* i18n keys. Fontsizes are absolute px
 * (legacy, scaled at render) → integer step. `schedule` is imported separately.
 */
export const chapterFields: readonly FieldSpec[] = [
  { key: "name", control: "text", labelKey: "news_desk.chapter.name" },
  { key: "modes.top_strip", path: ["modes", "top_strip"], control: "checkbox", labelKey: "news_desk.chapter.mode_top_strip", section: "news_desk.chapter.mode_section" },
  { key: "modes.start_card", path: ["modes", "start_card"], control: "checkbox", labelKey: "news_desk.chapter.mode_start_card" },
  // Top strip
  { key: "style.top_strip.bg_color", path: ["style", "top_strip", "bg_color"], control: "color", labelKey: "news_desk.chapter.bg_color", section: "news_desk.chapter.strip_style_section", visibleWhen: stripOn },
  { key: "style.top_strip.text_color", path: ["style", "top_strip", "text_color"], control: "color", labelKey: "news_desk.chapter.text_color", visibleWhen: stripOn },
  { key: "style.top_strip.fontsize", path: ["style", "top_strip", "fontsize"], control: "number", labelKey: "news_desk.chapter.fontsize", step: 1, min: 1, visibleWhen: stripOn },
  // Start card
  { key: "style.start_card.title_color", path: ["style", "start_card", "title_color"], control: "color", labelKey: "news_desk.chapter.title_color", section: "news_desk.chapter.card_style_section", visibleWhen: cardOn },
  { key: "style.start_card.title_fontsize", path: ["style", "start_card", "title_fontsize"], control: "number", labelKey: "news_desk.chapter.title_fontsize", step: 1, min: 1, visibleWhen: cardOn },
  { key: "style.start_card.body_color", path: ["style", "start_card", "body_color"], control: "color", labelKey: "news_desk.chapter.body_color", visibleWhen: cardOn },
  { key: "style.start_card.body_fontsize", path: ["style", "start_card", "body_fontsize"], control: "number", labelKey: "news_desk.chapter.body_fontsize", step: 1, min: 1, visibleWhen: cardOn },
  { key: "style.start_card.bg_color", path: ["style", "start_card", "bg_color"], control: "color", labelKey: "news_desk.chapter.card_bg_color", visibleWhen: cardOn },
  { key: "style.start_card.bg_opacity", path: ["style", "start_card", "bg_opacity"], control: "number", labelKey: "news_desk.chapter.bg_opacity", step: 1, min: 0, max: 100, visibleWhen: cardOn },
  { key: "style.start_card.accent_color", path: ["style", "start_card", "accent_color"], control: "color", labelKey: "news_desk.chapter.accent_color", visibleWhen: cardOn },
  { key: "style.start_card.duration_sec", path: ["style", "start_card", "duration_sec"], control: "number", labelKey: "news_desk.chapter.duration_sec", step: 1, min: 1, max: 30, visibleWhen: cardOn },
];
