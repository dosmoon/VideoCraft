/**
 * Shared video-component contract.
 *
 * Foundation doc §4.5: composition is the app's single visual engine, and a
 * video component is a thin, full-stack definition of exactly two things —
 * ① its edit UI (property panel; lands later, with the renderer) and
 * ② `compile() → OTIO`. This file owns ②: the pure compile contract.
 *
 * One library, not per-plugin copies. The existing Python plugins each grew
 * their own subtitle / watermark (creations/{news_desk,clip}/components/) with
 * divergent field names and unit conventions (int% vs float fraction). Porting
 * here deliberately *normalises* to one canonical schema per component
 * (float fractions, render-primitive-aligned keys) — pre-alpha, no legacy.
 *
 * What stays per-plugin (NOT here): which components a creation picks, the
 * "analysis-structure → component-config" mapping, presets, and the workbench.
 */

import type { Track } from "../ir.js";
import type { TimeMap } from "../timemap.js";

/** A source-anchored caption cue (the host parses the SRT into these). */
export interface SourceCue {
  /** Source-time window [sourceStart, sourceEnd). */
  sourceStart: number;
  sourceEnd: number;
  text: string;
}

/**
 * Everything a component may read at compile time. Pure data — no UI, no I/O.
 * Components ignore the fields they don't need.
 */
export interface CompileContext {
  /** Composition output duration (seconds). */
  durationSec: number;
  /**
   * Source↔output mapping. Use `identityTimeMap(durationSec)` when the creation
   * performs no cutting (e.g. news_desk over a full-length video).
   */
  timeMap: TimeMap;
  /** Source-anchored caption cues, when a component consumes them (subtitle). */
  cues?: readonly SourceCue[];
}

/**
 * A component type: a canonical default instance plus a pure compile to OTIO
 * overlay tracks.
 *
 * `compile` returns *zero or more* overlay tracks. Most components return one;
 * a component whose elements overlap in time (chapter: strip + hero card)
 * returns several, since a single relative-positioned track cannot hold
 * overlapping clips. Track `z` is a component-local sublayer (0-based); the
 * host re-stacks across all components by list order.
 */
export interface VideoComponent<I> {
  /** Canonical component kind (NOT a render-primitive kind). */
  readonly kind: string;
  defaultInstance(): I;
  compile(instance: I, ctx: CompileContext): Track[];
}
