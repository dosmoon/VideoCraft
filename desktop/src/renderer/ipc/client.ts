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

  slotReadiness: (type: string, instance: string) =>
    rpcCall<Record<string, SlotState>>("material.slot_readiness", { type, instance }),
  getArtifact: (type: string, instance: string, key: string) =>
    rpcCall<string | null>("material.get_artifact", { type, instance, key }),

  loadConfig: (type: string, instance: string) =>
    rpcCall<Record<string, unknown>>("creation.load_config", { type, instance }),
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
  // Per-creation preview inputs; the shape is owned by the matching TS assembler
  // (clip → ClipPreviewData), so it's opaque here.
  previewData: (type: string, instance: string) =>
    rpcCall<unknown>("creation.preview_data", { type, instance }),

  /** Subscribe to server→client notifications; returns an unsubscribe fn. */
  onNotification: (cb: (method: string, params: unknown) => void): (() => void) =>
    window.vc.rpc.onNotification(cb),
};
