/** Integer microseconds — the engine's time unit (matches demuxer cts_us). */
export type TimeUs = number;

/**
 * A decoded-frame source for one media clip. ClipReader is the concrete impl;
 * the interface lets the compositor stay decoder-agnostic.
 *
 * `frameAt` returns a CLONE the caller must close() after use (or null when no
 * frame can be produced for that time).
 */
export interface VideoSource {
  readonly width: number;
  readonly height: number;
  readonly durationUs: TimeUs;
  frameAt(clipTimeUs: TimeUs): Promise<VideoFrame | null>;
  /** Export-mode: wait for and return the exact frame at the target time. */
  frameAtExact?(clipTimeUs: TimeUs): Promise<VideoFrame | null>;
  dispose(): void;
}
