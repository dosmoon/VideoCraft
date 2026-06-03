/**
 * WebCodecs encode sink — the in-browser H.264 path (software on Windows;
 * Chromium exposes no hardware encoder here, see reference_webcodecs_encode_cap).
 * Renders each frame to the GPU swapchain canvas and captures it straight into a
 * VideoFrame (no GPU→CPU readback — the browser keeps it GPU-side), encodes with
 * VideoEncoder, muxes to mp4 (streamed to disk via the `output` sink for large
 * renders, or returned as bytes). This is a verbatim extraction of the original
 * exportTimelineToMp4 inner loop — behaviour must stay identical.
 */

import { ArrayBufferTarget, Muxer, StreamTarget } from "mp4-muxer";
import { resolveAudioSegments, type AudioSegment } from "@composition/compositor/resolveAudio.js";
import { paintPreparedFrame } from "../compositor/draw";
import type { DecodedAudio } from "../source/sample-types";
import { mixAudio } from "./audioMix";
import type { ExportOptions } from "./encode";
import type { EffectiveExportParams, EncodeSink } from "./types";

type MuxTarget = ArrayBufferTarget | StreamTarget;

/** Fixed export audio rate; sources are linearly resampled to it in the mix. */
const AUDIO_SAMPLE_RATE = 48_000;
const AUDIO_BITRATE = 192_000;

interface AudioOut {
  sampleRate: number;
  numberOfChannels: number;
}

/**
 * Block until the encoder's queue drains to `max`, sleeping on the `dequeue`
 * event rather than polling with setTimeout. setTimeout(0) is clamped to ~4ms
 * for nested timers, so a poll loop throttles throughput even when the encoder
 * is far faster — the dequeue event wakes us the instant a frame leaves the
 * queue. A short timeout backstops the rare missed-event race.
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

/**
 * Build the WebCodecs encode sink. Configures the video encoder + muxer up front
 * (async — codec probe), then returns the per-frame `consume` + `finish`/`abort`.
 */
export async function createWebCodecsSink(
  opts: ExportOptions,
  params: EffectiveExportParams,
): Promise<EncodeSink> {
  const { width, height, fps, bitrate } = params;
  const frameDurUs = 1_000_000 / fps;
  const streaming = opts.output;

  const audioSegments = opts.audioSources ? resolveAudioSegments(opts.timeline) : [];
  const audioOut = planAudio(audioSegments, opts.audioSources);

  // Streaming to disk (full-source renders) vs in-memory buffer (small clip
  // outputs). Streaming can't move the moov atom to the front without buffering
  // the whole file, so it uses fastStart:false (moov at end) — fine for local
  // playback. The in-memory path keeps fastStart:"in-memory" (faststart mp4).
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

  return {
    async consume(backend, prepared, index) {
      if (encodeError) throw encodeError;
      // Render into the GPU canvas and capture it straight into a VideoFrame —
      // no copyTextureToBuffer/mapAsync readback; captured synchronously right
      // after submit so it reflects exactly this frame's draw.
      const rp = backend.beginPass();
      if (!rp) throw new Error("render failed (no GPU target)");
      paintPreparedFrame(backend, rp, prepared);
      backend.endPass(rp);

      const canvas = backend.canvasElement;
      if (!canvas) throw new Error("render failed (no canvas)");
      const frame = new VideoFrame(canvas, {
        timestamp: Math.round(index * frameDurUs),
        duration: Math.round(frameDurUs),
      });
      encoder.encode(frame, { keyFrame: index % fps === 0 });
      frame.close();

      await drainQueueBelow(encoder, 16, () => encodeError);
      // Flush pending disk writes periodically — the muxer emits 16 MiB chunks
      // hundreds of frames apart, so draining every frame just folds IO into the
      // loop. A rejected write surfaces here and aborts the export.
      if (streaming?.drain && (index + 1) % 120 === 0) await streaming.drain();
    },

    async finish() {
      if (encodeError) throw encodeError;
      await encoder.flush();
      encoder.close();
      if (encodeError) throw encodeError;

      // Audio pass: mix source PCM over the timeline and AAC-encode into the muxer.
      if (audioOut && opts.audioSources) {
        await encodeAudioTrack(muxer, audioSegments, opts.audioSources, audioOut, opts.durationSec);
      }

      muxer.finalize();
      if (streaming) {
        if (streaming.drain) await streaming.drain();
        return new Uint8Array(0);
      }
      return new Uint8Array((target as ArrayBufferTarget).buffer);
    },

    async abort() {
      try {
        if (encoder.state !== "closed") encoder.close();
      } catch {
        /* already closed */
      }
    },
  };
}
