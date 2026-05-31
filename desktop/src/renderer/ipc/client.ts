/**
 * Renderer-side RPC client — a thin typed wrapper over window.vc.rpc.
 *
 * The Python sidecar is the single owner of project/material state; the
 * renderer is a thin client (migration doc §2.3). This module unwraps the
 * tagged reply main forwards (`{ok:true,result}` | `{ok:false,...}`) back into
 * a resolved value or a thrown RpcError, and exposes typed method stubs for
 * the bound RPC surface.
 */

/** Mirrors the Python sidecar's JSON-RPC error (code + message + optional data). */
export class RpcError extends Error {
  code: number;
  data: unknown;
  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "RpcError";
    this.code = code;
    this.data = data;
  }
}

type RpcReply =
  | { ok: true; result: unknown }
  | { ok: false; code: number; message: string; data?: unknown };

/** Issue a raw RPC call; resolves with `result` or throws RpcError. */
export async function rpcCall<T = unknown>(
  method: string,
  params?: Record<string, unknown>,
): Promise<T> {
  const reply = (await window.vc.rpc.call(method, params)) as RpcReply;
  if (reply.ok) return reply.result as T;
  throw new RpcError(reply.code, reply.message, reply.data);
}

// ── Typed payloads (kept in step with core_rpc/methods/*) ─────────────────────

export interface ProjectBrief {
  folder: string;
  name: string;
  meta?: Record<string, unknown> | null;
}

/** A registered creation type for the 创作 [+] menu (project.list_creation_types). */
export interface CreationTypeInfo {
  type_name: string;
  single_instance: boolean;
  description_zh: string;
  description_en: string;
}

export interface SlotState {
  slot_id: string;
  is_locked: boolean;
  is_filled: boolean;
  summary: string;
}

/** A creation component instance. id/kind are structural; the rest is style. */
export interface Component {
  id: string;
  kind: string;
  enabled?: boolean;
  [key: string]: unknown;
}

/** One clip in a render plan (creation.plan_render). */
export interface RenderPlanClip {
  srcIdx: number;
  outIdx: number;
  outputPath: string;
  startSec: number;
  endSec: number;
  cropRect: { x: number; y: number; w: number; h: number } | null;
}

/** Render plan for the selected candidates (output paths + global geometry). */
export interface RenderPlan {
  lang: string;
  mode: "reframe" | "passthrough";
  aspect: string;
  shortEdge: number;
  instanceDir: string;
  clips: RenderPlanClip[];
}

/** Clip preset listing (creation.list_presets). */
export interface PresetList {
  names: string[];
  builtins: string[];
  lastUsed: string;
}

/** A persisted rendered output (config.rendered[]). */
export interface RenderedClip {
  file: string;
  source_clip_idx: number;
  output_index: number;
  duration_sec: number;
  rendered_at: string;
}

// ── Method stubs (the bound read-only surface; mutations land in later slices) ─

