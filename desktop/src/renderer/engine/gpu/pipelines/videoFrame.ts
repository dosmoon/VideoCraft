/**
 * Video-frame pipeline: samples a WebCodecs VideoFrame via
 * importExternalTexture (ported from Phase).
 *
 * External textures must use textureSampleBaseClampToEdge (not textureSample),
 * per WGSL spec. The fragment shader recentres UVs and applies a uniform scale
 * to letterbox/cover; out-of-range pixels are discarded (alpha 0) so this pass
 * can composite over a background instead of painting black bars.
 */

const SHADER = /* wgsl */ `
struct Uniforms {
  scale: vec2f,
}
@group(0) @binding(0) var samp: sampler;
@group(0) @binding(1) var tex: texture_external;
@group(0) @binding(2) var<uniform> u: Uniforms;

struct VertexOut {
  @builtin(position) pos: vec4f,
  @location(0) uv: vec2f,
}

@vertex
fn vs(@builtin(vertex_index) i: u32) -> VertexOut {
  var positions = array<vec2f, 6>(
    vec2f(-1.0, -1.0),
    vec2f( 1.0, -1.0),
    vec2f(-1.0,  1.0),
    vec2f(-1.0,  1.0),
    vec2f( 1.0, -1.0),
    vec2f( 1.0,  1.0),
  );
  var uvs = array<vec2f, 6>(
    vec2f(0.0, 1.0),
    vec2f(1.0, 1.0),
    vec2f(0.0, 0.0),
    vec2f(0.0, 0.0),
    vec2f(1.0, 1.0),
    vec2f(1.0, 0.0),
  );
  var out: VertexOut;
  out.pos = vec4f(positions[i], 0.0, 1.0);
  out.uv = uvs[i];
  return out;
}

@fragment
fn fs(in: VertexOut) -> @location(0) vec4f {
  let centred = (in.uv - vec2f(0.5)) * u.scale + vec2f(0.5);
  if (centred.x < 0.0 || centred.x > 1.0 || centred.y < 0.0 || centred.y > 1.0) {
    discard;
  }
  return textureSampleBaseClampToEdge(tex, samp, centred);
}
`;

export interface VideoFramePipeline {
  pipeline: GPURenderPipeline;
  bindGroupLayout: GPUBindGroupLayout;
  sampler: GPUSampler;
  /** vec2f scale + 8B padding = 16B aligned. Caller writes [scaleX, scaleY, 0, 0]. */
  uniformBuffer: GPUBuffer;
}

export function createVideoFramePipeline(
  device: GPUDevice,
  format: GPUTextureFormat,
): VideoFramePipeline {
  const module = device.createShaderModule({ code: SHADER });
  const bindGroupLayout = device.createBindGroupLayout({
    entries: [
      { binding: 0, visibility: GPUShaderStage.FRAGMENT, sampler: { type: "filtering" } },
      { binding: 1, visibility: GPUShaderStage.FRAGMENT, externalTexture: {} },
      { binding: 2, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "uniform" } },
    ],
  });
  const pipeline = device.createRenderPipeline({
    layout: device.createPipelineLayout({ bindGroupLayouts: [bindGroupLayout] }),
    vertex: { module, entryPoint: "vs" },
    fragment: { module, entryPoint: "fs", targets: [{ format }] },
    primitive: { topology: "triangle-list" },
  });
  const sampler = device.createSampler({ magFilter: "linear", minFilter: "linear" });
  const uniformBuffer = device.createBuffer({
    size: 16,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });
  return { pipeline, bindGroupLayout, sampler, uniformBuffer };
}
