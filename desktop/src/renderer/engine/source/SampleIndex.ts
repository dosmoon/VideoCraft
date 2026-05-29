import type { SampleMeta } from "./sample-types";

/**
 * Random-access view over a demuxer's sample list (ported from Phase).
 *
 * Samples are stored in decode order (dts ascending). Keyframe positions are
 * pre-computed so a seek can locate the nearest preceding keyframe in O(K).
 * Pure data — no WebCodecs/WebGPU dependency, fully unit-testable.
 */
export class SampleIndex {
  private readonly keyframes: number[];

  constructor(public readonly samples: ReadonlyArray<SampleMeta>) {
    const ks: number[] = [];
    for (let i = 0; i < samples.length; i++) {
      if (samples[i]!.is_sync) ks.push(i);
    }
    this.keyframes = ks;
  }

  get length(): number {
    return this.samples.length;
  }

  get keyframeCount(): number {
    return this.keyframes.length;
  }

  /**
   * Decode-order index of the keyframe whose presentation time (cts) is ≤
   * `targetUs`. Returns the first keyframe if the target falls before any
   * keyframe (or if there are none).
   */
  findKeyframeAtOrBefore(targetUs: number): number {
    let best = this.keyframes[0] ?? 0;
    for (const idx of this.keyframes) {
      const s = this.samples[idx]!;
      if (s.cts_us > targetUs) break;
      best = idx;
    }
    return best;
  }

  /** Decode-order index of the next keyframe strictly after `targetUs`, or -1. */
  findKeyframeAfter(targetUs: number): number {
    for (const idx of this.keyframes) {
      const s = this.samples[idx]!;
      if (s.cts_us > targetUs) return idx;
    }
    return -1;
  }
}
