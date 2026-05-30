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

/** Audio track metadata extracted by the demuxer (parallel to the video config). */
export interface AudioTrackMeta {
  id: number;
  /** Source sample rate (Hz). */
  sampleRate: number;
  /** Channel count (1 = mono, 2 = stereo). */
  numberOfChannels: number;
  /** WebCodecs codec string, e.g. "mp4a.40.2". */
  codec: string;
  nbSamples: number;
  durationUs: number;
}

/**
 * Fully decoded PCM for one media source — the currency between the decoder
 * (AudioReader) and both consumers (preview playback + export mix). Planar:
 * one Float32Array per channel, each of length `length`, samples in [-1, 1].
 */
export interface DecodedAudio {
  sampleRate: number;
  numberOfChannels: number;
  /** Samples per channel. */
  length: number;
  /** channelData[ch][frame] — planar float PCM. */
  channelData: Float32Array[];
}
