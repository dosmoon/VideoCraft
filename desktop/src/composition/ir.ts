/**
 * OTIO-style composition IR — the engine's single source of "what to draw".
 *
 * This is the TypeScript rebuild of the composition core (foundation doc
 * §2.5). It replaces the transient, overlay-only Python IR in
 * src/core/composition/timeline.py with a *persistent, full multi-track* model:
 * N video + N audio + N overlay tracks, all uniform Tracks (anti-CapCut — no
 * bespoke track types). See docs/design/composition-otio-foundation.md.
 *
 * Two orthogonal axes (kept deliberately separate):
 *   1. Structural type   — clip | gap | transition  (A2: three OTIO structural
 *      kinds, not one unified Item). Lives on the `type` discriminant.
 *   2. Render primitive   — `Clip.kind` (video, subtitle_cue, chapter_card, …).
 *      Dispatched by the compositor; membership pinned to the catalog.
 *
 * NOTE on the `type` discriminant: the schema sketch in §2.5 omits it, but a
 * runtime tag is what makes "three structural types" actually discriminable in
 * TS (and lets invariants like "Transition only between two Clips" be checked).
 * It is the structural axis made explicit; it does not collapse the three types
 * into a union Item.
 *
 * RELATIVE POSITIONING (A1): items store only a duration. Absolute position is
 * the cumulative duration of preceding items — *derived, never stored*. This
 * holds uniformly across video / audio / overlay tracks.
 */

import { isKnownClipKind, isMediaKind } from "./catalog.js";

export type TrackKind = "video" | "audio" | "overlay";

/**
 * Normalized source rectangle (each component in [0,1], relative to the source
 * frame) describing a clip's spatial reframe — the window of source pixels that
 * maps onto the output frame. The same shape the GPU crop pipeline + the
 * composition/crop geometry already speak.
 */
export interface CropRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A drawable item: source media (video/audio) or a generator (subtitle, card, …). */
export interface Clip {
  readonly type: "clip";
  /** Render primitive; must be in the clip-kind catalog (invariant #5). */
  kind: string;
  durationSec: number;
  /** Media clips only: start of the source time window (window length = durationSec). */
  sourceStart?: number;
  /** Media clips only: source id / path. */
  mediaRef?: string;
  /**
   * Media clips only: spatial reframe — the normalized source rectangle that
   * maps onto the output frame. Absent = whole source (no crop). This is a
   * per-clip *transform* (where the media sits, sibling of sourceStart/mediaRef),
   * NOT a "how to draw" style hint: the compositor reads it per clip and the GPU
   * samples only this window (reframe = cover). Geometry helpers live in
   * composition/crop. Invariant #7 bounds it.
   */
  crop?: CropRect;
  /** Visual fields — "how to draw" (inlined at compile time, no late lookup). */
  style: Record<string, unknown>;
  /** Kind-specific content — "what to draw". */
  data: Record<string, unknown>;
}

/** Empty span on a track. Carries duration only. */
export interface Gap {
  readonly type: "gap";
  durationSec: number;
}

/**
 * Effect between two neighbouring Clips. Has no standalone duration: its
 * in/out offsets reach into the neighbours and *overlap* them, shortening the
 * track total (invariant #4). Render primitive lives on `kind` (e.g. "crossfade").
 */
export interface Transition {
  readonly type: "transition";
  kind: string;
  /** Seconds the transition reaches back into the preceding clip. */
  inOffsetSec: number;
  /** Seconds the transition reaches forward into the following clip. */
  outOffsetSec: number;
}

export type TrackChild = Clip | Gap | Transition;

export interface Track {
  kind: TrackKind;
  /** Stacking order; higher z composites on top. */
  z: number;
  enabled: boolean;
  /** Ordered; absolute positions derived from order + duration (never stored). */
  children: TrackChild[];
}

export interface Timeline {
  /**
   * Full composition duration. Denormalised for convenience but must equal
   * `computeTimelineDuration(tracks)` (invariant #4) — validated, not trusted.
   */
  durationSec: number;
  tracks: Track[];
}

// ---------------------------------------------------------------------------
// Constructors (small ergonomic helpers; all fields stay plain data)
// ---------------------------------------------------------------------------

export function clip(init: Omit<Clip, "type">): Clip {
  return { type: "clip", ...init };
}