export const rpc = {
  ping: () =>
    rpcCall<{ ok: boolean; protocol: number; has_project: boolean }>("system.ping"),
  echo: (params: Record<string, unknown>) => rpcCall<Record<string, unknown>>("system.echo", params),

  recentList: () => rpcCall<ProjectBrief[]>("project.recent_list"),
  openProject: (folder: string) => rpcCall<ProjectBrief>("project.open", { folder }),
  closeProject: () => rpcCall<{ closed: boolean }>("project.close"),
  currentProject: () => rpcCall<ProjectBrief | null>("project.current"),
  listMaterials: () => rpcCall<Record<string, string[]>>("project.list_materials"),
  listCreations: () => rpcCall<Record<string, string[]>>("project.list_creations"),
  // Registered creation types for the 创作 [+] menu (user-facing descriptions —
  // the renderer must not show the raw type_name).
  listCreationTypes: () =>
    rpcCall<CreationTypeInfo[]>("project.list_creation_types"),
  // Create a new creation instance; name omitted → auto-numbered. Returns the
  // created {type, instance}.
  createCreationInstance: (type: string, name?: string) =>
    rpcCall<{ type: string; instance: string }>("project.create_creation_instance", {
      type,
      ...(name ? { name } : {}),
    }),

  slotReadiness: (type: string, instance: string) =>
    rpcCall<Record<string, SlotState>>("material.slot_readiness", { type, instance }),
  getArtifact: (type: string, instance: string, key: string) =>
    rpcCall<string | null>("material.get_artifact", { type, instance, key }),

  loadConfig: (type: string, instance: string) =>
    rpcCall<Record<string, unknown>>("creation.load_config", { type, instance }),
  // Bind a material instance to the creation (ADR-0005). A new-arch creation is
  // created unbound; this is how it gets its source. Returns the updated config.
  bindMaterial: (
    type: string,
    instance: string,
    materialType: string,
    materialInstance: string,
  ) =>
    rpcCall<Record<string, unknown>>("creation.bind_material", {
      type,
      instance,
      material_type: materialType,
      material_instance: materialInstance,
    }),
  listComponents: (type: string, instance: string) =>
    rpcCall<Component[]>("creation.list_components", { type, instance }),
  updateComponent: (
    type: string,
    instance: string,
    componentId: string,
    patch: Record<string, unknown>,
  ) =>
    rpcCall<Component>("creation.update_component", {
      type,
      instance,
      component_id: componentId,
      patch,
    }),
  // Patch top-level config fields (output geometry, selection, per-candidate
  // overrides via clips_overrides_merge). Returns the updated config dict.
  updateConfig: (type: string, instance: string, patch: Record<string, unknown>) =>
    rpcCall<Record<string, unknown>>("creation.update_config", { type, instance, patch }),
  // Per-creation preview inputs; the shape is owned by the matching TS assembler
  // (clip → ClipPreviewData), so it's opaque here.
  previewData: (type: string, instance: string) =>
    rpcCall<unknown>("creation.preview_data", { type, instance }),

  // Component list management ([+ Add] menu / remove / reorder). add/remove/move
  // return the updated component list (list order = z-order).
  listAddableComponents: (type: string, instance: string) =>
    rpcCall<{ kind: string; multi_instance: boolean }[]>("creation.list_addable_components", {
      type,
      instance,
    }),
  addComponent: (type: string, instance: string, kind: string) =>
    rpcCall<Component[]>("creation.add_component", { type, instance, kind }),
  removeComponent: (type: string, instance: string, componentId: string) =>
    rpcCall<Component[]>("creation.remove_component", { type, instance, component_id: componentId }),
  moveComponent: (type: string, instance: string, componentId: string, delta: number) =>
    rpcCall<Component[]>("creation.move_component", {
      type,
      instance,
      component_id: componentId,
      delta,
    }),

  // Material-artifact imports (provider-defined shape). list_imports reports what
  // the bound material offers; import_resource snapshots one into a component and
  // returns the updated component. news_desk: subtitle SRT + chapter schedule.
  listImports: (type: string, instance: string) =>
    rpcCall<{ subtitleLangs: string[]; analyses: string[] }>("creation.list_imports", {
      type,
      instance,
    }),
  importResource: (
    type: string,
    instance: string,
    componentId: string,
    params: Record<string, unknown>,
  ) =>
    rpcCall<Component>("creation.import_resource", {
      type,
      instance,
      component_id: componentId,
      params,
    }),

  // Render orchestration. plan_render returns output paths + geometry for the
  // selected candidates; the renderer encodes each to outputPath, writes it via
  // window.vc.writeFile, then commit_render records it (sidecar JSON + rendered[]).
  planRender: (type: string, instance: string) =>
    rpcCall<RenderPlan>("creation.plan_render", { type, instance }),
  commitRender: (
    type: string,
    instance: string,
    srcIdx: number,
    outIdx: number,
    durationSec: number,
  ) =>
    rpcCall<RenderedClip[]>("creation.commit_render", {
      type,
      instance,
      src_idx: srcIdx,
      out_idx: outIdx,
      duration_sec: durationSec,
    }),
  deleteRender: (type: string, instance: string, outIdx: number) =>
    rpcCall<RenderedClip[]>("creation.delete_render", { type, instance, out_idx: outIdx }),

  // Presets (Style-tab toolbar). apply returns the updated config; save/delete
  // return the updated preset list.
  listPresets: (type: string, instance: string) =>
    rpcCall<PresetList>("creation.list_presets", { type, instance }),
  applyPreset: (type: string, instance: string, name: string) =>
    rpcCall<Record<string, unknown>>("creation.apply_preset", { type, instance, name }),
  savePreset: (type: string, instance: string, name: string) =>
    rpcCall<PresetList>("creation.save_preset", { type, instance, name }),
  deletePreset: (type: string, instance: string, name: string) =>
    rpcCall<PresetList>("creation.delete_preset", { type, instance, name }),

  /** Subscribe to server→client notifications; returns an unsubscribe fn. */
  onNotification: (cb: (method: string, params: unknown) => void): (() => void) =>
    window.vc.rpc.onNotification(cb),
};
