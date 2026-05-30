/**
 * Spike C — WebCodecs export. Walk the timeline's output frames, prepare each
 * via the SAME prepareFrame/paintPreparedFrame the preview uses (so preview≡
 * render is structural), render to an OFFSCREEN target and read the pixels back
 * (the swapchain can't be read — WebGPU doesn't preserve the drawing buffer),
 * wrap them in a VideoFrame, encode with VideoEncoder, mux to mp4. Bytes go to
 * the main process to write (renderer can't touch the filesystem).
 *
 * Note (Spike A carry-over): frame sampling uses the playback ClipReader, which
 * returns the nearest decoded frame at-or-before each output time (±a few
 * frames). Bit-exact export wants a decode-to-exact-frame path — documented
 * refinement, not blocking the encode/mux/write de-risk here.
 */

import { ArrayBufferTarget, Muxer } from "mp4-muxer";
import { resolveFrameAt } from "@composition/compositor/resolve.js";
import { resolveAudioSegments, type AudioSegment } from "@composition/compositor/resolveAudio.js";
import type { Timeline } from "@composition/ir.js";
import type { Backend } from "../gpu/Backend";
import type { DecodedAudio } from "../source/sample-types";
import { mixAudio } from "./audioMix";
import {
  disposePrepared,
  paintPreparedFrame,
  prepareFrame,
  type DrawDeps,
} from "../compositor/draw";

/** Fixed export audio rate; sources are linearly resampled to it in the mix. */
const AUDIO_SAMPLE_RATE = 48_000;
const AUDIO_BITRATE = 192_000;

/** Thrown when cancelCheck() trips mid-encode so the caller can discard the clip. */
export class ExportCancelled extends Error {
  constructor() {
    super("export cancelled");
    this.name = "ExportCancelled";
  }
}

export interface ExportOptions {
  timeline: Timeline;
  drawDeps: DrawDeps;
  backend: Backend;
  width: number;
  height: number;
  fps: number;
  durationSec: number;
  /** Reframe offset crop ({x,y,w,h} normalized source coords); omit for passthrough/full. */
  cropRect?: { x: number; y: number; w: number; h: number };
  onProgress?: (done: number, total: number) => void;
  /** Polled each frame; returning true aborts with ExportCancelled. */
  cancelCheck?: () => boolean;
  /**
   * Decoded source audio keyed by mediaRef. When present (and the timeline has
   * audio clips referencing them), an AAC audio track is mixed + muxed in.
   */
  audioSources?: ReadonlyMap<string, DecodedAudio>;
}

interface AudioOut {
  sampleRate: number;
  numberOfChannels: number;
}

/** Decide the output audio shape, or null when there's nothing to mux. */
function planAudio(
  segments: readonly AudioSegment[],
  sources: ReadonlyMap<string, DecodedAudio> | undefined,
): AudioOut | null {
  if (!sources || segments.length === 0) return null;
  let channels = 0;
  let present = false;
  for (const seg of segments) {
    const s = sources.get(seg.mediaRef);
    if (s && s.length > 0) {
      present = true;
      channels = Math.max(channels, s.numberOfChannels);
    }
  }
  if (!present) return null;
  return { sampleRate: AUDIO_SAMPLE_RATE, numberOfChannels: Math.min(2, Math.max(1, channels)) };
}

/** Mix + AAC-encode the audio track into the muxer (after the video pass). */
async function encodeAudioTrack(
  muxer: Muxer<ArrayBufferTarget>,
  segments: readonly AudioSegment[],
  sources: ReadonlyMap<string, DecodedAudio>,
  out: AudioOut,
  durationSec: number,
): Promise<void> {
  const mixed = mixAudio(segments, sources, {
    sampleRate: out.sampleRate,
    numberOfChannels: out.numberOfChannels,
    durationSec,
  });
  if (mixed.length === 0) return;

  let encodeError: Error | null = null;
  const encoder = new AudioEncoder({
    output: (chunk, meta) => muxer.addAudioChunk(chunk, meta),
    error: (e) => {
      encodeError = e instanceof Error ? e : new Error(String(e));
    },
  });
  encoder.configure({
    codec: "mp4a.40.2", // AAC-LC
    sampleRate: out.sampleRate,
    numberOfChannels: out.numberOfChannels,
    bitrate: AUDIO_BITRATE,
  });

  // Feed ~0.5s planar chunks; the encoder re-frames to AAC's 1024-sample blocks.
  const chunkFrames = Math.round(out.sampleRate / 2);
  for (let offset = 0; offset < mixed.length; offset += chunkFrames) {
    if (encodeError) throw encodeError;
    const n = Math.min(chunkFrames, mixed.length - offset);
    const planar = new Float32Array(n * out.numberOfChannels);
    for (let ch = 0; ch < out.numberOfChannels; ch++) {
      planar.set(mixed.channelData[ch]!.subarray(offset, offset + n), ch * n);
    }
    const data = new AudioData({
      format: "f32-planar",
      sampleRate: out.sampleRate,
      numberOfFrames: n,
      numberOfChannels: out.numberOfChannels,
      timestamp: Math.round((offset / out.sampleRate) * 1_000_000),
      data: planar.buffer,
    });
    encoder.encode(data);
    data.close();
    while (encoder.encodeQueueSize > 8) {
      await new Promise<void>((r) => setTimeout(r, 0));
      if (encodeError) throw encodeError;
    }
  }

  await encoder.flush();
  encoder.close();
  if (encodeError) throw encodeError;
}

