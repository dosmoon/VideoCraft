/**
 * Video-frame pipeline: samples a WebCodecs VideoFrame via
 * importExternalTexture (ported from Phase).
 *
 * External textures must use textureSampleBaseClampToEdge (not textureSample),
 * per WGSL spec. Two sampling modes (selected by `mode`):
 *   - mode 0 (fit): recentre UVs + uniform scale to letterbox/cover; out-of-
 *     range pixels are discarded (alpha 0) so it composites over a background.
 *   - mode 1 (crop): sample only the crop window [origin, origin+size] and map
 *     it across the whole output — the reframe export's offset crop. The crop
 *     window is already output-aspect, so it fills exactly (no letterbox).
 * Mode 0 is byte-identical to the original fit path (preview unaffected).
 */

const SHADER = /* wgsl */ `
struct Uniforms {
  scale: vec2f,       // fit mode
  cropOrigin: vec2f,  // crop mode: window origin (normalized source coords)
  cropSize: vec2f,    // crop mode: window size
  mode: f32,          // 0 = fit, 1 = crop
  _pad: f32,
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
  var s: vec2f;
  if (u.mode > 0.5) {
    s = u.cropOrigin + in.uv * u.cropSize;
  } else {
    s = (in.uv - vec2f(0.5)) * u.scale + vec2f(0.5);
  }
  if (s.x < 0.0 || s.x > 1.0 || s.y < 0.0 || s.y > 1.0) {
    discard;
  }
  return textureSampleBaseClampToEdge(tex, samp, s);
}
`;

export interface VideoFramePipeline {
  pipeline: GPURenderPipeline;
  bindGroupLayout: GPUBindGroupLayout;
  sampler: GPUSampler;
  /** Uniforms struct (32B): [scaleX,scaleY, cropOX,cropOY, cropW,cropH, mode, pad]. */
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
    size: 32,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });
  return { pipeline, bindGroupLayout, sampler, uniformBuffer };
}
