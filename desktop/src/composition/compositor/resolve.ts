/**
 * Frame resolver — the compositor's substrate-independent spine.
 *
 * Given a Timeline and an output time `t`, resolve what every track contributes
 * at that instant: which clip is active, its z (paint order), and — for media
 * clips — the source time to decode/seek. This is the *single* function both
 * preview and final render walk, which is what makes preview≡render structural
 * rather than two paths kept in sync (foundation doc §1, §4).
 *
 * Pure and GPU-free: the WebGPU/WebCodecs/libass-wasm layer consumes a
 * FrameSlice; it does not re-derive timing. Kept here so it stays unit-testable
 * before any substrate exists.
 */

import { placeTrackChildren, type Clip, type Timeline, type TrackKind } from "../ir.js";
import { isMediaKind } from "../catalog.js";

/** A clip active at the queried instant, resolved to absolute + source time. */
export interface ActiveClip {
  clip: Clip;
  /** Absolute output window of this clip. */
  startSec: number;
  endSec: number;
  /**
   * Source time to sample for a media clip (sourceStart + offset into the
   * clip). `null` for generator/overlay clips, which draw from style/data.
   */
  sourceTimeSec: number | null;
}

/** One track's contribution at the queried instant. */
export interface ResolvedTrack {
  kind: TrackKind;
  z: number;
  /**
   * Clips active at `t`. Usually 0 (gap) or 1; exactly 2 inside a transition's
   * overlap region (outgoing + incoming), in paint order (outgoing first).
   */
  clips: ActiveClip[];
}

/** Everything visible/audible at one output instant, in paint order. */
export interface FrameSlice {
  timeSec: number;
  /** Enabled tracks contributing at `t`, sorted by z ascending (background first). */
  tracks: ResolvedTrack[];
}

/** Half-open containment: a clip covers [start, end). */
function covers(startSec: number, endSec: number, t: number): boolean {
  return t >= startSec && t < endSec;
}

/**
 * Resolve the clips active on a single track's child list at output time `t`.
 * Returns them in track order, so during a transition the outgoing clip
 * (earlier in the list) precedes the incoming one.
 */
export function activeClipsAt(
  children: Parameters<typeof placeTrackChildren>[0],
  t: number,
): ActiveClip[] {
  const out: ActiveClip[] = [];
  for (const placed of placeTrackChildren(children)) {
    const child = placed.child;
    if (child.type !== "clip") continue;
    if (!covers(placed.startSec, placed.endSec, t)) continue;
    out.push({
      clip: child,
      startSec: placed.startSec,
      endSec: placed.endSec,
      sourceTimeSec: isMediaKind(child.kind)
        ? (child.sourceStart ?? 0) + (t - placed.startSec)
        : null,
    });
  }
  return out;
}

/**
 * Resolve a full frame at output time `t`. Disabled tracks are skipped; tracks
 * are returned sorted by z ascending so a consumer can paint background→front.
 * Tracks contributing nothing at `t` (in a gap) are omitted.
 */
export function resolveFrameAt(timeline: Timeline, t: number): FrameSlice {
  const tracks: ResolvedTrack[] = [];
  for (const track of timeline.tracks) {
    if (!track.enabled) continue;
    const clips = activeClipsAt(track.children, t);
    if (clips.length === 0) continue;
    tracks.push({ kind: track.kind, z: track.z, clips });
  }
  tracks.sort((a, b) => a.z - b.z);
  return { timeSec: t, tracks };
}
