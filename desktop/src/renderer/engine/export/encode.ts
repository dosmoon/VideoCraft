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
import type { Timeline } from "@composition/ir.js";
import type { Backend } from "../gpu/Backend";
import {
  disposePrepared,
  paintPreparedFrame,
  prepareFrame,
  type DrawDeps,
} from "../compositor/draw";

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

  const muxer = new Muxer({
    target: new ArrayBufferTarget(),
    video: { codec: "avc", width, height, frameRate: fps },
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

  muxer.finalize();
  return new Uint8Array(muxer.target.buffer);
}
