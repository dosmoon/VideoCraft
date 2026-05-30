import { describe, it, expect } from "vitest";
import { clip, gap, type Timeline, type Track } from "../ir.js";
import { resolveAudioSegments, dbToGain, hasAudio } from "./resolveAudio.js";

function audioTrack(children: Track["children"]): Track {
  return { kind: "audio", z: 0, enabled: true, children };
}

function timeline(tracks: Track[], durationSec: number): Timeline {
  return { durationSec, tracks };
}

describe("dbToGain", () => {
  it("maps 0 dB to unity", () => {
    expect(dbToGain(0)).toBeCloseTo(1, 10);
  });
  it("maps +6 dB to ~2× and -6 dB to ~0.5×", () => {
    expect(dbToGain(6)).toBeCloseTo(1.995, 2);
    expect(dbToGain(-6)).toBeCloseTo(0.501, 2);
  });
});

describe("resolveAudioSegments", () => {
  it("places a single windowed audio clip", () => {
    const tl = timeline(
      [
        audioTrack([
          clip({ kind: "audio", durationSec: 5, sourceStart: 12, mediaRef: "src", style: { gainDb: 0 }, data: {} }),
        ]),
      ],
      5,
    );
    const segs = resolveAudioSegments(tl);
    expect(segs).toHaveLength(1);
    expect(segs[0]).toMatchObject({
      mediaRef: "src",
      outStartSec: 0,
      outEndSec: 5,
      sourceStartSec: 12,
    });
    expect(segs[0]!.gain).toBeCloseTo(1, 10);
  });

  it("places sequential clips contiguously and honours a leading gap", () => {
    const tl = timeline(
      [
        audioTrack([
          gap(2),
          clip({ kind: "audio", durationSec: 3, sourceStart: 0, mediaRef: "a", style: {}, data: {} }),
          clip({ kind: "audio", durationSec: 4, sourceStart: 10, mediaRef: "b", style: {}, data: {} }),
        ]),
      ],
      9,
    );
    const segs = resolveAudioSegments(tl);
    expect(segs.map((s) => [s.outStartSec, s.outEndSec])).toEqual([
      [2, 5],
      [5, 9],
    ]);
    expect(segs.map((s) => s.mediaRef)).toEqual(["a", "b"]);
  });

  it("applies per-clip gainDb", () => {
    const tl = timeline(
      [audioTrack([clip({ kind: "audio", durationSec: 1, sourceStart: 0, mediaRef: "s", style: { gainDb: 6 }, data: {} })])],
      1,
    );
    expect(resolveAudioSegments(tl)[0]!.gain).toBeCloseTo(dbToGain(6), 10);
  });

  it("skips disabled audio tracks and non-audio tracks", () => {
    const disabled: Track = {
      kind: "audio",
      z: 0,
      enabled: false,
      children: [clip({ kind: "audio", durationSec: 1, sourceStart: 0, mediaRef: "s", style: {}, data: {} })],
    };
    const video: Track = {
      kind: "video",
      z: 0,
      enabled: true,
      children: [clip({ kind: "video", durationSec: 1, sourceStart: 0, mediaRef: "v", style: {}, data: {} })],
    };
    expect(resolveAudioSegments(timeline([disabled, video], 1))).toHaveLength(0);
  });

  it("hasAudio reflects presence of resolvable audio segments", () => {
    const withAudio = timeline(
      [audioTrack([clip({ kind: "audio", durationSec: 1, sourceStart: 0, mediaRef: "s", style: {}, data: {} })])],
      1,
    );
    const videoOnly = timeline(
      [{ kind: "video", z: 0, enabled: true, children: [clip({ kind: "video", durationSec: 1, sourceStart: 0, mediaRef: "v", style: {}, data: {} })] }],
      1,
    );
    expect(hasAudio(withAudio)).toBe(true);
    expect(hasAudio(videoOnly)).toBe(false);
  });
});
