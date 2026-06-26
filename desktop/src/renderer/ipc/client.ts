/**
 * Renderer-side RPC client — a thin typed wrapper over window.vc.rpc.
 *
 * The Python sidecar is the single owner of project/material state; the
 * renderer is a thin client (migration doc §2.3). This module unwraps the
 * tagged reply main forwards (`{ok:true,result}` | `{ok:false,...}`) back into
 * a resolved value or a thrown RpcError, and exposes typed method stubs for
 * the bound RPC surface.
 *
 * ADR-0008 (Phase A4): clip config/preset/render is now owned by TS. The
 * creation.* methods below dispatch `type === "clip"` to `clipBackend` (which
 * loads the TS ClipConfigOwner + render.ts and persists via window.vc.fs);
 * news_desk stays on the Python sidecar until A5. This whole dispatch goes away
 * at A6 when the generic creation.* RPCs are retired.
 */

import { clipBackend } from "@creations/clip/clientBackend.js";
import { newsDeskBackend } from "@creations/news_desk/clientBackend.js";
import { materialBackend } from "@materials/news_video/clientBackend.js";
import type { SlotId, SlotState } from "@materials/news_video/model.js";

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

// Renderer-local notification bus (ADR-0008 B3.2). TS-side material mutations go
// through capability.*, which emits NO domain events (it is plugin-agnostic), so
// the TS owner fires the same `event.material.changed` the Python sidecar used to
// emit. `onNotification` below merges this local stream with the server stream, so
// existing subscribers (the Hub sidebar) receive both with zero change.
const localListeners = new Set<(method: string, params: unknown) => void>();

