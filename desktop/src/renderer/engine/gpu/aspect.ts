/**
 * Aspect-fit math for the WebGPU video pipeline (ported from Phase).
 * Pure logic: no GPU/DOM deps, unit-testable.
 *
 * The video shader recentres frame UVs around (0.5,0.5) and applies scale:
 *   centred = (uv - 0.5) * scale + 0.5
 * - scale > 1 on an axis → UV range extends past [0,1] → bars (letterbox).
 * - scale < 1 → frame cropped on that axis (cover).
 */

export type FitMode = "contain" | "cover";

export interface AspectInput {
  srcWidth: number;
  srcHeight: number;
  dstWidth: number;
  dstHeight: number;
  mode: FitMode;
}

export interface AspectScale {
  scaleX: number;
  scaleY: number;
}

export function computeAspectScale(input: AspectInput): AspectScale {
  const { srcWidth, srcHeight, dstWidth, dstHeight, mode } = input;
  if (srcWidth <= 0 || srcHeight <= 0 || dstWidth <= 0 || dstHeight <= 0) {
    return { scaleX: 1, scaleY: 1 };
  }
  const frameAspect = srcWidth / srcHeight;
  const canvasAspect = dstWidth / dstHeight;

  let scaleX = 1;
  let scaleY = 1;
  if (mode === "contain") {
    if (frameAspect > canvasAspect) {
      scaleY = frameAspect / canvasAspect;
    } else {
      scaleX = canvasAspect / frameAspect;
    }
  } else {
    if (frameAspect > canvasAspect) {
      scaleX = canvasAspect / frameAspect;
    } else {
      scaleY = frameAspect / canvasAspect;
    }
  }
  return { scaleX, scaleY };
}
