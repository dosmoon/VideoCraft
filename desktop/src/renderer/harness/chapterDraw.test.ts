/**
 * Headless guard for the chapter draw path. Verifies — without a GPU — that the
 * canvas2D layer recognises the chapter overlay kinds (topic_strip /
 * chapter_hero_card) and draws them. This catches the exact regression the user
 * hit: chapters compiled into the timeline but were invisible because
 * canvas2d.ts didn't list the kinds, so drawFrameSlice skipped them.
 */

import type { Clip } from "@composition/ir.js";
import { isCanvas2dOverlay, drawOverlayClip } from "../engine/overlay/canvas2d";

/** Minimal 2D-context stub recording which draw calls fire. */
function stubCtx() {
  const calls: string[] = [];
  const ctx = {
    font: "",
    textAlign: "" as CanvasTextAlign,
    textBaseline: "" as CanvasTextBaseline,
    fillStyle: "" as string,
    strokeStyle: "" as string,
    lineWidth: 0,
    lineJoin: "" as CanvasLineJoin,
    measureText: (t: string) => ({ width: t.length * 10 }) as TextMetrics,
    fillRect: () => calls.push("fillRect"),
    strokeText: () => calls.push("strokeText"),
    fillText: () => calls.push("fillText"),
  };
  return { ctx: ctx as unknown as OffscreenCanvasRenderingContext2D, calls };
}

function stripClip(): Clip {
  return {
    type: "clip",
    kind: "topic_strip",
    durationSec: 30,
    style: { bgColor: "#1E40AF", textColor: "#FFFFFF", fontsizePct: 26 / 1080 },
    data: { text: "第一章" },
  } as Clip;
}

function cardClip(): Clip {
  return {
    type: "clip",
    kind: "chapter_hero_card",
    durationSec: 6,
    style: {
      titleColor: "#FFFFFF",
      titleFontsizePct: 40 / 1080,
      bodyColor: "#E5E7EB",
      bodyFontsizePct: 22 / 1080,
      bgColor: "#0F1B2C",
      bgOpacity: 55,
      accentColor: "#DC2626",
    },
    data: { text: "第一章", refined: "本章讲述供水设施遇袭。", keyPoints: ["三枚导弹", "落在市场"] },
  } as Clip;
}

describe("chapter canvas2D path", () => {
  it("recognises the chapter overlay kinds", () => {
    expect(isCanvas2dOverlay("topic_strip")).toBe(true);
    expect(isCanvas2dOverlay("chapter_hero_card")).toBe(true);
  });

  it("draws the topic strip (band fill + title text)", () => {
    const { ctx, calls } = stubCtx();
    expect(drawOverlayClip(ctx, stripClip(), 1280, 720)).toBe(true);
    expect(calls).toContain("fillRect"); // the band
    expect(calls).toContain("fillText"); // the title
  });

  it("draws the hero card (panel + title + body + bullets)", () => {
    const { ctx, calls } = stubCtx();
    expect(drawOverlayClip(ctx, cardClip(), 1280, 720)).toBe(true);
    expect(calls).toContain("fillRect"); // panel + accent rule
    // title + refined + 2 bullets → several text draws.
    expect(calls.filter((c) => c === "fillText").length).toBeGreaterThanOrEqual(4);
  });

  it("skips an empty hero card", () => {
    const { ctx } = stubCtx();
    const empty = { type: "clip", kind: "chapter_hero_card", durationSec: 6, style: {}, data: {} } as Clip;
    expect(drawOverlayClip(ctx, empty, 1280, 720)).toBe(false);
  });
});
