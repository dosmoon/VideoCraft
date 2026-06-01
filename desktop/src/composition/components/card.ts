/**
 * Hook / outro card components — a single text card pinned to the start (hook)
 * or end (outro) of the composition.
 *
 * Ports creations/clip/components/hook_outro.py. Both share the same field set
 * and card-style contract; they differ only in their time window and the
 * role-specific style keys the primitive expects (hook_* vs outro_*). The
 * legacy code stamped both roles' keys onto every card; here each card emits
 * only its own role's keys.
 */

import { clip, type Clip, type Track } from "../ir.js";
import { packOverlaySegments } from "../assemble.js";
import type { CompileContext, VideoComponent } from "./contract.js";
import type { FieldSpec } from "./fieldSpec.js";

export type CardPosition = "upper-third" | "center" | "lower-third";

export interface CardInstance {
  enabled: boolean;
  text: string;
  font: string;
  sizePct: number; // fraction of target_h
  color: string;
  bgColor: string;
  bgOpacity: number; // 0..100
  strokeColor: string;
  strokePct: number; // fraction of target_h
  boxPaddingPct: number; // fraction of target_h
  position: CardPosition;
  durationSec: number;
}

function defaultCard(position: CardPosition): CardInstance {
  return {
    enabled: true,
    text: "",
    font: "Microsoft YaHei",
    sizePct: 0.05,
    color: "#FFFFFF",
    bgColor: "#000000",
    bgOpacity: 70,
    strokeColor: "#000000",
    strokePct: 0.003,
    boxPaddingPct: 0.012,
    position,
    durationSec: 5,
  };
}

function cardClip(
  instance: CardInstance,
  primitiveKind: "hook_text" | "outro_text",
  roleStyle: Record<string, unknown>,
  durationSec: number,
): Clip {
  return clip({
    kind: primitiveKind,
    durationSec,
    style: {
      font: instance.font,
      size_pct: instance.sizePct,
      color: instance.color,
      bg_color: instance.bgColor,
      bg_opacity: instance.bgOpacity,
      stroke_color: instance.strokeColor,
      stroke_pct: instance.strokePct,
      box_padding_pct: instance.boxPaddingPct,
      ...roleStyle,
    },
    data: { text: instance.text },
  });
}

export const hookCard: VideoComponent<CardInstance> = {
  kind: "hook_card",

  defaultInstance: () => defaultCard("upper-third"),

  compile(instance: CardInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || instance.text.trim() === "" || instance.durationSec <= 0) return [];
    const end = Math.min(ctx.durationSec, instance.durationSec);
    if (end <= 0) return [];
    const c = cardClip(
      instance,
      "hook_text",
      { hook_position: instance.position, hook_duration_sec: instance.durationSec },
      end,
    );
    return [packOverlaySegments([{ startSec: 0, endSec: end, clip: c }])];
  },
};

export const outroCard: VideoComponent<CardInstance> = {
  kind: "outro_card",

  defaultInstance: () => defaultCard("lower-third"),

  compile(instance: CardInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || instance.text.trim() === "" || instance.durationSec <= 0) return [];
    const start = Math.max(0, ctx.durationSec - instance.durationSec);
    if (ctx.durationSec - start <= 0) return [];
    const c = cardClip(
      instance,
      "outro_text",
      { outro_position: instance.position, outro_duration_sec: instance.durationSec },
      ctx.durationSec - start,
    );
    return [packOverlaySegments([{ startSec: start, endSec: ctx.durationSec, clip: c }])];
  },
};

/**
 * Edit-UI fields (wire snake keys). Shared by hook_card + outro_card. `text` is
 * NOT here — hook/outro text comes from the candidate, not the component (the
 * Tk panel had no text field either).
 */
export const cardFields: readonly FieldSpec[] = [
  { key: "name", control: "text", labelKey: "card.name" },
  { key: "duration_sec", control: "number", labelKey: "card.duration", step: 1, min: 1, max: 30 },
  { key: "font", control: "text", labelKey: "card.font" },
  { key: "size_pct", control: "number", labelKey: "card.fontsize", step: 0.005, min: 0, max: 0.5 },
  { key: "color", control: "color", labelKey: "card.color" },
  { key: "stroke_color", control: "color", labelKey: "card.stroke_color" },
  { key: "stroke_pct", control: "number", labelKey: "card.stroke_width", step: 0.001, min: 0, max: 0.02 },
  { key: "bg_color", control: "color", labelKey: "card.bg_color" },
  { key: "bg_opacity", control: "number", labelKey: "card.bg_opacity", step: 1, min: 0, max: 100 },
  { key: "box_padding_pct", control: "number", labelKey: "card.box_padding", step: 0.005, min: 0, max: 0.2 },
  {
    key: "position",
    control: "select",
    labelKey: "card.position",
    options: ["upper-third", "center", "lower-third"],
    optionLabelKeys: {
      "upper-third": "card.position.upper_third",
      center: "card.position.center",
      "lower-third": "card.position.lower_third",
    },
  },
];