/**
 * Pick an H.264 codec string whose level actually covers width×height. A fixed
 * low level (e.g. baseline 3.1 = max 1280×720) makes configure() reject for
 * portrait/HD targets — and then encode() throws "closed codec". Try High
 * profile from level 5.2 down and take the first the encoder reports supported
 * for these dims; fall back to baseline 3.1.
 */
async function pickAvcCodec(width: number, height: number, bitrate: number, fps: number): Promise<string> {
  const candidates = [
    "avc1.640034", // High 5.2  (≤ 4K)
    "avc1.640033", // High 5.1
    "avc1.64002a", // High 4.2  (≤ 1080p-ish)
    "avc1.640028", // High 4.0
    "avc1.42001f", // Baseline 3.1 (≤ 720p)
  ];
  for (const codec of candidates) {
    try {
      const s = await VideoEncoder.isConfigSupported({
        codec,
        width,
        height,
        bitrate,
        framerate: fps,
        avc: { format: "avc" },
      });
      if (s.supported) return codec;
    } catch {
      /* try the next candidate */
    }
  }
  return "avc1.640034";
}

export async function exportTimelineToMp4(opts: ExportOptions): Promise<Uint8Array> {
  const { timeline, drawDeps, backend, width, height, fps, durationSec, cropRect, onProgress, cancelCheck } =
    opts;
  const deps: DrawDeps = cropRect ? { ...drawDeps, cropRect } : drawDeps;
  const total = Math.max(1, Math.round(durationSec * fps));
  const frameDurUs = 1_000_000 / fps;
  // Scale the bitrate with resolution so portrait/HD targets aren't starved.
  const bitrate = Math.min(24_000_000, Math.max(4_000_000, Math.round(width * height * fps * 0.12)));

  const audioSegments = opts.audioSources ? resolveAudioSegments(timeline) : [];
  const audioOut = planAudio(audioSegments, opts.audioSources);

  const muxer = new Muxer({
    target: new ArrayBufferTarget(),
    video: { codec: "avc", width, height, frameRate: fps },
    ...(audioOut
      ? { audio: { codec: "aac" as const, numberOfChannels: audioOut.numberOfChannels, sampleRate: audioOut.sampleRate } }
      : {}),
    fastStart: "in-memory",
  });

  let encodeError: Error | null = null;
  const encoder = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (e) => {
      encodeError = e instanceof Error ? e : new Error(String(e));
    },
  });
  encoder.configure({
    codec: await pickAvcCodec(width, height, bitrate, fps),
    width,
    height,
    bitrate,
    framerate: fps,
    avc: { format: "avc" }, // length-prefixed (AVCC) — what mp4 wants
  });

  for (let i = 0; i < total; i++) {
    if (encodeError) throw encodeError;
    if (cancelCheck?.()) {
      encoder.close();
      throw new ExportCancelled();
    }

    const slice = resolveFrameAt(timeline, i / fps);
    const prepared = await prepareFrame(slice, deps, /* exact */ true);
    const px = await backend.renderOffscreenToBytes((rp) => paintPreparedFrame(backend, rp, prepared));
    disposePrepared(prepared);
    if (!px) throw new Error("offscreen render failed (no GPU target)");

    const frame = new VideoFrame(px.data, {
      format: px.format.startsWith("bgra") ? "BGRA" : "RGBA",
      codedWidth: px.width,
      codedHeight: px.height,
      timestamp: Math.round(i * frameDurUs),
      duration: Math.round(frameDurUs),
      layout: [{ offset: 0, stride: px.bytesPerRow }],
    });
    encoder.encode(frame, { keyFrame: i % fps === 0 });
    frame.close();

    while (encoder.encodeQueueSize > 8) {
      await new Promise<void>((r) => setTimeout(r, 0));
      if (encodeError) throw encodeError;
    }
    onProgress?.(i + 1, total);
  }

  await encoder.flush();
  encoder.close();
  if (encodeError) throw encodeError;

  // Audio pass: mix source PCM over the timeline and AAC-encode into the muxer.
  if (audioOut && opts.audioSources) {
    await encodeAudioTrack(muxer, audioSegments, opts.audioSources, audioOut, durationSec);
  }

  muxer.finalize();
  return new Uint8Array(muxer.target.buffer);
}
