import { describe, it, expect } from "vitest";
import { mixAudio } from "./audioMix.js";
import type { DecodedAudio } from "../source/sample-types";
import type { AudioSegment } from "@composition/compositor/resolveAudio.js";

function src(sampleRate: number, channels: number[][]): DecodedAudio {
  return {
    sampleRate,
    numberOfChannels: channels.length,
    length: channels[0]!.length,
    channelData: channels.map((c) => Float32Array.from(c)),
  };
}

function seg(over: Partial<AudioSegment> = {}): AudioSegment {
  return { mediaRef: "s", outStartSec: 0, outEndSec: 1, sourceStartSec: 0, gain: 1, ...over };
}

describe("mixAudio", () => {
  it("copies a unity-gain segment 1:1 when rates match", () => {
    const sources = new Map([["s", src(4, [[0, 0.25, 0.5, 0.75]])]]);
    const out = mixAudio([seg()], sources, { sampleRate: 4, numberOfChannels: 1, durationSec: 1 });
    expect(out.length).toBe(4);
    expect(Array.from(out.channelData[0]!)).toEqual([0, 0.25, 0.5, 0.75]);
  });

  it("applies segment gain", () => {
    const sources = new Map([["s", src(4, [[1, 1, 1, 1]])]]);
    const out = mixAudio([seg({ gain: 0.5 })], sources, { sampleRate: 4, numberOfChannels: 1, durationSec: 1 });
    expect(Array.from(out.channelData[0]!)).toEqual([0.5, 0.5, 0.5, 0.5]);
  });

  it("replicates a mono source across stereo output", () => {
    const sources = new Map([["s", src(4, [[0.1, 0.2, 0.3, 0.4]])]]);
    const out = mixAudio([seg()], sources, { sampleRate: 4, numberOfChannels: 2, durationSec: 1 });
    expect(out.numberOfChannels).toBe(2);
    expect(Array.from(out.channelData[0]!)).toEqual([0.1, 0.2, 0.3, 0.4].map((v) => Math.fround(v)));
    expect(Array.from(out.channelData[1]!)).toEqual(Array.from(out.channelData[0]!));
  });

  it("honours sourceStartSec offset", () => {
    // PCM in [-1, 1] (multiples of 1/8 are exact in float32).
    const sources = new Map([["s", src(4, [[0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]])]]);
    // Start 0.5s into the source (= frame 2 at rate 4), 1s window.
    const out = mixAudio([seg({ sourceStartSec: 0.5 })], sources, {
      sampleRate: 4,
      numberOfChannels: 1,
      durationSec: 1,
    });
    expect(Array.from(out.channelData[0]!)).toEqual([0.25, 0.375, 0.5, 0.625]);
  });

  it("places a segment at its output offset, leaving earlier frames silent", () => {
    const sources = new Map([["s", src(4, [[0.5, 0.5, 0.5, 0.5]])]]);
    const out = mixAudio([seg({ outStartSec: 0.5, outEndSec: 1.5 })], sources, {
      sampleRate: 4,
      numberOfChannels: 1,
      durationSec: 2,
    });
    // total 8 frames; segment fills frames [2,6).
    expect(Array.from(out.channelData[0]!)).toEqual([0, 0, 0.5, 0.5, 0.5, 0.5, 0, 0]);
  });

  it("sums overlapping segments and clamps to [-1, 1]", () => {
    const sources = new Map([["s", src(4, [[0.8, 0.8, 0.8, 0.8]])]]);
    const out = mixAudio([seg(), seg()], sources, { sampleRate: 4, numberOfChannels: 1, durationSec: 1 });
    // 0.8 + 0.8 = 1.6 → clamped to 1.
    expect(Array.from(out.channelData[0]!)).toEqual([1, 1, 1, 1]);
  });

  it("linearly resamples when source rate exceeds output rate", () => {
    // Source at 8 Hz, output at 4 Hz → output frame i samples source at 2i.
    const sources = new Map([["s", src(8, [[0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]])]]);
    const out = mixAudio([seg()], sources, { sampleRate: 4, numberOfChannels: 1, durationSec: 1 });
    expect(Array.from(out.channelData[0]!)).toEqual([0, 0.25, 0.5, 0.75]);
  });

  it("soft-clamps out-of-range sums to [-1, 1]", () => {
    const sources = new Map([["s", src(4, [[2, -2, 0.5, -0.5]])]]);
    const out = mixAudio([seg()], sources, { sampleRate: 4, numberOfChannels: 1, durationSec: 1 });
    expect(Array.from(out.channelData[0]!)).toEqual([1, -1, 0.5, -0.5]);
  });
});
