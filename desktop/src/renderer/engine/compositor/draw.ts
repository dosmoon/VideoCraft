/**
 * GPU draw layer — consumes a FrameSlice (from resolveFrameAt) and paints it,
 * dispatching by Clip.kind. This is the substrate side of preview≡render: the
 * same prepare+paint feed both the on-screen preview (swapchain) and the export
 * (offscreen render target), so they cannot diverge.
 *
 * Split into prepare (async: fetch media frames + build overlay textures) and
 * paint (sync: draw layers into a given pass). Preview begins a swapchain pass;
 * export begins an offscreen pass it can read back (the swapchain can't be read
 * — WebGPU doesn't preserve the drawing buffer).
 *
 * Representative-subset coverage (substrate round): media `video` (external
 * texture) + canvas2D text/subtitle overlays. audio, transitions, and the rest
 * are later production work.
 */

import { isMediaKind } from "@composition/catalog.js";
import type { FrameSlice } from "@composition/compositor/resolve.js";
import type { Backend, RenderPass } from "../gpu/Backend";
import type { FitMode } from "../gpu/aspect";
import type { VideoSource } from "../types";
import { drawOverlayClip, isCanvas2dOverlay } from "../overlay/canvas2d";

export interface DrawDeps {
  backend: Backend;
  /** mediaRef → decoded-frame source. */
  sources: Map<string, VideoSource>;
  fit: FitMode;
  /** Reused scratch canvas for 2D overlays (sized to the GPU canvas). */
  overlayCanvas: OffscreenCanvas;
  overlayCtx: OffscreenCanvasRenderingContext2D;
  /** Reframe export offset crop ({x,y,w,h} normalized source coords). */
  cropRect?: { x: number; y: number; w: number; h: number };
}

type Layer =
  | { kind: "video"; frame: VideoFrame; fit: FitMode; crop?: { x: number; y: number; w: number; h: number } }
  | { kind: "overlay"; texture: GPUTexture };

/** Counts of what got drawn this frame — handy for the harness HUD. */
export interface DrawStats {
  video: number;
  overlay: number;
  skipped: number;
  /** Timestamp (µs) of the first drawn video frame — for seek-precision HUD. */
  videoTimestampUs: number | null;
}

/** Layers + owned GPU resources for one frame, ready to paint then dispose. */
export interface PreparedFrame {
  layers: Layer[];
  frames: VideoFrame[];
  textures: GPUTexture[];
  stats: DrawStats;
}

/**
 * Async: fetch media frames + rasterise overlay textures, z-ascending.
 * `exact` (export) waits for the precise target frame; preview leaves it false
 * for non-blocking scrub.
 */
export async function prepareFrame(
  slice: FrameSlice,
  deps: DrawDeps,
  exact = false,
): Promise<PreparedFrame> {
  const { backend, sources, fit, overlayCanvas, overlayCtx } = deps;
  const w = overlayCanvas.width;
  const h = overlayCanvas.height;

  const layers: Layer[] = [];
  const frames: VideoFrame[] = [];
  const textures: GPUTexture[] = [];
  const stats: DrawStats = { video: 0, overlay: 0, skipped: 0, videoTimestampUs: null };

  for (const track of slice.tracks) {
    // Audio tracks carry no visual layers — they're mixed separately (preview
    // AudioPlayback / export encodeAudioTrack). Skip them here, else an audio
    // clip (also a media kind) would fetch the video reader and draw a stray
    // video layer.
    if (track.kind === "audio") continue;
    for (const ac of track.clips) {
      const c = ac.clip;
      if (isMediaKind(c.kind)) {
        const src = c.mediaRef ? sources.get(c.mediaRef) : undefined;
        if (!src) {
          stats.skipped++;
          continue;
        }
        const sourceUs = (ac.sourceTimeSec ?? 0) * 1_000_000;
        const frame =
          exact && src.frameAtExact ? await src.frameAtExact(sourceUs) : await src.frameAt(sourceUs);
        if (frame) {
          if (stats.videoTimestampUs == null) stats.videoTimestampUs = frame.timestamp;
          frames.push(frame);
          layers.push({ kind: "video", frame, fit, ...(deps.cropRect ? { crop: deps.cropRect } : {}) });
        } else {
          stats.skipped++;
        }
      } else if (isCanvas2dOverlay(c.kind)) {
        overlayCtx.clearRect(0, 0, w, h);
        if (!drawOverlayClip(overlayCtx, c, w, h)) {
          stats.skipped++;
          continue;
        }
        const tex = backend.createOverlayTexture();
        if (!tex) {
          stats.skipped++;
          continue;
        }
        backend.uploadOverlay(tex, overlayCanvas);
        textures.push(tex);
        layers.push({ kind: "overlay", texture: tex });
      } else {
        // audio, transitions, and overlay kinds outside this subset.
        stats.skipped++;
      }
    }
  }
  return { layers, frames, textures, stats };
}

/** Sync: paint prepared layers into an open pass, background→front. */
export function paintPreparedFrame(backend: Backend, rp: RenderPass, prepared: PreparedFrame): void {
  for (const layer of prepared.layers) {
    if (layer.kind === "video") {
      backend.drawVideoFrame(rp, layer.frame, layer.fit, layer.crop);
      prepared.stats.video++;
    } else {
      backend.drawOverlayTexture(rp, layer.texture);
      prepared.stats.overlay++;
    }
  }
}

/** Release a prepared frame's GPU resources (call after painting + submit). */
export function disposePrepared(prepared: PreparedFrame): void {
  for (const f of prepared.frames) f.close();
  for (const t of prepared.textures) t.destroy();
}

/** Preview path: prepare → swapchain pass → paint → dispose. */
export async function drawFrameSlice(
  slice: FrameSlice,
  deps: DrawDeps,
  exact = false,
): Promise<DrawStats> {
  const prepared = await prepareFrame(slice, deps, exact);
  const rp = deps.backend.beginPass();
  if (rp) {
    paintPreparedFrame(deps.backend, rp, prepared);
    deps.backend.endPass(rp);
  }
  disposePrepared(prepared);
  return prepared.stats;
}
