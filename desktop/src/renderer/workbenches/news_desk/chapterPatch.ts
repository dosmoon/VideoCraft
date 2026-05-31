/**
 * Chapter component patch builders — pure nested-merge helpers.
 *
 * The chapter component's editable state is nested (modes / style.top_strip /
 * style.start_card), but creation.update_component SHALLOW-merges the patch into
 * the component dict. So editing one nested field must re-send the WHOLE nested
 * object, or the shallow merge drops its siblings. These builders read the
 * component's current nested value (with defaults) and return a complete patch.
 *
 * Mirrors creations/news_desk/component_defs.py::_chapter defaults + types.ts
 * NewsDeskChapterConfig.
 */

import type { Component } from "../../ipc/client";

export interface ChapterModes {
  top_strip: boolean;
  start_card: boolean;
}

export interface TopStripStyle {
  bg_color: string;
  text_color: string;
  fontsize: number;
}

export interface StartCardStyle {
  title_color: string;
  title_fontsize: number;
  body_color: string;
  body_fontsize: number;
  bg_color: string;
  bg_opacity: number;
  accent_color: string;
  duration_sec: number;
}

export const DEFAULT_MODES: ChapterModes = { top_strip: true, start_card: false };
export const DEFAULT_STRIP: TopStripStyle = {
  bg_color: "#1E40AF",
  text_color: "#FFFFFF",
  fontsize: 26,
};
export const DEFAULT_CARD: StartCardStyle = {
  title_color: "#FFFFFF",
  title_fontsize: 40,
  body_color: "#E5E7EB",
  body_fontsize: 22,
  bg_color: "#0F1B2C",
  bg_opacity: 55,
  accent_color: "#DC2626",
  duration_sec: 6,
};

/** Current modes with defaults filled in. */
export function readModes(c: Component): ChapterModes {
  const m = (c["modes"] ?? {}) as Partial<ChapterModes>;
  return { ...DEFAULT_MODES, ...m };
}

function readStyleObj(c: Component): {
  top_strip?: Partial<TopStripStyle>;
  start_card?: Partial<StartCardStyle>;
} {
  return (c["style"] ?? {}) as {
    top_strip?: Partial<TopStripStyle>;
    start_card?: Partial<StartCardStyle>;
  };
}

/** Current top-strip / start-card style with defaults filled in. */
export function readStrip(c: Component): TopStripStyle {
  return { ...DEFAULT_STRIP, ...readStyleObj(c).top_strip };
}
export function readCard(c: Component): StartCardStyle {
  return { ...DEFAULT_CARD, ...readStyleObj(c).start_card };
}

/** Patch toggling one mode, preserving the other. */
export function patchMode(c: Component, key: keyof ChapterModes, value: boolean): Record<string, unknown> {
  return { modes: { ...readModes(c), [key]: value } };
}

/** Patch one top-strip style field, preserving start_card (full style re-sent). */
export function patchStrip(c: Component, key: keyof TopStripStyle, value: unknown): Record<string, unknown> {
  const style = readStyleObj(c);
  return { style: { ...style, top_strip: { ...readStrip(c), [key]: value } } };
}

/** Patch one start-card style field, preserving top_strip (full style re-sent). */
export function patchCard(c: Component, key: keyof StartCardStyle, value: unknown): Record<string, unknown> {
  const style = readStyleObj(c);
  return { style: { ...style, start_card: { ...readCard(c), [key]: value } } };
}
