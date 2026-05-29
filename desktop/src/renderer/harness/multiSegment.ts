/**
 * Spike A timeline — multi-segment concat on a single video track, slicing the
 * same source into windows whose sourceStart is deliberately NON-monotonic.
 * Each cut forces the ClipReader to seek (backward across a GOP), so the burned
 * frame number on screen vs. the resolver's expected source frame validates
 * frame-accurate seek across cut points.
 *
 * Output layout (each segment 2s):
 *   [0,2)  ← source [6.0, 8.0)   frames ~180–240
 *   [2,4)  ← source [0.5, 2.5)   frames ~15–75   (big backward jump = seek)
 *   [4,6)  ← source [3.0, 5.0)   frames ~90–150  (jump = seek)
 */

import { clip, computeTimelineDuration, type Timeline, type Track } from "@composition/ir.js";
import { DEMO_MEDIA_REF } from "./demoTimeline";

interface Seg {
  sourceStart: number;
  durationSec: number;
}

const SEGMENTS: Seg[] = [
  { sourceStart: 6.0, durationSec: 2.0 },
  { sourceStart: 0.5, durationSec: 2.0 },
  { sourceStart: 3.0, durationSec: 2.0 },
];

export function buildMultiSegmentTimeline(): Timeline {
  const videoTrack: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: SEGMENTS.map((s) =>
      clip({
        kind: "video",
        durationSec: s.durationSec,
        sourceStart: s.sourceStart,
        mediaRef: DEMO_MEDIA_REF,
        style: {},
        data: {},
      }),
    ),
  };
  return { tracks: [videoTrack], durationSec: computeTimelineDuration([videoTrack]) };
}