export function gap(durationSec: number): Gap {
  return { type: "gap", durationSec };
}

export function transition(
  kind: string,
  inOffsetSec: number,
  outOffsetSec: number,
): Transition {
  return { type: "transition", kind, inOffsetSec, outOffsetSec };
}

// ---------------------------------------------------------------------------
// Placement & duration derivation (invariants #1 and #4)
// ---------------------------------------------------------------------------

/** A child resolved to its absolute output-time window. */
export interface PlacedChild {
  child: TrackChild;
  index: number;
  startSec: number;
  endSec: number;
}

/** The overlap a transition removes from the track total: in + out offsets. */
export function transitionOverlap(t: Transition): number {
  return t.inOffsetSec + t.outOffsetSec;
}

/**
 * Resolve every child to an absolute [startSec, endSec) window (invariant #1).
 *
 * Clips/Gaps advance a cursor by their duration. A Transition carries no
 * duration of its own; instead it pulls everything after it earlier by its
 * overlap, so the following clip overlaps the preceding one (the NLE crossfade
 * model). The transition's own window is that overlap region.
 */
export function placeTrackChildren(children: readonly TrackChild[]): PlacedChild[] {
  const placed: PlacedChild[] = [];
  let cursor = 0;
  for (let index = 0; index < children.length; index++) {
    const child = children[index]!;
    if (child.type === "transition") {
      const overlap = transitionOverlap(child);
      // The cut sits at the current cursor (preceding clip's end). The overlap
      // region ends there; the following clip is pulled back to its start.
      const startSec = cursor - overlap;
      placed.push({ child, index, startSec, endSec: cursor });
      cursor = startSec;
      continue;
    }
    placed.push({ child, index, startSec: cursor, endSec: cursor + child.durationSec });
    cursor += child.durationSec;
  }
  return placed;
}

/** Track length = Σ clip/gap durations − Σ transition overlaps (invariant #4 term). */
export function computeTrackDuration(track: Track): number {
  let total = 0;
  for (const child of track.children) {
    if (child.type === "transition") {
      total -= transitionOverlap(child);
    } else {
      total += child.durationSec;
    }
  }
  return total;
}

/**
 * Composition length = max track length over *enabled* tracks (invariant #4).
 * Disabled tracks contribute nothing — they are dropped at compile time
 * (carried over from the Python Track contract).
 */
export function computeTimelineDuration(tracks: readonly Track[]): number {
  let max = 0;
  for (const track of tracks) {
    if (!track.enabled) continue;
    const d = computeTrackDuration(track);
    if (d > max) max = d;
  }
  return max;
}

// ---------------------------------------------------------------------------
// Validation — the invariants as runtime checks (the contract, pinned)
// ---------------------------------------------------------------------------

export interface ValidationIssue {
  /** Dotted path to the offending node, e.g. "tracks[1].children[3]". */
  path: string;
  /**
   * Which invariant was violated. 1–6 per foundation doc §2.5; #7 = media clip
   * crop rect must be a valid sub-rectangle of the source in normalized coords.
   */
  invariant: number;
  message: string;
}

/** Floating-point tolerance for the durationSec consistency check. */
const DURATION_EPSILON = 1e-6;

export interface ValidateOptions {
  /**
   * Source media durations keyed by `mediaRef`. When a media clip's ref is
   * present here, invariant #2's upper bound (`sourceStart + duration ≤ source`)
   * is enforced; otherwise only the lower bound (`sourceStart ≥ 0`) is checked.
   */
  sourceDurations?: Readonly<Record<string, number>>;
}

/**
 * Collect every invariant violation in a timeline. Returns an empty array for a
 * legal timeline. Pure — never throws on bad data (that's the point: tests and
 * UI both want the full issue list, not a single throw).
 */
