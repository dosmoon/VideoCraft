import { describe, it, expect } from "vitest";
import { clip, gap, transition, type Timeline, type Track } from "../ir.js";
import { activeClipsAt, resolveFrameAt } from "./resolve.js";

function videoClip(durationSec: number, sourceStart = 0, mediaRef = "src") {
  return clip({ kind: "video", durationSec, sourceStart, mediaRef, style: {}, data: {} });
}
function sub(durationSec: number, text = "x") {
  return clip({ kind: "subtitle_cue", durationSec, style: {}, data: { text } });
}
function track(kind: Track["kind"], children: Track["children"], z = 0, enabled = true): Track {
  return { kind, z, enabled, children };
}

describe("activeClipsAt", () => {
  it("returns the single clip covering t (half-open [start,end))", () => {
    const children = [videoClip(10), gap(2), videoClip(5)];
    expect(activeClipsAt(children, 5).map((a) => a.startSec)).toEqual([0]);
    expect(activeClipsAt(children, 12).map((a) => a.startSec)).toEqual([12]);
    expect(activeClipsAt(children, 10)).toEqual([]); // in the gap
  });

  it("computes media source time as sourceStart + offset into the clip", () => {
    const a = activeClipsAt([videoClip(10, 30)], 4)[0]!;
    expect(a.sourceTimeSec).toBe(34);
  });

  it("leaves generator clips with null source time", () => {
    expect(activeClipsAt([sub(5)], 2)[0]!.sourceTimeSec).toBeNull();
  });

  it("returns both clips inside a transition overlap (outgoing first)", () => {
    // A[0,10], crossfade(1,1) overlap 2 -> B pulled to start at 8; at t=9 both active.
    const children = [videoClip(10, 0, "a"), transition("crossfade", 1, 1), videoClip(10, 0, "b")];
    const at9 = activeClipsAt(children, 9);
    expect(at9).toHaveLength(2);
    expect(at9.map((a) => a.clip.mediaRef)).toEqual(["a", "b"]);
    // outside the overlap only one is active
    expect(activeClipsAt(children, 4)).toHaveLength(1);
    expect(activeClipsAt(children, 15)).toHaveLength(1);
  });
});

describe("resolveFrameAt", () => {
  function scene(): Timeline {
    const video = track("video", [videoClip(60, 100)], 0);
    const subs = track("overlay", [gap(5), sub(3, "hi")], 10);
    const wm = track("overlay", [videoClip(60)], 5); // full-duration overlay-ish
    return { durationSec: 60, tracks: [video, subs, wm] };
  }

  it("returns contributing tracks sorted by z ascending (paint order)", () => {
    const frame = resolveFrameAt(scene(), 6); // subtitle active in [5,8)
    expect(frame.tracks.map((t) => t.z)).toEqual([0, 5, 10]);
    expect(frame.timeSec).toBe(6);
  });

  it("omits tracks that are in a gap at t", () => {
    const frame = resolveFrameAt(scene(), 2); // subtitle still in its leading gap
    expect(frame.tracks.map((t) => t.z)).toEqual([0, 5]); // no overlay-subtitle track
  });

  it("skips disabled tracks", () => {
    const video = track("video", [videoClip(60, 100)], 0);
    const disabled = track("overlay", [sub(60)], 10, false);
    const frame = resolveFrameAt({ durationSec: 60, tracks: [video, disabled] }, 3);
    expect(frame.tracks).toHaveLength(1);
    expect(frame.tracks[0]!.kind).toBe("video");
  });

  it("surfaces the media source time on the video track", () => {
    const frame = resolveFrameAt(scene(), 6);
    const videoLayer = frame.tracks.find((t) => t.kind === "video")!;
    expect(videoLayer.clips[0]!.sourceTimeSec).toBe(106); // sourceStart 100 + 6
  });
});
