import { describe, it, expect } from "vitest";
import {
  clip,
  gap,
  transition,
  placeTrackChildren,
  computeTrackDuration,
  computeTimelineDuration,
  transitionOverlap,
  validateTimeline,
  assertValidTimeline,
  type Track,
  type Timeline,
} from "./ir.js";

// --- small builders -------------------------------------------------------

function videoClip(durationSec: number, sourceStart = 0, mediaRef = "src"): ReturnType<typeof clip> {
  return clip({ kind: "video", durationSec, sourceStart, mediaRef, style: {}, data: {} });
}
function subtitle(durationSec: number): ReturnType<typeof clip> {
  return clip({ kind: "subtitle_cue", durationSec, style: {}, data: { text: "hi" } });
}
function track(kind: Track["kind"], children: Track["children"], z = 0): Track {
  return { kind, z, enabled: true, children };
}
function timeline(tracks: Track[]): Timeline {
  return { durationSec: computeTimelineDuration(tracks), tracks };
}

// --- invariant #1: relative positioning (absolute pos = cumulative duration)

describe("invariant #1 — relative positioning", () => {
  it("clip/gap absolute positions are cumulative, not stored", () => {
    const placed = placeTrackChildren([videoClip(10), gap(2), videoClip(5)]);
    expect(placed.map((p) => [p.startSec, p.endSec])).toEqual([
      [0, 10],
      [10, 12],
      [12, 17],
    ]);
  });

  it("an empty track places nothing", () => {
    expect(placeTrackChildren([])).toEqual([]);
  });
});

// --- invariant #4 + transition overlap ------------------------------------

describe("invariant #4 — duration = Σ clip/gap − Σ transition overlap", () => {
  it("track duration sums clips and gaps", () => {
    expect(computeTrackDuration(track("video", [videoClip(10), gap(2), videoClip(5)]))).toBe(17);
  });

  it("a transition subtracts its in+out overlap and pulls neighbours together", () => {
    const t = transition("crossfade", 1, 1); // overlap 2
    expect(transitionOverlap(t)).toBe(2);
    const trk = track("video", [videoClip(10), t, videoClip(10)]);
    // 10 + 10 − 2 = 18
    expect(computeTrackDuration(trk)).toBe(18);

    const placed = placeTrackChildren(trk.children);
    // clip A: [0,10]; transition overlap region [8,10]; clip B pulled to start at 8
    expect([placed[0]!.startSec, placed[0]!.endSec]).toEqual([0, 10]);
    expect([placed[1]!.startSec, placed[1]!.endSec]).toEqual([8, 10]);
    expect([placed[2]!.startSec, placed[2]!.endSec]).toEqual([8, 18]);
  });

  it("timeline duration is the max over enabled tracks", () => {
    const tl = timeline([
      track("video", [videoClip(20)]),
      track("overlay", [subtitle(5)]),
    ]);
    expect(tl.durationSec).toBe(20);
  });

  it("disabled tracks do not extend the timeline", () => {
    const longDisabled: Track = { kind: "overlay", z: 1, enabled: false, children: [subtitle(99)] };
    expect(computeTimelineDuration([track("video", [videoClip(20)]), longDisabled])).toBe(20);
  });

  it("validateTimeline flags a stale stored durationSec", () => {
    const tl: Timeline = { durationSec: 999, tracks: [track("video", [videoClip(20)])] };
    const issues = validateTimeline(tl);
    expect(issues).toHaveLength(1);
    expect(issues[0]!.invariant).toBe(4);
  });
});

// --- invariant #2: media source-window bounds -----------------------------

describe("invariant #2 — media clip source window", () => {
  it("accepts a window inside the source", () => {
    const tl = timeline([track("video", [videoClip(10, 5, "src")])]);
    expect(validateTimeline(tl, { sourceDurations: { src: 30 } })).toEqual([]);
  });

  it("rejects a negative sourceStart", () => {
    const tl = timeline([track("video", [clip({ kind: "video", durationSec: 5, sourceStart: -1, mediaRef: "src", style: {}, data: {} })])]);
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 2 && /sourceStart/.test(i.message))).toBe(true);
  });

  it("rejects a window past the source duration", () => {
    const tl = timeline([track("video", [videoClip(10, 25, "src")])]); // 25+10=35 > 30
    const issues = validateTimeline(tl, { sourceDurations: { src: 30 } });
    expect(issues.some((i) => i.invariant === 2 && /exceeds source duration/.test(i.message))).toBe(true);
  });

  it("skips the upper bound when the source duration is unknown", () => {
    const tl = timeline([track("video", [videoClip(10, 25, "mystery")])]);
    expect(validateTimeline(tl)).toEqual([]);
  });
});

