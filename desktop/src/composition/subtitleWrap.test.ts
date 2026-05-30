import { describe, expect, it } from "vitest";
import { computeMaxChars, fitCues, hasCJK, splitCue } from "./subtitleWrap";
import type { SourceCue } from "./components/contract";

describe("computeMaxChars (≡ compute_subtitle_max_chars, resolution-independent)", () => {
  it("9:16 @ 0.05 CJK ≈ 10 (matches the legacy vertical max_chars_zh)", () => {
    expect(computeMaxChars(9 / 16, 0.05, true)).toBe(10);
  });
  it("9:16 @ 0.05 latin is wider (narrower glyphs)", () => {
    expect(computeMaxChars(9 / 16, 0.05, false)).toBe(18);
  });
  it("16:9 fits more chars than 9:16", () => {
    expect(computeMaxChars(16 / 9, 0.05, true)).toBeGreaterThan(
      computeMaxChars(9 / 16, 0.05, true),
    );
  });
  it("floors at 2 for absurdly large fonts", () => {
    expect(computeMaxChars(9 / 16, 0.9, true)).toBe(2);
  });
});

describe("hasCJK", () => {
  it("detects CJK vs latin", () => {
    expect(hasCJK("有的就业人数")).toBe(true);
    expect(hasCJK("hello world")).toBe(false);
  });
});

describe("splitCue (≡ split_subtitle: one line, time distributed by chars)", () => {
  it("keeps a short cue intact", () => {
    const c: SourceCue = { sourceStart: 0, sourceEnd: 2, text: "短句" };
    expect(splitCue(c, 10, true)).toEqual([{ sourceStart: 0, sourceEnd: 2, text: "短句" }]);
  });

  it("splits a long CJK cue into ≤maxChars pieces, preserving the window", () => {
    const c: SourceCue = { sourceStart: 10, sourceEnd: 14, text: "有的就业人数比以往任何政府都多得多" };
    const parts = splitCue(c, 10, true);
    expect(parts.length).toBeGreaterThan(1);
    for (const p of parts) expect(p.text.length).toBeLessThanOrEqual(10);
    expect(parts[0]!.sourceStart).toBe(10); // first starts at the cue start
    expect(parts[parts.length - 1]!.sourceEnd).toBe(14); // last snaps to the cue end
    // pieces are contiguous and monotonic
    for (let i = 1; i < parts.length; i++) {
      expect(parts[i]!.sourceStart).toBeCloseTo(parts[i - 1]!.sourceEnd, 6);
    }
  });

  it("breaks latin at spaces", () => {
    const c: SourceCue = { sourceStart: 0, sourceEnd: 4, text: "the quick brown fox jumps over" };
    const parts = splitCue(c, 12, false);
    expect(parts.length).toBeGreaterThan(1);
    // no piece ends mid-word (each trimmed piece is whole words)
    for (const p of parts) expect(p.text).toBe(p.text.trim());
  });
});

describe("fitCues (per-cue script auto-detect)", () => {
  it("fits a long cue and passes a short one through", () => {
    const cues: SourceCue[] = [
      { sourceStart: 0, sourceEnd: 4, text: "有的就业人数比以往任何政府都多得多" },
      { sourceStart: 4, sourceEnd: 5, text: "短" },
    ];
    const out = fitCues(cues, 0.05, 9 / 16);
    expect(out.length).toBeGreaterThan(2); // first split, second intact
    expect(out[out.length - 1]).toEqual({ sourceStart: 4, sourceEnd: 5, text: "短" });
  });
});
