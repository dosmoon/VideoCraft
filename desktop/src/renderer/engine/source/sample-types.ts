/**
 * Internal sample-level types for the source layer. Describe encoded chunks
 * coming out of the demuxer; never escape the source layer (ClipReader works
 * in VideoFrame terms). Ported from Phase (dosmoon-phase).
 */

/** One demuxed encoded sample. Times are integer microseconds. */
export interface SampleMeta {
  data: Uint8Array;
  /** Composition (presentation) time. */
  cts_us: number;
  /** Decode time. */
  dts_us: number;
  duration_us: number;
  is_sync: boolean;
}
