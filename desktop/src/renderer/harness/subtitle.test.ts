/**
 * Headless guard for the subtitle path (Spike B). Verifies — without a GPU —
 * that a subtitle_cue is recognised by the canvas2D dispatch, that the subtitle
 * timeline resolves a cue clip with text at a cue time, and that drawOverlayClip
 * accepts it. Catches the duplicate-file / stale-bundle class of bug that made
 * `isCanvas2dOverlay("subtitle_cue")` read false at runtime.
 */

import { resolveFrameAt } from "@composition/compositor/resolve.js";
import type { Clip } from "@composition/ir.js";
import { isCanvas2dOverlay, drawOverlayClip } from "../engine/overlay/canvas2d";
import { buildSubtitleTimeline } from "./demoTimeline";

/** Minimal 2D-context stub recording that the draw calls fire. */
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

describe("subtitle canvas2D path", () => {
  it("recognises subtitle_cue and the card kinds", () => {
    expect(isCanvas2dOverlay("subtitle_cue")).toBe(true);
    expect(isCanvas2dOverlay("hook_text")).toBe(true);
    expect(isCanvas2dOverlay("video")).toBe(false);
  });

  it("resolves a subtitle_cue clip with text at a cue time", () => {
    const tl = buildSubtitleTimeline(10);
    const slice = resolveFrameAt(tl, 1.5); // inside the first sample cue [0.5,3.0)
    const overlay = slice.tracks.find((t) => t.kind === "overlay");
    expect(overlay).toBeDefined();
    const cue = overlay!.clips[0]!.clip;
    expect(cue.kind).toBe("subtitle_cue");
    expect(typeof cue.data["text"]).toBe("string");
    expect((cue.data["text"] as string).length).toBeGreaterThan(0);
  });

  it("drawOverlayClip draws the cue (box + stroke + fill)", () => {
    const tl = buildSubtitleTimeline(10);
    const cue = resolveFrameAt(tl, 1.5).tracks.find((t) => t.kind === "overlay")!.clips[0]!
      .clip as Clip;
    const { ctx, calls } = stubCtx();
    expect(drawOverlayClip(ctx, cue, 1280, 720)).toBe(true);
    expect(calls).toContain("fillText");
  });
});
