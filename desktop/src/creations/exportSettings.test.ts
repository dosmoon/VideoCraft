import { describe, expect, it } from "vitest";

import { resolveBitrate } from "../renderer/engine/export/types";
import {
  DEFAULT_EXPORT_SETTINGS,
  defaultEngine,
  downscaleToShortEdge,
  effectiveEngine,
  exportSettingsFromConfig,
  normalizeEngine,
  normalizeFps,
  normalizeMbps,
  normalizeResolution,
  presetToShortEdge,
} from "./exportSettings";

describe("exportSettings — normalizers", () => {
  it("engine: only chromium/ffmpeg pass; else auto", () => {
    expect(normalizeEngine("ffmpeg")).toBe("ffmpeg");
    expect(normalizeEngine("chromium")).toBe("chromium");
    expect(normalizeEngine("")).toBe("");
    expect(normalizeEngine("bogus")).toBe("");
    expect(normalizeEngine(undefined)).toBe("");
  });
  it("fps: int in [1,120], else 30", () => {
    expect(normalizeFps(60)).toBe(60);
    expect(normalizeFps("24")).toBe(24);
    expect(normalizeFps(0)).toBe(30);
    expect(normalizeFps(999)).toBe(30);
    expect(normalizeFps("x")).toBe(30);
  });
  it("mbps: positive, clamped [1,200], else 12", () => {
    expect(normalizeMbps(18)).toBe(18);
    expect(normalizeMbps(0)).toBe(12);
    expect(normalizeMbps(500)).toBe(200);
    expect(normalizeMbps("x")).toBe(12);
  });
  it("resolution: 'source' or 3-4 digit string, else 'source'", () => {
    expect(normalizeResolution("1080")).toBe("1080");
    expect(normalizeResolution("source")).toBe("source");
    expect(normalizeResolution("abc")).toBe("source");
    expect(normalizeResolution(undefined)).toBe("source");
  });
});

describe("exportSettings — engine resolution", () => {
  it("defaultEngine: always WebCodecs (ffmpeg transport-bound; opt-in only)", () => {
    expect(defaultEngine(null)).toBe("chromium");
    expect(defaultEngine({ ffmpeg: true, nvenc: true })).toBe("chromium");
  });
  it("effectiveEngine: explicit choice wins; ffmpeg falls back when absent; auto = WebCodecs", () => {
    const probe = { ffmpeg: true, nvenc: true };
    expect(effectiveEngine("chromium", probe)).toBe("chromium");
    expect(effectiveEngine("ffmpeg", probe)).toBe("ffmpeg");
    expect(effectiveEngine("ffmpeg", { ffmpeg: false, nvenc: false })).toBe("chromium");
    expect(effectiveEngine("", probe)).toBe("chromium"); // auto → WebCodecs
    expect(effectiveEngine("", null)).toBe("chromium");
  });
});

describe("exportSettings — resolution geometry", () => {
  it("downscaleToShortEdge: never upscale, preserve aspect, even dims", () => {
    // 1920x1080, cap short edge 720 → 1280x720
    expect(downscaleToShortEdge(1920, 1080, "720")).toEqual({ width: 1280, height: 720 });
    // source / non-numeric → source dims (even)
    expect(downscaleToShortEdge(1921, 1081, "source")).toEqual({ width: 1920, height: 1080 });
    // target >= short edge → no upscale
    expect(downscaleToShortEdge(1280, 720, "1080")).toEqual({ width: 1280, height: 720 });
    // portrait 1080x1920, cap 720 → 720x1280
    expect(downscaleToShortEdge(1080, 1920, "720")).toEqual({ width: 720, height: 1280 });
  });
  it("presetToShortEdge: numeric preset → px; non-numeric → fallback", () => {
    expect(presetToShortEdge("1080")).toBe(1080);
    expect(presetToShortEdge("720")).toBe(720);
    expect(presetToShortEdge("source")).toBe(1080);
    expect(presetToShortEdge("source", 720)).toBe(720);
  });
});

describe("resolveBitrate — auto matches the long-standing formula", () => {
  const auto = (w: number, h: number, fps: number) =>
    Math.min(24_000_000, Math.max(4_000_000, Math.round(w * h * fps * 0.12)));
  it("auto = clamp(w*h*fps*0.12, 4M, 24M)", () => {
    expect(resolveBitrate("auto", 0, 1920, 1080, 30)).toBe(auto(1920, 1080, 30)); // ~7.46M
    expect(resolveBitrate("auto", 0, 1280, 720, 30)).toBe(4_000_000); // clamped up
    expect(resolveBitrate("auto", 0, 3840, 2160, 60)).toBe(24_000_000); // clamped down
  });
  it("mbps mode uses the user value (bps); ignores 0", () => {
    expect(resolveBitrate("mbps", 12, 1920, 1080, 30)).toBe(12_000_000);
    expect(resolveBitrate("mbps", 0, 1920, 1080, 30)).toBe(auto(1920, 1080, 30));
  });
});

describe("exportSettingsFromConfig", () => {
  it("null config → defaults", () => {
    expect(exportSettingsFromConfig(null)).toEqual(DEFAULT_EXPORT_SETTINGS);
  });
  it("reads common fields, normalizing", () => {
    const s = exportSettingsFromConfig({
      export_engine: "ffmpeg",
      export_fps: 60,
      export_bitrate_mode: "mbps",
      export_bitrate_mbps: 20,
    });
    expect(s.engine).toBe("ffmpeg");
    expect(s.fps).toBe(60);
    expect(s.bitrateMode).toBe("mbps");
    expect(s.bitrateMbps).toBe(20);
  });
});
