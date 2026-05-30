/**
 * Audio resolver — the audio counterpart to resolveFrameAt. Where the frame
 * resolver answers "what is visible at instant t", this answers "what audio
 * plays over the whole timeline": each enabled audio track's clips, placed to
 * absolute output windows, with their source in-point and linear gain.
 *
 * Pure and decode-free (mirrors resolveFrameAt's discipline): it reuses
 * placeTrackChildren so audio and video share one placement logic. Both
 * consumers — preview playback (Web Audio scheduling) and export (PCM mix) —
 * walk these segments, so they cannot disagree about timing or gain.
 */

import { placeTrackChildren, type Timeline } from "../ir.js";

/** One source-audio span placed on the output timeline. */
export interface AudioSegment {
  /** Source media id/path to decode. */
  mediaRef: string;
  /** Absolute output window [outStartSec, outEndSec). */
  outStartSec: number;
  outEndSec: number;
  /** Source in-point sampled at outStartSec (advances 1:1 with output time). */
  sourceStartSec: number;
  /** Linear amplitude multiplier (already converted from gainDb). */
  gain: number;
}

/** Convert decibels to a linear amplitude multiplier (0 dB = ×1). */
export function dbToGain(db: number): number {
  return Math.pow(10, db / 20);
}

/**
 * Collect every audio clip across enabled audio tracks as a placed segment.
 * Gaps contribute silence (omitted). Generator/empty clips and clips without a
 * mediaRef are skipped. Segments are returned in (track, clip) order.
 */
export function resolveAudioSegments(timeline: Timeline): AudioSegment[] {
  const segments: AudioSegment[] = [];
  for (const track of timeline.tracks) {
    if (track.kind !== "audio" || !track.enabled) continue;
    for (const placed of placeTrackChildren(track.children)) {
      const child = placed.child;
      if (child.type !== "clip") continue;
      if (!child.mediaRef) continue;
      const gainDb = typeof child.style.gainDb === "number" ? child.style.gainDb : 0;
      segments.push({
        mediaRef: child.mediaRef,
        outStartSec: placed.startSec,
        outEndSec: placed.endSec,
        sourceStartSec: child.sourceStart ?? 0,
        gain: dbToGain(gainDb),
      });
    }
  }
  return segments;
}

/** True when the timeline has at least one enabled audio clip with a source. */
export function hasAudio(timeline: Timeline): boolean {
  return resolveAudioSegments(timeline).length > 0;
}
