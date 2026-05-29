/**
 * Compositor — consumes the OTIO Timeline and produces frames.
 *
 * Current surface is the substrate-independent frame resolver (resolve.ts).
 * The GPU draw layer (WebGPU/WebCodecs/libass-wasm) will land here and consume
 * FrameSlice; it must not re-derive timing.
 */
export * from "./resolve.js";