// --- invariant #3: transitions only between two clips ---------------------

describe("invariant #3 — transition placement", () => {
  it("rejects a transition not flanked by two clips", () => {
    const tl = timeline([track("video", [videoClip(10), transition("x", 1, 1), gap(5)])]);
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 3 && /between two clips/.test(i.message))).toBe(true);
  });

  it("rejects a leading transition", () => {
    const trk = track("video", [transition("x", 1, 1), videoClip(10)]);
    const tl: Timeline = { durationSec: computeTrackDuration(trk), tracks: [trk] };
    expect(validateTimeline(tl).some((i) => i.invariant === 3)).toBe(true);
  });

  it("rejects an offset larger than its neighbour clip", () => {
    const tl = timeline([track("video", [videoClip(3), transition("x", 5, 1), videoClip(10)])]);
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 3 && /inOffsetSec/.test(i.message))).toBe(true);
  });

  it("accepts a well-formed transition", () => {
    const tl = timeline([track("video", [videoClip(10), transition("crossfade", 1, 1), videoClip(10)])]);
    expect(validateTimeline(tl)).toEqual([]);
  });
});

// --- invariant #5: kind catalogs ------------------------------------------

describe("invariant #5 — kind membership", () => {
  it("rejects an unknown clip kind", () => {
    const tl = timeline([track("overlay", [clip({ kind: "wibble", durationSec: 2, style: {}, data: {} })])]);
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 5 && /not in the catalog/.test(i.message))).toBe(true);
  });

  it("rejects an unknown track kind", () => {
    const bad = { kind: "sticker" as Track["kind"], z: 0, enabled: true, children: [] };
    const tl: Timeline = { durationSec: 0, tracks: [bad] };
    expect(validateTimeline(tl).some((i) => i.invariant === 5 && /track kind/.test(i.message))).toBe(true);
  });

  it("accepts catalog kinds (ported Python primitive vocabulary)", () => {
    const tl = timeline([
      track("video", [videoClip(10)]),
      track("overlay", [subtitle(4), gap(1), clip({ kind: "chapter_hero_card", durationSec: 3, style: {}, data: {} })]),
    ]);
    expect(validateTimeline(tl)).toEqual([]);
  });
});

// --- invariant #7: media clip crop rect -----------------------------------

describe("invariant #7 — media clip crop rect", () => {
  function videoCrop(crop: { x: number; y: number; w: number; h: number }): ReturnType<typeof clip> {
    return clip({ kind: "video", durationSec: 10, sourceStart: 0, mediaRef: "src", crop, style: {}, data: {} });
  }

  it("accepts an absent crop (whole source)", () => {
    const tl = timeline([track("video", [videoClip(10)])]);
    expect(validateTimeline(tl)).toEqual([]);
  });

  it("accepts a valid normalized sub-rectangle", () => {
    const tl = timeline([track("video", [videoCrop({ x: 0.1, y: 0, w: 0.8, h: 1 })])]);
    expect(validateTimeline(tl)).toEqual([]);
  });

  it("rejects a non-positive size", () => {
    const tl = timeline([track("video", [videoCrop({ x: 0, y: 0, w: 0, h: 1 })])]);
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 7 && /positive size/.test(i.message))).toBe(true);
  });

  it("rejects a rect that spills past the source bounds", () => {
    const tl = timeline([track("video", [videoCrop({ x: 0.5, y: 0, w: 0.8, h: 1 })])]); // x+w = 1.3 > 1
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 7 && /outside the source bounds/.test(i.message))).toBe(true);
  });

  it("rejects a non-finite component", () => {
    const tl = timeline([track("video", [videoCrop({ x: 0, y: 0, w: NaN, h: 1 })])]);
    const issues = validateTimeline(tl);
    expect(issues.some((i) => i.invariant === 7 && /non-finite/.test(i.message))).toBe(true);
  });
});

// --- assert wrapper -------------------------------------------------------

describe("assertValidTimeline", () => {
  it("throws with a readable digest on invalid input", () => {
    const tl: Timeline = { durationSec: 5, tracks: [track("video", [videoClip(10)])] };
    expect(() => assertValidTimeline(tl)).toThrowError(/Invalid timeline/);
  });

  it("does not throw on a valid timeline", () => {
    const tl = timeline([track("video", [videoClip(10)])]);
    expect(() => assertValidTimeline(tl)).not.toThrow();
  });
});