export function validateTimeline(
  timeline: Timeline,
  options: ValidateOptions = {},
): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const sourceDurations = options.sourceDurations ?? {};

  timeline.tracks.forEach((track, ti) => {
    const tp = `tracks[${ti}]`;

    // #5: Track.kind ∈ {video, audio, overlay}
    if (track.kind !== "video" && track.kind !== "audio" && track.kind !== "overlay") {
      issues.push({
        path: tp,
        invariant: 5,
        message: `unknown track kind "${track.kind}"`,
      });
    }

    track.children.forEach((child, ci) => {
      const cp = `${tp}.children[${ci}]`;

      if (child.type === "clip") {
        // #5: Clip.kind ∈ catalog
        if (!isKnownClipKind(child.kind)) {
          issues.push({
            path: cp,
            invariant: 5,
            message: `clip kind "${child.kind}" is not in the catalog`,
          });
        }
        if (child.durationSec < 0) {
          issues.push({ path: cp, invariant: 1, message: `negative durationSec ${child.durationSec}` });
        }
        // #2: media clip source-window bounds (v0: no speed change)
        if (isMediaKind(child.kind)) {
          const start = child.sourceStart ?? 0;
          if (start < 0) {
            issues.push({ path: cp, invariant: 2, message: `sourceStart ${start} < 0` });
          }
          if (child.mediaRef !== undefined && child.mediaRef in sourceDurations) {
            const srcDur = sourceDurations[child.mediaRef]!;
            if (start + child.durationSec > srcDur + DURATION_EPSILON) {
              issues.push({
                path: cp,
                invariant: 2,
                message: `source window [${start}, ${start + child.durationSec}] exceeds source duration ${srcDur}`,
              });
            }
          }
          // #7: spatial crop rect (when present) must be a positive-size
          // sub-rectangle of the source frame in normalized [0,1] coords.
          if (child.crop !== undefined) {
            const { x, y, w, h } = child.crop;
            if (![x, y, w, h].every((n) => Number.isFinite(n))) {
              issues.push({ path: cp, invariant: 7, message: `crop has a non-finite component` });
            } else if (w <= 0 || h <= 0) {
              issues.push({ path: cp, invariant: 7, message: `crop must have positive size, got w=${w} h=${h}` });
            } else if (
              x < -DURATION_EPSILON ||
              y < -DURATION_EPSILON ||
              x + w > 1 + DURATION_EPSILON ||
              y + h > 1 + DURATION_EPSILON
            ) {
              issues.push({
                path: cp,
                invariant: 7,
                message: `crop rect [${x}, ${y}, ${w}, ${h}] is outside the source bounds [0,1]`,
              });
            }
          }
        }
      } else if (child.type === "gap") {
        if (child.durationSec < 0) {
          issues.push({ path: cp, invariant: 1, message: `negative gap durationSec ${child.durationSec}` });
        }
      } else {
        // Transition — #3: only between two Clips; offsets ≤ neighbour durations
        const prev = track.children[ci - 1];
        const next = track.children[ci + 1];
        if (prev?.type !== "clip" || next?.type !== "clip") {
          issues.push({
            path: cp,
            invariant: 3,
            message: "transition must sit between two clips",
          });
        } else {
          if (child.inOffsetSec < 0 || child.outOffsetSec < 0) {
            issues.push({ path: cp, invariant: 3, message: "transition offsets must be ≥ 0" });
          }
          if (child.inOffsetSec > prev.durationSec + DURATION_EPSILON) {
            issues.push({
              path: cp,
              invariant: 3,
              message: `inOffsetSec ${child.inOffsetSec} exceeds preceding clip duration ${prev.durationSec}`,
            });
          }
          if (child.outOffsetSec > next.durationSec + DURATION_EPSILON) {
            issues.push({
              path: cp,
              invariant: 3,
              message: `outOffsetSec ${child.outOffsetSec} exceeds following clip duration ${next.durationSec}`,
            });
          }
        }
      }
    });
  });

  // #4: stored durationSec must equal the derived value
  const derived = computeTimelineDuration(timeline.tracks);
  if (Math.abs(timeline.durationSec - derived) > DURATION_EPSILON) {
    issues.push({
      path: "durationSec",
      invariant: 4,
      message: `stored durationSec ${timeline.durationSec} ≠ derived ${derived}`,
    });
  }

  return issues;
}

/** Throwing wrapper for call sites that treat an invalid timeline as a bug. */
export function assertValidTimeline(timeline: Timeline, options?: ValidateOptions): void {
  const issues = validateTimeline(timeline, options);
  if (issues.length > 0) {
    const detail = issues.map((i) => `  [#${i.invariant}] ${i.path}: ${i.message}`).join("\n");
    throw new Error(`Invalid timeline (${issues.length} issue(s)):\n${detail}`);
  }
}
