/**
 * Export render loop. Walks the timeline's output frames and, for each, runs the
 * SAME prepareFrame the preview uses (so preview≡render is structural), then
 * hands the prepared frame to a pluggable EncodeSink that renders it to its own
 * target and encodes it. The sink chooses the engine:
 *   - WebCodecs (in-browser, software H.264) — webcodecsSink.ts
 *   - ffmpeg + NVENC (native, hardware) — ffmpegSink.ts [later]
 *
 * `exportTimelineToMp4` is the public entry (the export tabs call it); it builds
 * the WebCodecs sink. Engine selection moves here once ffmpegSink lands.
 */

import { resolveFrameAt } from "@composition/compositor/resolve.js";
import type { Timeline } from "@composition/ir.js";
import type { Backend } from "../gpu/Backend";
import type { DecodedAudio } from "../source/sample-types";
import { disposePrepared, prepareFrame, type DrawDeps } from "../compositor/draw";
import { resolveBitrate, type EncodeSink } from "./types";
import { createWebCodecsSink } from "./webcodecsSink";

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
  /** Target video bitrate (bps). Omit for the resolution-scaled auto formula. */
  bitrate?: number;
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
   * ArrayBuffer (let alone copy over IPC). The function returns an empty
   * Uint8Array in this mode.
   */
  output?: {
    onData: (data: Uint8Array, position: number) => void;
    drain?: () => Promise<void>;
  };
}

/**
 * Shared producer: iterate output frames, prepare each (decode + overlays), and
 * hand it to the sink. The sink owns rendering-to-its-target + encoding, so this
 * loop is engine-agnostic. On cancel/error the sink is aborted for cleanup.
 */
async function runRenderLoop(opts: ExportOptions, sink: EncodeSink): Promise<Uint8Array> {
  const { timeline, drawDeps, backend, fps, durationSec, cropRect, onProgress, cancelCheck } = opts;
  const deps: DrawDeps = cropRect ? { ...drawDeps, cropRect } : drawDeps;
  const total = Math.max(1, Math.round(durationSec * fps));
  try {
    for (let i = 0; i < total; i++) {
      if (cancelCheck?.()) throw new ExportCancelled();
      const slice = resolveFrameAt(timeline, i / fps);
      const prepared = await prepareFrame(slice, deps, /* exact */ true);
      try {
        await sink.consume(backend, prepared, i);
      } finally {
        disposePrepared(prepared);
      }
      onProgress?.(i + 1, total);
    }
    return await sink.finish();
  } catch (e) {
    await sink.abort();
    throw e;
  }
}

export async function exportTimelineToMp4(opts: ExportOptions): Promise<Uint8Array> {
  const params = {
    width: opts.width,
    height: opts.height,
    fps: opts.fps,
    bitrate: opts.bitrate ?? resolveBitrate("auto", 0, opts.width, opts.height, opts.fps),
  };
  const sink = await createWebCodecsSink(opts, params);
  return runRenderLoop(opts, sink);
}
