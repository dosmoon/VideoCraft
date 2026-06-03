/**
 * Export-engine seam. The shared render loop (encode.ts::runRenderLoop) drives a
 * pluggable EncodeSink so multiple encode backends — in-browser WebCodecs, and
 * (later) native ffmpeg+NVENC — reuse the IDENTICAL GPU render path, which is
 * the preview≡render guarantee. Each sink owns its render target + encoder +
 * container.
 */

import type { Backend } from "../gpu/Backend";
import type { PreparedFrame } from "../compositor/draw";

/** Internal engine id. The UI's "Chromium" maps to "webcodecs". */
export type ExportEngine = "webcodecs" | "ffmpeg";

export type BitrateMode = "auto" | "mbps";

/** Resolved, ready-to-encode output params (one struct both engines agree on). */
export interface EffectiveExportParams {
  width: number;
  height: number;
  fps: number;
  /** Target video bitrate in bits/sec. */
  bitrate: number;
}

/**
 * Resolve the target video bitrate (bps). "auto" scales with resolution × fps
 * (the long-standing formula, clamped 4–24 Mbps); "mbps" uses the user value.
 */
export function resolveBitrate(
  mode: BitrateMode,
  mbps: number,
  width: number,
  height: number,
  fps: number,
): number {
  if (mode === "mbps" && mbps > 0) return Math.round(mbps * 1_000_000);
  return Math.min(24_000_000, Math.max(4_000_000, Math.round(width * height * fps * 0.12)));
}

/**
 * A pluggable encode backend behind the shared render loop. The loop prepares
 * each frame (decode + overlays) then hands it to `consume`, which renders it to
 * the sink's own target (swapchain canvas for WebCodecs; offscreen readback for
 * ffmpeg) and encodes it.
 */
export interface EncodeSink {
  /** Render `prepared` to this sink's target and encode frame `index`. */
  consume(backend: Backend, prepared: PreparedFrame, index: number): Promise<void>;
  /**
   * Flush video, encode any audio track, finalize the container. Returns mp4
   * bytes (in-memory sink) or an empty array (streamed/written to disk).
   */
  finish(): Promise<Uint8Array>;
  /** Release resources on cancel/error (idempotent). */
  abort(): Promise<void>;
}
