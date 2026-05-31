/**
 * Headless guard for the chapter draw path. Verifies — without a GPU — that the
 * canvas2D layer recognises the chapter overlay kinds (topic_strip /
 * chapter_hero_card) and draws them with the CORRECT data keys. This catches the
 * exact regression the user hit: chapters compiled into the timeline but were
 * invisible because drawOverlayClip read clip.data["text"], while the chapter
 * component emits data.topic_text (strip) and data.title/data.body (card), so
 * the draw bailed on empty text.
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
    globalAlpha: 1,
    measureText: (t: string) => ({ width: t.length * 10 }) as TextMetrics,
    fillRect: () => calls.push("fillRect"),
    strokeText: () => calls.push("strokeText"),
    fillText: () => calls.push("fillText"),
    drawImage: () => calls.push("drawImage"),
  };
  return { ctx: ctx as unknown as OffscreenCanvasRenderingContext2D, calls };
}

// Mirrors what creations/news_desk chapter.ts emits: topic_text for the strip,
// title+body for the card, snake_case style with absolute px fontsizes.
function stripClip(): Clip {
  return {
    type: "clip",
    kind: "topic_strip",
    durationSec: 30,
    style: { bg_color: "#1E40AF", text_color: "#FFFFFF", fontsize: 26 },
    data: { topic_text: "第一章" },
  } as Clip;
}

function cardClip(): Clip {
  return {
    type: "clip",
    kind: "chapter_hero_card",
    durationSec: 6,
    style: {
      title_color: "#FFFFFF",
      title_fontsize: 40,
      body_color: "#E5E7EB",
      body_fontsize: 22,
      bg_color: "#0F1B2C",
      bg_opacity: 55,
      accent_color: "#DC2626",
    },
    data: { title: "第一章", body: "本章讲述供水设施遇袭。" },
  } as Clip;
}

describe("chapter canvas2D path", () => {
  it("recognises the chapter overlay kinds", () => {
    expect(isCanvas2dOverlay("topic_strip")).toBe(true);
    expect(isCanvas2dOverlay("chapter_hero_card")).toBe(true);
  });

  it("draws the topic strip (band fill + title text) from data.topic_text", () => {
    const { ctx, calls } = stubCtx();
    expect(drawOverlayClip(ctx, stripClip(), 1280, 720)).toBe(true);
    expect(calls).toContain("fillRect"); // the band
    expect(calls).toContain("fillText"); // the title
  });

  it("draws the hero card (panel + accent + title + body) from data.title/body", () => {
    const { ctx, calls } = stubCtx();
    expect(drawOverlayClip(ctx, cardClip(), 1280, 720)).toBe(true);
    // panel + accent stripe → ≥2 fillRect; title + body → ≥2 fillText.
    expect(calls.filter((c) => c === "fillRect").length).toBeGreaterThanOrEqual(2);
    expect(calls.filter((c) => c === "fillText").length).toBeGreaterThanOrEqual(2);
  });

  it("skips an empty strip / card", () => {
    const { ctx } = stubCtx();
    const emptyStrip = { type: "clip", kind: "topic_strip", durationSec: 30, style: {}, data: {} } as Clip;
    const emptyCard = { type: "clip", kind: "chapter_hero_card", durationSec: 6, style: {}, data: {} } as Clip;
    expect(drawOverlayClip(ctx, emptyStrip, 1280, 720)).toBe(false);
    expect(drawOverlayClip(ctx, emptyCard, 1280, 720)).toBe(false);
  });
});
