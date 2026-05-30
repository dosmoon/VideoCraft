/**
 * Audio mixer — flatten resolved AudioSegments + decoded source PCM into one
 * planar PCM buffer on the output timeline. Pure number-crunching (no WebCodecs/
 * Web Audio), so it is fully unit-testable; both export (→ AudioEncoder) and, if
 * needed, an offline preview render consume the same result.
 *
 * Per output frame: for each segment covering it, sample the source PCM (linear
 * resampling when the source rate differs from the output), apply the segment's
 * gain, and sum across segments. Channels are mapped by index, with mono sources
 * replicated to every output channel. The final sum is soft-clamped to [-1, 1].
 */

import type { DecodedAudio } from "../source/sample-types";
import type { AudioSegment } from "@composition/compositor/resolveAudio.js";

export interface MixOptions {
  sampleRate: number;
  numberOfChannels: number;
  /** Output timeline length; mix buffer = round(durationSec * sampleRate). */
  durationSec: number;
}

export interface MixedAudio {
  sampleRate: number;
  numberOfChannels: number;
  length: number;
  channelData: Float32Array[];
}

/** Sample one source plane at a fractional frame position with linear interp. */
function sampleAt(plane: Float32Array, pos: number): number {
  const i0 = Math.floor(pos);
  if (i0 < 0 || i0 >= plane.length) return 0;
  const frac = pos - i0;
  if (frac === 0) return plane[i0]!;
  const i1 = i0 + 1 < plane.length ? i0 + 1 : i0;
  return plane[i0]! * (1 - frac) + plane[i1]! * frac;
}

/** Mix segments into planar Float32 PCM: channelData[ch][frame], length frames. */
export function mixAudio(
  segments: readonly AudioSegment[],
  sources: ReadonlyMap<string, DecodedAudio>,
  opts: MixOptions,
): MixedAudio {
  const { sampleRate, numberOfChannels } = opts;
  const total = Math.max(0, Math.round(opts.durationSec * sampleRate));
  const channelData: Float32Array[] = [];
  for (let ch = 0; ch < numberOfChannels; ch++) channelData.push(new Float32Array(total));

  for (const seg of segments) {
    const src = sources.get(seg.mediaRef);
    if (!src || src.length === 0) continue;

    const outStart = Math.max(0, Math.round(seg.outStartSec * sampleRate));
    const outEnd = Math.min(total, Math.round(seg.outEndSec * sampleRate));

    for (let i = outStart; i < outEnd; i++) {
      // Output frame i → seconds into the segment → source frame position.
      const segSec = (i - outStart) / sampleRate;
      const srcPos = (seg.sourceStartSec + segSec) * src.sampleRate;
      if (srcPos < 0 || srcPos >= src.length) continue;

      for (let ch = 0; ch < numberOfChannels; ch++) {
        const plane = src.channelData[ch] ?? src.channelData[src.numberOfChannels - 1];
        if (!plane) continue;
        const dst = channelData[ch]!;
        dst[i] = (dst[i] ?? 0) + sampleAt(plane, srcPos) * seg.gain;
      }
    }
  }

  // Soft clamp to valid PCM range.
  for (const plane of channelData) {
    for (let i = 0; i < plane.length; i++) {
      const v = plane[i]!;
      if (v > 1) plane[i] = 1;
      else if (v < -1) plane[i] = -1;
    }
  }

  return { sampleRate, numberOfChannels, length: total, channelData };
}
