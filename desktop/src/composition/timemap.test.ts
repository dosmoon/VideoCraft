import { describe, it, expect } from "vitest";
import { clip, gap, type Track } from "./ir.js";
import { buildTimeMap, deriveOverlayTrack, type SourceAnchoredCue } from "./timemap.js";

function videoClip(durationSec: number, sourceStart: number, mediaRef = "src") {
  return clip({ kind: "video", durationSec, sourceStart, mediaRef, style: {}, data: {} });
}

// A two-segment assembly that drops source [10, 30):
//   segment 0: source [0,10)  -> output [0,10)
//   segment 1: source [30,40) -> output [10,20)
function assembled(): Track {
  return {
    kind: "video",
    z: 0,
    enabled: true,
    children: [videoClip(10, 0), videoClip(10, 30)],
  };
}

describe("buildTimeMap", () => {
  it("derives output-ordered segments from the video assembly", () => {
    const tm = buildTimeMap(assembled());
    expect(tm.segments).toEqual([
      { outStart: 0, outEnd: 10, sourceStart: 0, sourceEnd: 10, mediaRef: "src" },
      { outStart: 10, outEnd: 20, sourceStart: 30, sourceEnd: 40, mediaRef: "src" },
    ]);
  });

  it("outToSource maps within a segment and respects the ripple", () => {
    const tm = buildTimeMap(assembled());
    expect(tm.outToSource(5)).toBe(5); // segment 0
    expect(tm.outToSource(12)).toBe(32); // segment 1: 30 + (12-10)
  });

  it("sourceToOut inverts the mapping and returns null for cut source time", () => {
    const tm = buildTimeMap(assembled());
    expect(tm.sourceToOut(5)).toBe(5);
    expect(tm.sourceToOut(32)).toBe(12);
    expect(tm.sourceToOut(20)).toBeNull(); // 20 is in the dropped [10,30) region
  });

  it("gaps map to null (no source under a gap)", () => {
    const trk: Track = { kind: "video", z: 0, enabled: true, children: [videoClip(10, 0), gap(5), videoClip(5, 50)] };
    const tm = buildTimeMap(trk);
    expect(tm.outToSource(12)).toBeNull(); // inside the gap [10,15)
    expect(tm.outToSource(17)).toBe(52); // segment after the gap: 50 + (17-15)
  });

  it("disambiguates by mediaRef when multiple sources are present", () => {
    const trk: Track = {
      kind: "video",
      z: 0,
      enabled: true,
      children: [videoClip(10, 0, "a"), videoClip(10, 0, "b")],
    };
    const tm = buildTimeMap(trk);
    expect(tm.sourceToOut(5, "a")).toBe(5);
    expect(tm.sourceToOut(5, "b")).toBe(15);
  });
});

// --- invariant #6: source-anchored content -> legal OTIO overlay sequence --

describe("invariant #6 — deriveOverlayTrack", () => {
  it("ripples source-anchored cues onto the assembled timeline, alternating gap/clip", () => {
    const tm = buildTimeMap(assembled());
    const cues: SourceAnchoredCue[] = [
      { kind: "subtitle_cue", sourceStart: 2, sourceEnd: 4, data: { text: "a" } }, // kept -> out [2,4)
      { kind: "subtitle_cue", sourceStart: 15, sourceEnd: 18, data: { text: "b" } }, // fully in cut region -> dropped
      { kind: "subtitle_cue", sourceStart: 32, sourceEnd: 35, data: { text: "c" } }, // kept -> out [12,15)
    ];
    const overlay = deriveOverlayTrack(cues, tm);
    expect(overlay.kind).toBe("overlay");

    // Expect: gap[0,2), cue[2,4), gap[4,12), cue[12,15)
    const kinds = overlay.children.map((c) => c.type);
    expect(kinds).toEqual(["gap", "clip", "gap", "clip"]);

    const c1 = overlay.children[1]!;
    const c3 = overlay.children[3]!;
    expect(c1.type === "clip" && c1.durationSec).toBe(2); // [2,4)
    expect(c3.type === "clip" && c3.durationSec).toBe(3); // [12,15)
    expect((overlay.children[0] as { durationSec: number }).durationSec).toBe(2);
    expect((overlay.children[2] as { durationSec: number }).durationSec).toBe(8); // [4,12)
  });

  it("splits a cue that straddles a cut into the surviving segments", () => {
    const tm = buildTimeMap(assembled());
    // Cue source [8,32) straddles the dropped region [10,30):
    //   survives as [8,10) -> out [8,10)  and  [30,32) -> out [10,12)
    const overlay = deriveOverlayTrack([{ kind: "subtitle_cue", sourceStart: 8, sourceEnd: 32 }], tm);
    const clips = overlay.children.filter((c) => c.type === "clip");
    expect(clips).toHaveLength(2);
  });

  it("a cue entirely in a cut region produces an empty overlay", () => {
    const tm = buildTimeMap(assembled());
    const overlay = deriveOverlayTrack([{ kind: "subtitle_cue", sourceStart: 12, sourceEnd: 20 }], tm);
    expect(overlay.children).toEqual([]);
  });

  it("a leading-aligned cue produces no opening gap", () => {
    const tm = buildTimeMap(assembled());
    const overlay = deriveOverlayTrack([{ kind: "subtitle_cue", sourceStart: 0, sourceEnd: 3 }], tm);
    expect(overlay.children[0]!.type).toBe("clip");
  });
});
