/**
 * WebCodecs export. Walk the timeline's output frames, prepare each via the SAME
 * prepareFrame/paintPreparedFrame the preview uses (so preview≡render is
 * structural), render into the GPU canvas, capture the canvas straight into a
 * VideoFrame (no GPU→CPU readback — the browser keeps it GPU-side), encode with
 * VideoEncoder, mux to mp4. The mp4 streams to disk via the `output` sink (16
 * MiB chunks) for large renders, or is returned as bytes for small ones.
 *
 * Note: this is the in-browser encode path. It's software H.264 (~135 fps@1080p)
 * — Chromium exposes no hardware encoder for WebCodecs on this platform. The
 * native ffmpeg + NVENC path (sidecar) is the route to hardware-speed export.
 */

import { ArrayBufferTarget, Muxer, StreamTarget } from "mp4-muxer";

type MuxTarget = ArrayBufferTarget | StreamTarget;
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

/**
 * Block until the encoder's queue drains to `max`, sleeping on the `dequeue`
 * event rather than polling with setTimeout. setTimeout(0) is clamped to ~4ms
 * for nested timers, so a poll loop throttles throughput to ~120 fps even when
 * the encoder is far faster — the dequeue event wakes us the instant a frame
 * leaves the queue. A short timeout backstops the rare missed-event race.
 */
async function drainQueueBelow(
  encoder: VideoEncoder | AudioEncoder,
  max: number,
  checkError: () => Error | null,
): Promise<void> {
  while (encoder.encodeQueueSize > max) {
    const err = checkError();
    if (err) throw err;
    await new Promise<void>((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        encoder.removeEventListener("dequeue", finish);
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(finish, 8);
      encoder.addEventListener("dequeue", finish);
    });
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
  /**
   * When set, the muxed mp4 is STREAMED to this sink (16 MiB chunks, at the
   * given byte position) instead of being buffered whole in memory and returned.
   * Required for full-source renders, which are too large to hold in one
   * ArrayBuffer (let alone copy over IPC). `drain` is awaited once per frame so
   * pending writes flush and outstanding data stays bounded; the function
   * returns an empty Uint8Array in this mode.
   */
  output?: {
    onData: (data: Uint8Array, position: number) => void;
    drain?: () => Promise<void>;
  };
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
  muxer: Muxer<MuxTarget>,
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
    await drainQueueBelow(encoder, 8, () => encodeError);
  }

  await encoder.flush();
  encoder.close();
  if (encodeError) throw encodeError;
}

/**
 * Pick a working H.264 encoder config. Probes codec level (a fixed low level
 * like baseline 3.1 = max 1280×720 makes configure() reject portrait/HD targets,
 * then encode() throws "closed codec") × acceleration × latency, taking the
 * first the encoder reports supported. `latencyMode:"realtime"` drops B-frames/
 * lookahead for speed; prefer-hardware is honoured where a hardware encoder
 * exists (none on the current Windows/Chromium, which falls back to software).
 */
async function pickEncoderConfig(
  width: number,
  height: number,
  bitrate: number,
  fps: number,
): Promise<VideoEncoderConfig> {
  const codecs = [
    "avc1.640034", // High 5.2  (≤ 4K)
    "avc1.640033", // High 5.1
    "avc1.64002a", // High 4.2  (≤ 1080p-ish)
    "avc1.640028", // High 4.0
    "avc1.42001f", // Baseline 3.1 (≤ 720p)
  ];
  const base = (
    codec: string,
    accel: HardwareAcceleration,
    latency: LatencyMode,
  ): VideoEncoderConfig => ({
    codec,
    width,
    height,
    bitrate,
    framerate: fps,
    avc: { format: "avc" }, // length-prefixed (AVCC) — what mp4 wants
    hardwareAcceleration: accel,
    latencyMode: latency,
  });
  for (const accel of ["prefer-hardware", "no-preference"] as const) {
    for (const latency of ["realtime", "quality"] as const) {
      for (const codec of codecs) {
        try {
          const s = await VideoEncoder.isConfigSupported(base(codec, accel, latency));
          if (s.supported) return base(codec, accel, latency);
        } catch {
          /* try the next candidate */
        }
      }
    }
  }
  return base("avc1.640034", "no-preference", "quality");
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

  // Streaming to disk (full-source renders) vs in-memory buffer (small clip
  // outputs). Streaming can't move the moov atom to the front without buffering
  // the whole file, so it uses fastStart:false (moov at end) — fine for local
  // playback. The in-memory path keeps fastStart:"in-memory" (faststart mp4).
  const streaming = opts.output;
  const target: MuxTarget = streaming
    ? new StreamTarget({ onData: streaming.onData, chunked: true })
    : new ArrayBufferTarget();
  const muxer = new Muxer({
    target,
    video: { codec: "avc", width, height, frameRate: fps },
    ...(audioOut
      ? { audio: { codec: "aac" as const, numberOfChannels: audioOut.numberOfChannels, sampleRate: audioOut.sampleRate } }
      : {}),
    fastStart: streaming ? false : "in-memory",
  });

  let encodeError: Error | null = null;
  const encoder = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (e) => {
      encodeError = e instanceof Error ? e : new Error(String(e));
    },
  });
  encoder.configure(await pickEncoderConfig(width, height, bitrate, fps));

  for (let i = 0; i < total; i++) {
    if (encodeError) throw encodeError;
    if (cancelCheck?.()) {
      encoder.close();
      throw new ExportCancelled();
    }

    const slice = resolveFrameAt(timeline, i / fps);
    const prepared = await prepareFrame(slice, deps, /* exact */ true);

    // Render into the GPU canvas and capture it straight into a VideoFrame.
    // Capturing the canvas (vs. copyTextureToBuffer + mapAsync readback) keeps
    // the pixels GPU-side — no per-frame stall, no CPU round-trip, no re-upload
    // by the encoder. Captured synchronously right after submit so it reflects
    // exactly this frame's draw.
    const rp = backend.beginPass();
    if (!rp) {
      disposePrepared(prepared);
      throw new Error("render failed (no GPU target)");
    }
    paintPreparedFrame(backend, rp, prepared);
    backend.endPass(rp);
    disposePrepared(prepared);

    const canvas = backend.canvasElement;
    if (!canvas) throw new Error("render failed (no canvas)");
    const frame = new VideoFrame(canvas, {
      timestamp: Math.round(i * frameDurUs),
      duration: Math.round(frameDurUs),
    });
    encoder.encode(frame, { keyFrame: i % fps === 0 });
    frame.close();

    await drainQueueBelow(encoder, 16, () => encodeError);
    // Flush pending disk writes periodically — the muxer emits 16 MiB chunks
    // hundreds of frames apart, so draining every frame just folds IO into the
    // loop. A rejected write surfaces here and aborts the export.
    if (streaming?.drain && ((i + 1) % 120 === 0 || i + 1 === total)) {
      await streaming.drain();
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
  if (streaming) {
    if (streaming.drain) await streaming.drain();
    return new Uint8Array(0);
  }
  return new Uint8Array((target as ArrayBufferTarget).buffer);
}
