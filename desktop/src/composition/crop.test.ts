import { describe, expect, it } from "vitest";
import { centerCropRect, clampCropRect, parseAspect, targetDimsForAspect } from "./crop.js";

describe("parseAspect", () => {
  it("parses w:h", () => {
    expect(parseAspect("9:16")).toEqual({ aw: 9, ah: 16 });
    expect(parseAspect("16:9")).toEqual({ aw: 16, ah: 9 });
  });
  it("falls back to 9:16 on garbage", () => {
    expect(parseAspect("")).toEqual({ aw: 9, ah: 16 });
    expect(parseAspect("0:0")).toEqual({ aw: 9, ah: 16 });
  });
});

describe("centerCropRect (≡ render.py::_center_crop_rect)", () => {
  it("9:16 out of a 16:9 source → full-height vertical strip, centered horizontally", () => {
    const r = centerCropRect(1920, 1080, 9, 16);
    // target_ar = 9/16 = 0.5625; cur_ar = 1.777 > target → crop width.
    const newW = 1080 * (9 / 16); // 607.5
    expect(r.h).toBe(1);
    expect(r.w).toBeCloseTo(newW / 1920, 6);
    expect(r.x).toBeCloseTo((1920 - newW) / 2 / 1920, 6);
    expect(r.y).toBe(0);
  });

  it("16:9 out of a 9:16 source → full-width horizontal strip, centered vertically", () => {
    const r = centerCropRect(1080, 1920, 16, 9);
    const newH = 1080 / (16 / 9);
    expect(r.w).toBe(1);
    expect(r.h).toBeCloseTo(newH / 1920, 6);
    expect(r.x).toBe(0);
    expect(r.y).toBeCloseTo((1920 - newH) / 2 / 1920, 6);
  });

  it("degenerate source → full frame", () => {
    expect(centerCropRect(0, 0, 9, 16)).toEqual({ x: 0, y: 0, w: 1, h: 1 });
  });
});

describe("targetDimsForAspect (≡ render.py::_target_dims_for_aspect — the export dims)", () => {
  it("9:16 @ 1080 short edge → 1080×1920", () => {
    expect(targetDimsForAspect("9:16", 1080)).toEqual({ width: 1080, height: 1920 });
  });
  it("16:9 @ 1080 short edge → 1920×1080", () => {
    expect(targetDimsForAspect("16:9", 1080)).toEqual({ width: 1920, height: 1080 });
  });
  it("1:1 @ 1080 → 1080×1080", () => {
    expect(targetDimsForAspect("1:1", 1080)).toEqual({ width: 1080, height: 1080 });
  });
  it("always returns even dimensions (encoder requirement)", () => {
    const { width, height } = targetDimsForAspect("4:5", 1081);
    expect(width % 2).toBe(0);
    expect(height % 2).toBe(0);
  });
});

describe("clampCropRect (≡ composition_preview.html::clampRect)", () => {
  it("re-derives height from width at the output aspect", () => {
    // 9:16 box of width 0.3 in a 1920x1080 source.
    const r = clampCropRect({ x: 0.1, y: 0, w: 0.3, h: 0.5 }, 1920, 1080, 9, 16);
    const expectedH = (0.3 * 1920) / (9 / 16) / 1080;
    expect(r.h).toBeCloseTo(expectedH, 6);
    expect(r.w).toBe(0.3);
  });

  it("clamps the anchor so the box stays inside the source", () => {
    const r = clampCropRect({ x: 0.95, y: 0.95, w: 0.3, h: 0.3 }, 1920, 1080, 9, 16);
    expect(r.x).toBeCloseTo(1 - r.w, 6);
    expect(r.y).toBeCloseTo(1 - r.h, 6);
  });

  it("shrinks width when the derived height would exceed the frame", () => {
    // A very wide box whose 9:16 height would blow past 1 → height capped, width refit.
    const r = clampCropRect({ x: 0, y: 0, w: 0.95, h: 1 }, 1080, 1920, 9, 16);
    expect(r.h).toBeLessThanOrEqual(1);
    expect(r.w).toBeLessThanOrEqual(0.95);
  });
});
