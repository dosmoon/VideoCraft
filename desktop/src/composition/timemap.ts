/**
 * TimeMap — a *derived* source↔output mapping, not a stored positioning system.
 *
 * Foundation doc §2.5: positioning is relative and lives on the tracks. The
 * TimeMap is computed *from* the video track's assembly and exists only to
 * project source-anchored content (SRT cues, analysis spans authored in source
 * time) onto the assembled output timeline — cutting and rippling them to match
 * how the video was assembled. Regions removed by the assembly map to `null`.
 *
 * This is what makes invariant #6 hold: applying the assembly's cut/ripple to
 * source-anchored content yields a legal OTIO overlay sequence (cue-clips and
 * gaps alternating).
 */

import { placeTrackChildren, clip, type Track } from "./ir.js";
import { packOverlaySegments, type OverlaySegment } from "./assemble.js";
import { isMediaKind } from "./catalog.js";

/** One kept slice of source media, placed on the output timeline. */
export interface TimeMapSegment {
  /** Output-time window [outStart, outEnd). */
  outStart: number;
  outEnd: number;
  /** Corresponding source-time window [sourceStart, sourceEnd). */
  sourceStart: number;
  sourceEnd: number;
  mediaRef: string | undefined;
}

export interface TimeMap {
  segments: TimeMapSegment[];
  /** Output time → source time (within the covering segment), or null if cut. */
  outToSource(outSec: number): number | null;
  /**
   * Source time → output time. When `mediaRef` is given, only segments from
   * that source match (disambiguates multiple sources). Returns null if the
   * source instant was cut out. First match wins.
   */
  sourceToOut(sourceSec: number, mediaRef?: string): number | null;
}

function makeTimeMap(segments: TimeMapSegment[]): TimeMap {
  const outToSource = (outSec: number): number | null => {
    for (const seg of segments) {
      if (outSec >= seg.outStart && outSec < seg.outEnd) {
        return seg.sourceStart + (outSec - seg.outStart);
      }
    }
    return null;
  };

  const sourceToOut = (sourceSec: number, mediaRef?: string): number | null => {
    for (const seg of segments) {
      if (mediaRef !== undefined && seg.mediaRef !== mediaRef) continue;
      if (sourceSec >= seg.sourceStart && sourceSec < seg.sourceEnd) {
        return seg.outStart + (sourceSec - seg.sourceStart);
      }
    }
    return null;
  };

  return { segments, outToSource, sourceToOut };
}

/**
 * Build a TimeMap from a video track. Each media clip becomes a segment in
 * output order; gaps and non-media clips advance output time without mapping to
 * any source (so they read back as `null`). No-speed-change v0: source and
 * output windows are equal length.
 */
export function buildTimeMap(videoTrack: Track): TimeMap {
  const segments: TimeMapSegment[] = [];
  for (const placed of placeTrackChildren(videoTrack.children)) {
    const child = placed.child;
    if (child.type !== "clip" || !isMediaKind(child.kind)) continue;
    const sourceStart = child.sourceStart ?? 0;
    segments.push({
      outStart: placed.startSec,
      outEnd: placed.endSec,
      sourceStart,
      sourceEnd: sourceStart + child.durationSec,
      mediaRef: child.mediaRef,
    });
  }
  return makeTimeMap(segments);
}

/**
 * Identity TimeMap: source time === output time over [0, durationSec). Used by
 * creations that perform no cutting (e.g. news_desk over a full-length video),
 * so source-anchored components ripple through a no-op and need no special case.
 */
export function identityTimeMap(durationSec: number, mediaRef?: string): TimeMap {
  return makeTimeMap([
    { outStart: 0, outEnd: durationSec, sourceStart: 0, sourceEnd: durationSec, mediaRef },
  ]);
}

/** A source-anchored overlay item (e.g. an SRT cue) before assembly is applied. */
export interface SourceAnchoredCue {
  kind: string;
  /** Source-time window the cue is anchored to. */
  sourceStart: number;
  sourceEnd: number;
  style?: Record<string, unknown>;
  data?: Record<string, unknown>;
  mediaRef?: string;
}

/**
 * Project source-anchored cues onto the assembled output timeline (invariant
 * #6). For every kept segment a cue overlaps, emit a cue-clip at the mapped
 * output window; cues in cut regions are dropped, and a cue straddling a cut is
 * split across the segments it survives in. The result is a legal overlay
 * Track: cue-clips and gaps strictly alternating, ordered, gap-filled from 0.
 */
export function deriveOverlayTrack(
  cues: readonly SourceAnchoredCue[],
  timemap: TimeMap,
  options: { z?: number; enabled?: boolean } = {},
): Track {
  const segments: OverlaySegment[] = [];

  for (const cue of cues) {
    for (const seg of timemap.segments) {
      if (cue.mediaRef !== undefined && seg.mediaRef !== cue.mediaRef) continue;
      // Intersect the cue's source window with this segment's source window.
      const lo = Math.max(cue.sourceStart, seg.sourceStart);
      const hi = Math.min(cue.sourceEnd, seg.sourceEnd);
      if (hi <= lo) continue;
      const outStart = seg.outStart + (lo - seg.sourceStart);
      const outEnd = seg.outStart + (hi - seg.sourceStart);
      segments.push({
        startSec: outStart,
        endSec: outEnd,
        clip: clip({
          kind: cue.kind,
          durationSec: outEnd - outStart,
          style: cue.style ?? {},
          data: cue.data ?? {},
        }),
      });
    }
  }

  return packOverlaySegments(segments, options);
}
