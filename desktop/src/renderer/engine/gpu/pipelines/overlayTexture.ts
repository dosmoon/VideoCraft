/**
 * Overlay-texture pipeline: composites a full-frame RGBA texture (a 2D-rendered
 * overlay layer, or later a libass bitmap) over whatever is already in the pass,
 * with straight-alpha src-over blending.
 *
 * Full-frame layers (rather than per-element quads) mirror how ASS/libass and
 * the Python overlay model work — each overlay track resolves to one RGBA image
 * the size of the frame. UV mapping matches the video pipeline so image row 0
 * lands at the top of the canvas.
 */

const SHADER = /* wgsl */ `
@group(0) @binding(0) var samp: sampler;
@group(0) @binding(1) var tex: texture_2d<f32>;

struct VertexOut {
  @builtin(position) pos: vec4f,
  @location(0) uv: vec2f,
}

@vertex
fn vs(@builtin(vertex_index) i: u32) -> VertexOut {
  var positions = array<vec2f, 6>(
    vec2f(-1.0, -1.0), vec2f( 1.0, -1.0), vec2f(-1.0,  1.0),
    vec2f(-1.0,  1.0), vec2f( 1.0, -1.0), vec2f( 1.0,  1.0),
  );
  var uvs = array<vec2f, 6>(
    vec2f(0.0, 1.0), vec2f(1.0, 1.0), vec2f(0.0, 0.0),
    vec2f(0.0, 0.0), vec2f(1.0, 1.0), vec2f(1.0, 0.0),
  );
  var out: VertexOut;
  out.pos = vec4f(positions[i], 0.0, 1.0);
  out.uv = uvs[i];
  return out;
}

@fragment
fn fs(in: VertexOut) -> @location(0) vec4f {
  return textureSample(tex, samp, in.uv);
}
`;

export interface OverlayTexturePipeline {
  pipeline: GPURenderPipeline;
  bindGroupLayout: GPUBindGroupLayout;
  sampler: GPUSampler;
}

export function createOverlayTexturePipeline(
  device: GPUDevice,
  format: GPUTextureFormat,
): OverlayTexturePipeline {
  const module = device.createShaderModule({ code: SHADER });
  const bindGroupLayout = device.createBindGroupLayout({
    entries: [
      { binding: 0, visibility: GPUShaderStage.FRAGMENT, sampler: { type: "filtering" } },
      { binding: 1, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: "float" } },
    ],
  });
  const pipeline = device.createRenderPipeline({
    layout: device.createPipelineLayout({ bindGroupLayouts: [bindGroupLayout] }),
    vertex: { module, entryPoint: "vs" },
    fragment: {
      module,
      entryPoint: "fs",
      targets: [
        {
          format,
          // Straight-alpha src-over: out = src.rgb*src.a + dst.rgb*(1-src.a).
          blend: {
            color: { srcFactor: "src-alpha", dstFactor: "one-minus-src-alpha", operation: "add" },
            alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" },
          },
        },
      ],
    },
    primitive: { topology: "triangle-list" },
  });
  const sampler = device.createSampler({ magFilter: "linear", minFilter: "linear" });
  return { pipeline, bindGroupLayout, sampler };
}
