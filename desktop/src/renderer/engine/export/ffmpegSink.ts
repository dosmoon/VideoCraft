/**
 * ffmpeg encode sink — the native hardware path (h264_nvenc), the route around
 * Chromium's software-only WebCodecs encoder. Renders each frame to an OFFSCREEN
 * GPU target, reads the pixels back, and pipes the raw frame to a main-process
 * ffmpeg job (window.vc.ffmpegEncode) which encodes + pulls audio from the source
 * file and writes the mp4 to disk. Rendering stays on the GPU (same prepareFrame/
 * paintPreparedFrame as preview), so preview≡render holds — ffmpeg only encodes.
 *
 * Readback is one-shot per frame (~sub-ms GPU round-trip); NVENC runs in a
 * separate process, so the encoder, not the readback, is the throughput limit.
 */

import { paintPreparedFrame } from "../compositor/draw";
import type { ExportOptions } from "./encode";
import type { EffectiveExportParams, EncodeSink } from "./types";

export interface FfmpegTarget {
  /** Final mp4 path (ffmpeg owns the write; .part→rename in main). */
  outputPath: string;
  /** Source file to pull the audio track from (omit for silent output). */
  sourcePath?: string;
  /** Audio in-point (sec) for a clip window; omit for full-source. */
  audioStartSec?: number;
}

export async function createFfmpegSink(
  opts: ExportOptions,
  params: EffectiveExportParams,
  target: FfmpegTarget,
): Promise<EncodeSink> {
  // Canvas/readback format on Windows is bgra8unorm; tell ffmpeg the right input.
  const pixfmt = opts.backend.textureFormat.startsWith("rgba") ? "rgba" : "bgra";
  const jobId = await window.vc.ffmpegEncode.start({
    outputPath: target.outputPath,
    width: params.width,
    height: params.height,
    fps: params.fps,
    bitrate: params.bitrate,
    pixfmt,
    ...(target.sourcePath ? { sourcePath: target.sourcePath } : {}),
    ...(target.audioStartSec != null ? { audioStartSec: target.audioStartSec } : {}),
  });

  return {
    async consume(backend, prepared) {
      const px = await backend.renderOffscreenToBytes((rp) => paintPreparedFrame(backend, rp, prepared));
      if (!px) throw new Error("render failed (no GPU target)");
      // ffmpeg rawvideo wants tightly-packed rows; the GPU readback row stride is
      // 256-aligned (e.g. 1080px → 4352 not 4320), so repack when they differ.
      const rowBytes = px.width * 4;
      let frame: Uint8Array;
      if (px.bytesPerRow === rowBytes) {
        frame = px.data;
      } else {
        frame = new Uint8Array(rowBytes * px.height);
        for (let y = 0; y < px.height; y++) {
          const src = y * px.bytesPerRow;
          frame.set(px.data.subarray(src, src + rowBytes), y * rowBytes);
        }
      }
      await window.vc.ffmpegEncode.writeFrame(jobId, frame);
    },

    async finish() {
      await window.vc.ffmpegEncode.finish(jobId);
      return new Uint8Array(0); // ffmpeg wrote the file directly
    },

    async abort() {
      await window.vc.ffmpegEncode.abort(jobId);
    },
  };
}
