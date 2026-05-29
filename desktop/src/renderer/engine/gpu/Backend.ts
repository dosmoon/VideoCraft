/**
 * WebGPU rendering backend (adapted from Phase's WebGPUBackend).
 *
 * Thin device/context lifecycle + a composable render-pass API. Phase drew a
 * single layer per render(); we expose beginPass / drawVideoFrame / endPass so
 * Phase 2's drawFrameSlice can paint many layers (video + overlays) into one
 * pass, z-ascending. `present()` is the Phase-1 single-layer convenience.
 */

import { computeAspectScale, type FitMode } from "./aspect";
import { createVideoFramePipeline, type VideoFramePipeline } from "./pipelines/videoFrame";
import {
  createOverlayTexturePipeline,
  type OverlayTexturePipeline,
} from "./pipelines/overlayTexture";
import { EngineError } from "../errors";

/** A 2D image source the overlay path can upload (OffscreenCanvas or canvas). */
export type OverlayImageSource =
  | OffscreenCanvas
  | HTMLCanvasElement
  | ImageBitmap;

export interface RenderPass {
  encoder: GPUCommandEncoder;
  pass: GPURenderPassEncoder;
}

const DEFAULT_CLEAR: GPUColor = { r: 0.07, g: 0.07, b: 0.08, a: 1 };

export class Backend {
  private device: GPUDevice | null = null;
  private context: GPUCanvasContext | null = null;
  private videoPipeline: VideoFramePipeline | null = null;
  private overlayPipeline: OverlayTexturePipeline | null = null;
  private format: GPUTextureFormat = "bgra8unorm";
  private canvas: HTMLCanvasElement | null = null;
  // Offscreen target + readback buffer for export (the swapchain can't be read).
  private offscreenTarget: GPUTexture | null = null;
  private readbackBuffer: GPUBuffer | null = null;
  private targetW = 0;
  private targetH = 0;

  async init(canvas: HTMLCanvasElement): Promise<void> {
    if (!("gpu" in navigator) || !navigator.gpu) {
      throw new EngineError("WebGPU not available", "NO_WEBGPU");
    }
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) throw new EngineError("No GPU adapter found", "NO_ADAPTER");
    const device = await adapter.requestDevice();
    const ctx = canvas.getContext("webgpu");
    if (!ctx) throw new EngineError("Failed to acquire webgpu context", "NO_CONTEXT");
    const format = navigator.gpu.getPreferredCanvasFormat();
    ctx.configure({ device, format, alphaMode: "premultiplied" });

