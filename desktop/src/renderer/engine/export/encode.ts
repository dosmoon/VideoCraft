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

export interface ExportOptions {
  timeline: Timeline;
  drawDeps: DrawDeps;
  backend: Backend;
  width: number;
  height: number;
  fps: number;
  durationSec: number;
  onProgress?: (done: number, total: number) => void;
}

export async function exportTimelineToMp4(opts: ExportOptions): Promise<Uint8Array> {
  const { timeline, drawDeps, backend, width, height, fps, durationSec, onProgress } = opts;
  const total = Math.max(1, Math.round(durationSec * fps));
  const frameDurUs = 1_000_000 / fps;

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
    codec: "avc1.42001f", // H.264 baseline, level 3.1 (covers 720p30)
    width,
    height,
    bitrate: 6_000_000,
    framerate: fps,
    avc: { format: "avc" }, // length-prefixed (AVCC) — what mp4 wants
  });

  for (let i = 0; i < total; i++) {
    if (encodeError) throw encodeError;

    const slice = resolveFrameAt(timeline, i / fps);
    const prepared = await prepareFrame(slice, drawDeps, /* exact */ true);
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