export function emitLocal(method: string, params: unknown): void {
  for (const cb of [...localListeners]) {
    try {
      cb(method, params);
    } catch {
      /* a listener error must not break the bus */
    }
  }
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
  mode: "reframe" | "letterbox" | "passthrough";
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

/** One preset language for the ASR/translate/import picker (system.list_languages). */
export interface KnownLanguage {
  iso: string;
  display: string; // "en — English (英语)"
}

// ── AI console (ai.* domain) ──────────────────────────────────────────────────

export type AiDeployTier = "local" | "free_online" | "aistack" | "cloud";
export type AiCategory = "llm" | "asr" | "tts";
export type AiKeyState = "cli" | "no_key_needed" | "not_configured" | "empty" | "ok";

export interface AiKeyStatus {
  state: AiKeyState;
  masked: string | null;
}

/** One provider row, normalized by core.ai.console_view (UI-free enums). */
export interface AiProvider {
  name: string;
  category: AiCategory;
  deploy_tier: AiDeployTier;
  type: string;
  enabled: boolean;
  needs_key: boolean;
  has_auth: boolean;
  key_status: AiKeyStatus;
  base_url: string;
  models: string[];
  // Editable per-provider extras present on this provider (timeouts, executable…).
  settings: Record<string, string | number>;
}

/** A routing-matrix row (task). label is "中文 / English" from the engine. */
export interface AiTask {
  id: string;
  category: AiCategory;
  label: string;
}

export interface AiRoutingCell {
  provider: string;
  model: string;
}

/** Full read-only AI console state (ai.snapshot). */
export interface AiSnapshot {
  tasks: AiTask[];
  routing_tiers: { llm: string[]; non_llm: string[] };
  task_routing: Record<string, AiRoutingCell>;
  task_tier_prefs: Record<string, Record<string, AiRoutingCell>>;
  providers: { llm: AiProvider[]; asr: AiProvider[]; tts: AiProvider[] };
  aistack: {
    base_url: string;
    enabled: boolean;
    models_cache: { llm: string[]; asr: string[]; tts: string[] };
  };
}

/** One TTS voice from a provider's catalog (ai.tts_voices → VoicePickerDialog). */
export interface TtsVoice {
  provider: string;
  voice_id: string;
  display_name: string;
  language: string; // BCP-47, e.g. "zh-CN"
  gender: string; // "F" | "M" | ""
  tags: string[];
  description: string;
}

/** Catalog freshness metadata (ai.tts_voices). */
export interface TtsVoiceMeta {
  count: number;
  last_refresh_ts: number;
  has_cache: boolean;
}

/** Per-provider call counters (ai.stats / Stats tab). */
export interface AiStatsEntry {
  calls: number;
  errors: number;
  last_used?: string | null;
  last_error?: string | null;
}

// ── Local model manager (models.* domain) ─────────────────────────────────────

/** One downloadable model with disk-only installed state (models.catalog). */
export interface ModelCatalogEntry {
  id: string;
  name: string;
  capability: string; // asr | llm | tts | vad
  tier: string; // first | recommended
  recommended_for: string; // cpu | gpu | both
  description: string;
  dir: string;
  installed: boolean;
  present: number;
  total: number;
}

/** A download job (models.jobs + live `event.models` pushes). */
export interface ModelJob {
  job_id: string;
  model_id: string;
  state: "queued" | "running" | "done" | "failed" | "cancelled";
  bytes_done: number;
  bytes_total: number;
  fraction: number;
  bytes_per_sec: number;
  eta_sec: number | null;
  current_file: string;
  error: string;
}

// ── Environment dashboard (env.* domain) ──────────────────────────────────────

/** A managed external dependency (env.components — metadata only). */
export interface EnvComponentMeta {
  id: string;
  category: string; // binary | python
  installable: boolean;
  info_url: string | null;
}

/** Detection result for one component (env.detect_all). */
export interface EnvDetect {
  id: string;
  available: boolean;
  version: string | null;
  source: string | null; // system | managed | pip
  path: string | null;
}

/** CUDA runtime + GPU status (gpu.status). */
export interface GpuStatus {
  installed: boolean; // CUDA pip wheels present
  available: boolean; // CUDA actually usable (wheels + driver)
  device_name: string;
  driver: string;
  vram_mb: number;
  wheel: string;
  reason: string;
}

/** Embedded-AI runtime status (embedded_ai.status). */
export interface EmbeddedAiStatus {
  installed: boolean; // faster-whisper + llama-cpp present in py-extra
}

/** A registered material type for the 素材 [+] menu (project.list_material_types_info). */
export interface MaterialTypeInfo {
  type_name: string;
  single_instance: boolean;
  description_zh: string;
  description_en: string;
}

/** The 15-field AI-corrected news context (material.read_context). All present. */
export interface SourceContext {
  host: string;
  host_bio: string;
  event_date: string;
  event_location: string;
  episode_topic: string;
  host_affiliation: string;
  guests: string;
  event_time: string;
  show_type: string;
  event_summary: string;
  key_points: string;
  background: string;
  audience: string;
  platform_tone: string;
  notes: string;
}

/** The 5 user-hint anchor fields seeding AI fill (material.read_basic_info). */
export interface SourceBasicInfo {
  host: string;
  host_bio: string;
  event_date: string;
  event_location: string;
  episode_topic: string;
}

/** The Source descriptor + probe values for the Source tab (material.source_meta). */
export interface SourceMeta {
  origin?: string;
  url?: string;
  imported_from?: string;
  title?: string;
  duration_sec?: number;
  width?: number;
  height?: number;
}

/** Subtitle quality-check result (material.check_subtitle). */
export interface SubtitleIssue {
  cue_index: number;
  category: string;
  severity: string;
  severity_class: string;
  message: string;
  auto_fixable: boolean;
}
export interface SubtitleCheck {
  cue_count: number;
  hard: number;
  fixable: number;
  advisory: number;
  issues: SubtitleIssue[];
}

/** One existing analysis artifact across kinds (material.list_analysis_artifacts). */
export interface AnalysisArtifact {
  kind: string;
  format: string; // "json" | "md"
  icon: string;
  display_zh: string;
  size_bytes: number;
}

/** Pre-import summary of an analysis.json (material.analysis_summary). */
export interface AnalysisSummary {
  filename: string;
  chapter_count: number;
  title_count: number;
  start_str: string;
  end_str: string;
  error: string;
}

/** Source-acquisition request (material.set_source). origin link → yt-dlp, local → copy/cut. */
export interface AcquireSource {
  origin: "link" | "local";
  url?: string;
  imported_from?: string;
  // HH:MM:SS / MM:SS time strings (validated server-side); omit for the whole video.
  clip_range?: { start: string; end: string } | null;
  title?: string;
}

// ADR-0008 terminal state: the three plugins (clip / news_desk / news_video) run
// entirely TS-side, so the creation.*/material.* dispatch below routes every known
// type to its TS backend. An unknown type is a programming error (the type-picker
// only offers the registered three) — these throw rather than hit a now-deleted
// Python RPC. Returning `never` keeps the dispatch ternaries well-typed.
function unsupportedCreation(type: string): never {
  throw new RpcError(-32602, `unsupported creation type: ${type}`);
}
function unsupportedMaterial(type: string): never {
  throw new RpcError(-32602, `unsupported material type: ${type}`);
}

// ── Method stubs (the bound read-only surface; mutations land in later slices) ─

export const rpc = {
  ping: () =>
    rpcCall<{ ok: boolean; protocol: number; has_project: boolean }>("system.ping"),
  echo: (params: Record<string, unknown>) => rpcCall<Record<string, unknown>>("system.echo", params),
  // Preset language catalog for the ASR/translate/import combobox pickers.
  listLanguages: () => rpcCall<KnownLanguage[]>("system.list_languages"),
  // UI language ("zh" | "en") from the shared user_data/settings.json — the
  // renderer awaits this at boot and sets its tr() singleton before first render.
  getLocale: () => rpcCall<{ lang: string }>("system.get_locale"),
  // Persist the UI language back to settings.json (the renderer switches hot on
  // its own; this keeps it across restart and in sync with the Tk app).
  setLocale: (lang: string) => rpcCall<{ lang: string }>("system.set_locale", { lang }),

  // ── AI console (ai.* domain) ───────────────────────────────────────────────
  // Read: full console state + per-provider call stats (refreshed separately).
  aiSnapshot: () => rpcCall<AiSnapshot>("ai.snapshot"),
  aiStats: () => rpcCall<Record<string, AiStatsEntry>>("ai.stats"),
  // Voice catalog for the VoicePickerDialog. refresh=true forces a network
  // re-fetch (else cached, auto-fetched once when no cache exists).
  ttsVoices: (provider: string, refresh = false) =>
    rpcCall<{ voices: TtsVoice[]; meta: TtsVoiceMeta }>("ai.tts_voices", { provider, refresh }),
  // Writes: each persists (sidecar) and returns a fresh snapshot to re-sync.
  aiSetKey: (provider: string, category: AiCategory, key: string) =>
    rpcCall<AiSnapshot>("ai.set_key", { provider, category, key }),
  aiSetProviderEnabled: (provider: string, category: AiCategory, enabled: boolean) =>
    rpcCall<AiSnapshot>("ai.set_provider_enabled", { provider, category, enabled }),
  aiSetRouting: (task: string, provider: string, model: string) =>
    rpcCall<AiSnapshot>("ai.set_routing", { task, provider, model }),
  aiSetTierPref: (task: string, tier: string, provider: string, model: string) =>
    rpcCall<AiSnapshot>("ai.set_tier_pref", { task, tier, provider, model }),
  aiSetAistackGateway: (baseUrl: string, enabled: boolean) =>
    rpcCall<AiSnapshot>("ai.set_aistack_gateway", { base_url: baseUrl, enabled }),
  // Patch a provider's config (base_url / models / settings). Whitelisted keys
  // only (server-side); the API key has its own path (aiSetKey).
  aiUpdateProvider: (provider: string, category: AiCategory, patch: Record<string, unknown>) =>
    rpcCall<AiSnapshot>("ai.update_provider", { provider, category, patch }),
  // Network actions — jobs (consume via runJob). The terminal event carries the
  // result: test_provider → {ok, reply}; test_aistack → {buckets, total};
  // refresh_models → {models}.
  aiTestProvider: (provider: string, category: AiCategory, model?: string) =>
    rpcCall<{ job_id: string }>("ai.test_provider", {
      provider,
      category,
      ...(model ? { model } : {}),
    }),
  aiTestAistack: (baseUrl: string) =>
    rpcCall<{ job_id: string }>("ai.test_aistack", { base_url: baseUrl }),
  aiRefreshModels: (provider: string, category: AiCategory) =>
    rpcCall<{ job_id: string }>("ai.refresh_models", { provider, category }),

  // ── Local model manager (models.* domain) ──────────────────────────────────
  // Catalog (disk-only installed state) + current jobs; download/cancel/remove.
  // Live download progress arrives via the `event.models` notification.
  modelsCatalog: () => rpcCall<ModelCatalogEntry[]>("models.catalog"),
  modelsJobs: () => rpcCall<ModelJob[]>("models.jobs"),
  modelsDownload: (modelId: string) =>
    rpcCall<{ job_id: string }>("models.download", { model_id: modelId }),
  modelsCancel: (jobId: string) => rpcCall<{ ok: boolean }>("models.cancel", { job_id: jobId }),
  modelsRemove: (modelId: string) => rpcCall<{ freed: number }>("models.remove", { model_id: modelId }),
  // Models root dir (default <repo>/user_data/models) + override.
  modelsRootDir: () => rpcCall<{ dir: string }>("models.root_dir"),
  modelsSetRootDir: (path: string) => rpcCall<{ dir: string }>("models.set_root_dir", { path }),
  // GPU / CUDA runtime — all jobs (nvidia-smi / pip). status terminal = GpuStatus;
  // install/uninstall stream pip log via progress.gpu.<action> (field `line`).
  gpuStatus: () => rpcCall<{ job_id: string }>("gpu.status"),
  gpuInstall: () => rpcCall<{ job_id: string }>("gpu.install"),
  gpuUninstall: () => rpcCall<{ job_id: string }>("gpu.uninstall"),
  // Embedded-AI runtime (faster-whisper + llama-cpp) — opt-in install into
  // py-extra. All jobs; install/uninstall stream pip log via
  // progress.embedded_ai.<action> (field `line`). status terminal = EmbeddedAiStatus.
  embeddedAiStatus: () => rpcCall<{ job_id: string }>("embedded_ai.status"),
  embeddedAiInstall: () => rpcCall<{ job_id: string }>("embedded_ai.install"),
  embeddedAiUninstall: () => rpcCall<{ job_id: string }>("embedded_ai.uninstall"),

  // ── Environment dashboard (env.* domain) ────────────────────────────────────
  // Component metadata (sync) + detection/install jobs (subprocess/pip → off-thread).
  envComponents: () => rpcCall<EnvComponentMeta[]>("env.components"),
  envDetectAll: () => rpcCall<{ job_id: string }>("env.detect_all"),
  envInstall: (componentId: string) => rpcCall<{ job_id: string }>("env.install", { component_id: componentId }),

  recentList: () => rpcCall<ProjectBrief[]>("project.recent_list"),
  openProject: (folder: string) => rpcCall<ProjectBrief>("project.open", { folder }),
  // Create a fresh project under parent_dir/name (scaffolds the skeleton + makes
  // it current). A duplicate folder / bad name throws RpcError with
  // data.reason ∈ {exists, invalid_name} so the launcher can localize.
  newProject: (parentDir: string, name: string) =>
    rpcCall<ProjectBrief>("project.new", { parent_dir: parentDir, name }),
  closeProject: () => rpcCall<{ closed: boolean }>("project.close"),
  currentProject: () => rpcCall<ProjectBrief | null>("project.current"),
  listMaterials: () => rpcCall<Record<string, string[]>>("project.list_materials"),
  listCreations: () => rpcCall<Record<string, string[]>>("project.list_creations"),
  // Abs path of a creation instance dir — the TS config owner needs it to
  // read/write config.json + render outputs via window.vc.fs (ADR-0008).
  creationInstanceDir: (type: string, instance: string) =>
    rpcCall<string>("project.creation_instance_dir", { type, instance }),
  // Abs path of a material instance dir — symmetric to creationInstanceDir; the
  // TS material model needs it to read/write context/subtitles via window.vc.fs.
  materialInstanceDir: (type: string, instance: string) =>
    rpcCall<string>("project.material_instance_dir", { type, instance }),
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

  // Rename / delete a material|creation instance (the dir is the instance name).
  renameInstance: (kind: "material" | "creation", type: string, instance: string, newName: string) =>
    rpcCall<{ type: string; instance: string }>("project.rename_instance", {
      kind,
      type,
      instance,
      new_name: newName,
    }),
  deleteInstance: (kind: "material" | "creation", type: string, instance: string) =>
    rpcCall<{ ok: boolean }>("project.delete_instance", { kind, type, instance }),

  // news_video (the only material type) → TS structured readiness; the data layer
  // emits facts (isFilled/isLocked + source/context/subtitle descriptors), the UI
  // formats any summary via tr().
  slotReadiness: (type: string, instance: string): Promise<Record<SlotId, SlotState>> =>
    type === "news_video" ? materialBackend.slotReadinessStructured(instance) : unsupportedMaterial(type),
  getArtifact: (type: string, instance: string, key: string) =>
    type === "news_video" ? materialBackend.getArtifact(instance, key) : unsupportedMaterial(type),

  loadConfig: (type: string, instance: string) =>
    type === "clip"
      ? clipBackend.loadConfig(instance)
      : type === "news_desk"
        ? newsDeskBackend.loadConfig(instance)
        : unsupportedCreation(type),
  // Bind a material instance to the creation (ADR-0005). A new-arch creation is
  // created unbound; this is how it gets its source. Returns the updated config.
  bindMaterial: (
    type: string,
    instance: string,
    materialType: string,
    materialInstance: string,
  ) =>
    type === "clip"
      ? clipBackend.bindMaterial(instance, materialType, materialInstance)
      : type === "news_desk"
        ? newsDeskBackend.bindMaterial(instance, materialType, materialInstance)
        : unsupportedCreation(type),
  listComponents: (type: string, instance: string) =>
    type === "clip"
      ? clipBackend.listComponents(instance)
      : type === "news_desk"
        ? newsDeskBackend.listComponents(instance)
        : unsupportedCreation(type),
  updateComponent: (
    type: string,
    instance: string,
    componentId: string,
    patch: Record<string, unknown>,
  ) =>
    type === "clip"
      ? clipBackend.updateComponent(instance, componentId, patch)
      : type === "news_desk"
        ? newsDeskBackend.updateComponent(instance, componentId, patch)
        : unsupportedCreation(type),
  // Patch top-level config fields (output geometry, selection, per-candidate
  // overrides via clips_overrides_merge). Returns the updated config dict.
  updateConfig: (type: string, instance: string, patch: Record<string, unknown>) =>
    type === "clip"
      ? clipBackend.updateConfig(instance, patch)
      : type === "news_desk"
        ? newsDeskBackend.updateConfig(instance, patch)
        : unsupportedCreation(type),
  // Per-creation preview inputs; the shape is owned by the matching TS assembler
  // (clip → ClipPreviewData), so it's opaque here.
  previewData: (type: string, instance: string) =>
    type === "clip"
      ? clipBackend.previewData(instance)
      : type === "news_desk"
        ? newsDeskBackend.previewData(instance)
        : unsupportedCreation(type),

  // Component list management ([+ Add] menu / remove / reorder). add/remove/move
  // return the updated component list (list order = z-order).
  listAddableComponents: (type: string, _instance: string) =>
    type === "clip"
      ? clipBackend.listAddableComponents()
      : type === "news_desk"
        ? newsDeskBackend.listAddableComponents()
        : unsupportedCreation(type),
  addComponent: (type: string, instance: string, kind: string) =>
    type === "clip"
      ? clipBackend.addComponent(instance, kind)
      : type === "news_desk"
        ? newsDeskBackend.addComponent(instance, kind)
        : unsupportedCreation(type),
  removeComponent: (type: string, instance: string, componentId: string) =>
    type === "clip"
      ? clipBackend.removeComponent(instance, componentId)
      : type === "news_desk"
        ? newsDeskBackend.removeComponent(instance, componentId)
        : unsupportedCreation(type),
  moveComponent: (type: string, instance: string, componentId: string, delta: number) =>
    type === "clip"
      ? clipBackend.moveComponent(instance, componentId, delta)
      : type === "news_desk"
        ? newsDeskBackend.moveComponent(instance, componentId, delta)
        : unsupportedCreation(type),

  // Material-artifact imports (provider-defined shape). list_imports reports what
  // the bound material offers; import_resource snapshots one into a component and
  // returns the updated component. news_desk: subtitle SRT + chapter schedule.
  listImports: (type: string, instance: string) =>
    type === "news_desk" ? newsDeskBackend.listImports(instance) : unsupportedCreation(type),
  importResource: (
    type: string,
    instance: string,
    componentId: string,
    params: Record<string, unknown>,
  ) =>
    type === "news_desk"
      ? newsDeskBackend.importResource(instance, componentId, params)
      : type === "clip"
        ? clipBackend.importResource(instance, componentId, params)
        : unsupportedCreation(type),

  // Render orchestration. plan_render returns output paths + geometry for the
  // selected candidates; the renderer encodes each to outputPath, writes it via
  // window.vc.writeFile, then commit_render records it (sidecar JSON + rendered[]).
  planRender: (type: string, instance: string) =>
    type === "clip"
      ? clipBackend.planRender(instance)
      : type === "news_desk"
        ? newsDeskBackend.planRender(instance)
        : unsupportedCreation(type),
  commitRender: (
    type: string,
    instance: string,
    srcIdx: number,
    outIdx: number,
    durationSec: number,
  ) =>
    type === "clip"
      ? clipBackend.commitRender(instance, srcIdx, outIdx, durationSec)
      : type === "news_desk"
        ? newsDeskBackend.commitRender(instance, srcIdx, outIdx, durationSec)
        : unsupportedCreation(type),
  deleteRender: (type: string, instance: string, outIdx: number) =>
    type === "clip"
      ? clipBackend.deleteRender(instance, outIdx)
      : type === "news_desk"
        ? newsDeskBackend.deleteRender(instance, outIdx)
        : unsupportedCreation(type),

  // Presets (Style-tab toolbar). apply returns the updated config; save/delete
  // return the updated preset list.
  listPresets: (type: string, instance: string) =>
    type === "clip"
      ? clipBackend.listPresets(instance)
      : type === "news_desk"
        ? newsDeskBackend.listPresets(instance)
        : unsupportedCreation(type),
  applyPreset: (type: string, instance: string, name: string) =>
    type === "clip"
      ? clipBackend.applyPreset(instance, name)
      : type === "news_desk"
        ? newsDeskBackend.applyPreset(instance, name)
        : unsupportedCreation(type),
  savePreset: (type: string, instance: string, name: string) =>
    type === "clip"
      ? clipBackend.savePreset(instance, name)
      : type === "news_desk"
        ? newsDeskBackend.savePreset(instance, name)
        : unsupportedCreation(type),
  deletePreset: (type: string, instance: string, name: string) =>
    type === "clip"
      ? clipBackend.deletePreset(instance, name)
      : type === "news_desk"
        ? newsDeskBackend.deletePreset(instance, name)
        : unsupportedCreation(type),

  // ── Material side (素材) ───────────────────────────────────────────────────
  // Registered material types for the 素材 [+] menu (descriptions, never the raw
  // type_name). Create returns the new {type, instance}; name omitted → auto.
  listMaterialTypes: () =>
    rpcCall<MaterialTypeInfo[]>("project.list_material_types_info"),
  createMaterialInstance: (type: string, name?: string) =>
    rpcCall<{ type: string; instance: string }>("project.create_material_instance", {
      type,
      ...(name ? { name } : {}),
    }),

  // Source descriptor + probe values for the Source tab (null fields until set).
  materialSourceMeta: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.materialSourceMeta(instance) : unsupportedMaterial(type),

  // News context (15 fields) + basic_info seed (5 fields). write_* persist the
  // whole dict (server normalizes) and return the stored value.
  readContext: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.readContext(instance) : unsupportedMaterial(type),
  writeContext: (type: string, instance: string, context: SourceContext) =>
    type === "news_video" ? materialBackend.writeContext(instance, context) : unsupportedMaterial(type),
  readBasicInfo: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.readBasicInfo(instance) : unsupportedMaterial(type),
  writeBasicInfo: (type: string, instance: string, basicInfo: SourceBasicInfo) =>
    type === "news_video" ? materialBackend.writeBasicInfo(instance, basicInfo) : unsupportedMaterial(type),
  contextCompletion: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.contextCompletion(instance) : unsupportedMaterial(type),

  // Subtitles + analyses (read). list_subtitle_languages → ISO codes with an SRT;
  // list_analyses → analysis.json filenames; analysis_summary → per-file preview;
  // read_analysis → the raw envelope (chapter editor source of truth).
  listSubtitleLanguages: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.listSubtitleLanguages(instance) : unsupportedMaterial(type),
  // SRT text for the in-tab viewer; quality check + one-click auto-fix.
  readSubtitle: (type: string, instance: string, lang: string) =>
    type === "news_video" ? materialBackend.readSubtitle(instance, lang) : unsupportedMaterial(type),
  checkSubtitle: (type: string, instance: string, lang: string) =>
    type === "news_video" ? materialBackend.checkSubtitle(instance, lang) : unsupportedMaterial(type),
  quickFixSubtitle: (type: string, instance: string, lang: string) =>
    type === "news_video" ? materialBackend.quickFixSubtitle(instance, lang) : unsupportedMaterial(type),
  // Import an external .srt from disk (path from window.vc.pickSubtitle).
  importSubtitle: (type: string, instance: string, path: string, lang: string) =>
    type === "news_video" ? materialBackend.importSubtitle(instance, path, lang) : unsupportedMaterial(type),
  // Existing analysis artifacts across all kinds + raw text of one (md/json viewer).
  listAnalysisArtifacts: (type: string, instance: string, lang: string) =>
    type === "news_video" ? materialBackend.listAnalysisArtifacts(instance, lang) : unsupportedMaterial(type),
  readAnalysisText: (type: string, instance: string, lang: string, kind: string) =>
    type === "news_video" ? materialBackend.readAnalysisText(instance, lang, kind) : unsupportedMaterial(type),
  listAnalyses: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.listAnalyses(instance) : unsupportedMaterial(type),
  analysisSummary: (type: string, instance: string, filename: string) =>
    type === "news_video" ? materialBackend.analysisSummary(instance, filename) : unsupportedMaterial(type),
  // Absolute path of a dubbing track's audio file (news_video only) — feed to
  // window.vc.mediaUrl() to play it in the dub detail view.
  dubAudioPath: (type: string, instance: string, lang: string) =>
    type === "news_video" ? materialBackend.dubAudioPath(instance, lang) : unsupportedMaterial(type),
  readAnalysis: (type: string, instance: string, filename: string) =>
    type === "news_video" ? materialBackend.readAnalysis(instance, filename) : unsupportedMaterial(type),
  // Re-save an analysis.json after editing the chapter schedule; server
  // normalizes (sort / end=next.start / drop degenerate / synth 00:00) and
  // returns the normalized envelope.
  saveChapters: (
    type: string,
    instance: string,
    filename: string,
    chapters: Record<string, unknown>[],
    lang: string,
  ) =>
    type === "news_video"
      ? materialBackend.saveChapters(instance, filename, chapters, lang)
      : unsupportedMaterial(type),

  // Project-meta writes the TS material backend calls after capability jobs
  // (which are plugin-agnostic and touch no project meta): persist the acquired
  // source descriptor + the ASR-detected / translated languages (ADR-0008 B3.2).
  commitSource: (source: AcquireSource, probe: { title?: string; durationSec?: number; width?: number; height?: number }) =>
    rpcCall<SourceMeta>("project.commit_source", {
      source,
      ...(probe.title ? { title: probe.title } : {}),
      ...(probe.durationSec != null ? { duration_sec: probe.durationSec } : {}),
      ...(probe.width != null ? { width: probe.width } : {}),
      ...(probe.height != null ? { height: probe.height } : {}),
    }),
  setSourceLanguage: (lang: string) =>
    rpcCall<{ source: string }>("project.set_source_language", { lang }),
  addTranslatedLanguage: (lang: string) =>
    rpcCall<{ translated_to: string[] }>("project.add_translated_language", { lang }),

  // Long-running material jobs (sidecar threads). Each returns {job_id}
  // immediately; consume progress/terminal via runJob (ipc/runJob.ts).
  startSetSource: (type: string, instance: string, source: AcquireSource) =>
    type === "news_video" ? materialBackend.startSetSource(instance, source) : unsupportedMaterial(type),
  startRunAsr: (type: string, instance: string, sourceLang?: string) =>
    type === "news_video" ? materialBackend.startRunAsr(instance, sourceLang) : unsupportedMaterial(type),
  // sourceLang (news_video only): translate FROM this language's SRT instead of the
  // project source — lets each subtitle node offer "translate from itself". Defaults
  // to the project source when omitted.
  startRunTranslate: (type: string, instance: string, targetLang: string, sourceLang?: string) =>
    type === "news_video"
      ? materialBackend.startRunTranslate(instance, targetLang, sourceLang)
      : unsupportedMaterial(type),
  startRunAnalysis: (type: string, instance: string, lang: string, analysisKind: string) =>
    type === "news_video"
      ? materialBackend.startRunAnalysis(instance, lang, analysisKind)
      : unsupportedMaterial(type),
  // Synthesize a dubbing track from a subtitle (news_video only). provider/voiceId
  // come from the VoicePickerDialog; options carries tuning (max_speed, …).
  startTtsDub: (
    type: string,
    instance: string,
    lang: string,
    provider: string,
    voiceId: string,
    options?: Record<string, unknown>,
  ) =>
    type === "news_video"
      ? materialBackend.startTtsDub(instance, lang, provider, voiceId, options)
      : unsupportedMaterial(type),
  // news_video → generic capability.llm_extract (plugin builds the prompt); the
  // job result is the raw 15-field dict, which the caller persists via writeContext
  // (capability does not write context.json).
  startAiFillContext: (type: string, instance: string) =>
    type === "news_video" ? materialBackend.startAiFill(instance) : unsupportedMaterial(type),

  // Cancel a running job by id (shared with the creation side; system.py).
  cancelJob: (jobId: string) => rpcCall<{ cancelled: boolean }>("job.cancel", { job_id: jobId }),

  /** Subscribe to notifications; returns an unsubscribe fn. Merges the server
   * stream with the renderer-local bus (emitLocal) so TS-side material mutations
   * reach existing subscribers (e.g. the Hub sidebar) without any extra wiring. */
  onNotification: (cb: (method: string, params: unknown) => void): (() => void) => {
    const offServer = window.vc.rpc.onNotification(cb);
    localListeners.add(cb);
    return () => {
      offServer();
      localListeners.delete(cb);
    };
  },
};