    this.canvas = canvas;
    this.device = device;
    this.context = ctx;
    this.format = format;
    this.videoPipeline = createVideoFramePipeline(device, format);
    this.overlayPipeline = createOverlayTexturePipeline(device, format);
  }

  get gpuDevice(): GPUDevice | null {
    return this.device;
  }

  /** The backing canvas — captured as a VideoFrame source during export. */
  get canvasElement(): HTMLCanvasElement | null {
    return this.canvas;
  }

  get textureFormat(): GPUTextureFormat {
    return this.format;
  }

  resize(width: number, height: number): void {
    if (!this.canvas) return;
    const w = Math.max(1, Math.floor(width));
    const h = Math.max(1, Math.floor(height));
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
  }

  /** Begin a render pass that clears the canvas. */
  beginPass(clear: GPUColor = DEFAULT_CLEAR): RenderPass | null {
    if (!this.device || !this.context) return null;
    const view = this.context.getCurrentTexture().createView();
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        { view, clearValue: clear, loadOp: "clear", storeOp: "store" },
      ],
    });
    return { encoder, pass };
  }

  /**
   * Draw one WebCodecs VideoFrame into the open pass, aspect-fit. The frame is
   * read synchronously here (external texture is valid only within this task);
   * the caller closes the frame after endPass().
   */
  drawVideoFrame(rp: RenderPass, frame: VideoFrame, fit: FitMode): void {
    if (!this.device || !this.canvas || !this.videoPipeline) return;

    const { scaleX, scaleY } = computeAspectScale({
      srcWidth: frame.displayWidth,
      srcHeight: frame.displayHeight,
      dstWidth: this.canvas.width,
      dstHeight: this.canvas.height,
      mode: fit,
    });

    this.device.queue.writeBuffer(
      this.videoPipeline.uniformBuffer,
      0,
      new Float32Array([scaleX, scaleY, 0, 0]),
    );

    const externalTexture = this.device.importExternalTexture({ source: frame });
    const bindGroup = this.device.createBindGroup({
      layout: this.videoPipeline.bindGroupLayout,
      entries: [
        { binding: 0, resource: this.videoPipeline.sampler },
        { binding: 1, resource: externalTexture },
        { binding: 2, resource: { buffer: this.videoPipeline.uniformBuffer } },
      ],
    });

    rp.pass.setPipeline(this.videoPipeline.pipeline);
    rp.pass.setBindGroup(0, bindGroup);
    rp.pass.draw(6);
  }

  /** Allocate an RGBA texture sized to the canvas, for overlay layers. */
  createOverlayTexture(): GPUTexture | null {
    if (!this.device || !this.canvas) return null;
    return this.device.createTexture({
      size: [this.canvas.width, this.canvas.height],
      format: "rgba8unorm",
      usage:
        GPUTextureUsage.COPY_DST |
        GPUTextureUsage.TEXTURE_BINDING |
        GPUTextureUsage.RENDER_ATTACHMENT,
    });
  }

  /** Copy a 2D image source (e.g. an OffscreenCanvas) into an overlay texture. */
  uploadOverlay(texture: GPUTexture, source: OverlayImageSource): void {
    if (!this.device || !this.canvas) return;
    this.device.queue.copyExternalImageToTexture(
      { source },
      { texture },
      [this.canvas.width, this.canvas.height],
    );
  }

  /** Draw an overlay texture over the current pass contents (alpha-blended). */
  drawOverlayTexture(rp: RenderPass, texture: GPUTexture): void {
    if (!this.device || !this.overlayPipeline) return;
    const bindGroup = this.device.createBindGroup({
      layout: this.overlayPipeline.bindGroupLayout,
      entries: [
        { binding: 0, resource: this.overlayPipeline.sampler },
        { binding: 1, resource: texture.createView() },
      ],
    });
    rp.pass.setPipeline(this.overlayPipeline.pipeline);
    rp.pass.setBindGroup(0, bindGroup);
    rp.pass.draw(6);
  }

  endPass(rp: RenderPass): void {
    if (!this.device) return;
    rp.pass.end();
    this.device.queue.submit([rp.encoder.finish()]);
  }

  /** Result of an offscreen render: raw pixels + layout for VideoFrame. */
  // (declared inline in renderOffscreenToBytes' return type)

  private ensureTarget(): boolean {
    if (!this.device || !this.canvas) return false;
    const w = this.canvas.width;
    const h = this.canvas.height;
    if (this.offscreenTarget && this.targetW === w && this.targetH === h) return true;
    this.offscreenTarget?.destroy();
    this.readbackBuffer?.destroy();
    this.offscreenTarget = this.device.createTexture({
      size: [w, h],
      format: this.format,
      usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC,
    });
    const bytesPerRow = Math.ceil((w * 4) / 256) * 256; // copyTextureToBuffer alignment
    this.readbackBuffer = this.device.createBuffer({
      size: bytesPerRow * h,
      usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });
    this.targetW = w;
    this.targetH = h;
    return true;
  }

  /**
   * Render one frame into an offscreen target (via the `paint` callback) and
   * read the pixels back — used by export, since the swapchain isn't readable.
   * Returns the raw bytes plus the row stride + format needed to wrap them in a
   * VideoFrame.
   */
  async renderOffscreenToBytes(
    paint: (rp: RenderPass) => void,
    clear: GPUColor = DEFAULT_CLEAR,
  ): Promise<{ data: Uint8Array; width: number; height: number; bytesPerRow: number; format: GPUTextureFormat } | null> {
    if (!this.device || !this.ensureTarget() || !this.offscreenTarget || !this.readbackBuffer) {
      return null;
    }
    const w = this.targetW;
    const h = this.targetH;
    const bytesPerRow = Math.ceil((w * 4) / 256) * 256;
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        { view: this.offscreenTarget.createView(), clearValue: clear, loadOp: "clear", storeOp: "store" },
      ],
    });
    paint({ encoder, pass });
    pass.end();
    encoder.copyTextureToBuffer(
      { texture: this.offscreenTarget },
      { buffer: this.readbackBuffer, bytesPerRow, rowsPerImage: h },
      { width: w, height: h, depthOrArrayLayers: 1 },
    );
    this.device.queue.submit([encoder.finish()]);
    await this.readbackBuffer.mapAsync(GPUMapMode.READ);
    const data = new Uint8Array(this.readbackBuffer.getMappedRange().slice(0));
    this.readbackBuffer.unmap();
    return { data, width: w, height: h, bytesPerRow, format: this.format };
  }

  /** Phase-1 convenience: clear + draw a single video frame (or just clear). */
  present(frame: VideoFrame | null, fit: FitMode = "contain"): void {
    const rp = this.beginPass();
    if (!rp) return;
    if (frame) this.drawVideoFrame(rp, frame, fit);
    this.endPass(rp);
  }

  dispose(): void {
    this.offscreenTarget?.destroy();
    this.readbackBuffer?.destroy();
    this.offscreenTarget = null;
    this.readbackBuffer = null;
    this.device?.destroy();
    this.device = null;
    this.context = null;
    this.videoPipeline = null;
    this.overlayPipeline = null;
    this.canvas = null;
  }
}
