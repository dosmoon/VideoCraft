import { describe, it, expect } from "vitest";
import { chapterSegments } from "./render.js";

describe("chapterSegments", () => {
  it("returns [] for a non-array schedule", () => {
    expect(chapterSegments(undefined)).toEqual([]);
    expect(chapterSegments(null)).toEqual([]);
    expect(chapterSegments({})).toEqual([]);
  });

  it("maps each chapter to a 1-indexed NN-title.mp4 stream-copy segment", () => {
    const segs = chapterSegments([
      { start_sec: 0, end_sec: 12.5, title: "Intro" },
      { start_sec: 12.5, end_sec: 30, title: "Main Story" },
    ]);
    expect(segs).toEqual([
      { name: "01-Intro.mp4", startSec: 0, durationSec: 12.5 },
      { name: "02-Main_Story.mp4", startSec: 12.5, durationSec: 17.5 },
    ]);
  });

  it("drops degenerate (<=0.1s) windows but keeps the schedule numbering", () => {
    const segs = chapterSegments([
      { start_sec: 0, end_sec: 0.05, title: "Blip" }, // dropped
      { start_sec: 2, end_sec: 11, title: "Real" }, // index 2 → "02-..."
    ]);
    expect(segs).toEqual([{ name: "02-Real.mp4", startSec: 2, durationSec: 9 }]);
  });

  it("sanitizes path-hostile titles and falls back to NN.mp4 when blank", () => {
    const segs = chapterSegments([
      { start_sec: 0, end_sec: 5, title: 'a/b:c*?"<>|d' },
      { start_sec: 5, end_sec: 10, title: "   " },
    ]);
    expect(segs[0]!.name).toBe("01-abcd.mp4");
    expect(segs[1]!.name).toBe("02.mp4");
  });
});
