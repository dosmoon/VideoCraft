/**
 * Overlay assembly — pack absolute-time overlay segments into a relative
 * OTIO overlay Track (gaps + clips, strictly alternating).
 *
 * Bridges the gap between how components *think* (an overlay shows from t0 to
 * t1 in output time) and how OTIO *stores* (relative durations, no absolute
 * positions). A single track cannot hold overlapping clips — overlapping
 * overlays belong on separate tracks (different z). Components that need
 * simultaneous layers (e.g. chapter strip + hero card) emit multiple tracks.
 */

import { gap, type Clip, type Gap, type Track } from "./ir.js";

const EPS = 1e-6;

/** An overlay clip placed at an absolute output-time window [startSec, endSec). */
export interface OverlaySegment {
  startSec: number;
  endSec: number;
  clip: Clip;
}

/**
 * Pack non-overlapping segments into one overlay Track. Segments are sorted by
 * start; gaps fill the gaps; degenerate (zero/negative-length) segments are
 * dropped. Overlapping segments throw — that's a "use separate tracks" bug.
 */
export function packOverlaySegments(
  segments: readonly OverlaySegment[],
  opts: { z?: number; enabled?: boolean } = {},
): Track {
  const sorted = [...segments]
    .filter((s) => s.endSec - s.startSec > EPS)
    .sort((a, b) => a.startSec - b.startSec);

  const children: (Clip | Gap)[] = [];
  let cursor = 0;
  for (const seg of sorted) {
    if (seg.startSec < cursor - EPS) {
      throw new Error(
        `overlapping overlay segments on one track: [${seg.startSec}, ${seg.endSec}) ` +
          `starts before cursor ${cursor} — put overlapping overlays on separate tracks`,
      );
    }
    if (seg.startSec > cursor + EPS) {
      children.push(gap(seg.startSec - cursor));
    }
    children.push(seg.clip);
    cursor = seg.endSec;
  }

  return {
    kind: "overlay",
    z: opts.z ?? 0,
    enabled: opts.enabled ?? true,
    children,
  };
}
