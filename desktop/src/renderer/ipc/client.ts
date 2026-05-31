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

/** One preset language for the ASR/translate/import picker (system.list_languages). */
export interface KnownLanguage {
  iso: string;
  display: string; // "en — English (英语)"
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

// ── Method stubs (the bound read-only surface; mutations land in later slices) ─

export const rpc = {
  ping: () =>
    rpcCall<{ ok: boolean; protocol: number; has_project: boolean }>("system.ping"),
  echo: (params: Record<string, unknown>) => rpcCall<Record<string, unknown>>("system.echo", params),
  // Preset language catalog for the ASR/translate/import combobox pickers.
  listLanguages: () => rpcCall<KnownLanguage[]>("system.list_languages"),

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
    rpcCall<SourceMeta>("material.source_meta", { type, instance }),

  // News context (15 fields) + basic_info seed (5 fields). write_* persist the
  // whole dict (server normalizes) and return the stored value.
  readContext: (type: string, instance: string) =>
    rpcCall<SourceContext>("material.read_context", { type, instance }),
  writeContext: (type: string, instance: string, context: SourceContext) =>
    rpcCall<SourceContext>("material.write_context", { type, instance, context }),
  readBasicInfo: (type: string, instance: string) =>
    rpcCall<SourceBasicInfo>("material.read_basic_info", { type, instance }),
  writeBasicInfo: (type: string, instance: string, basicInfo: SourceBasicInfo) =>
    rpcCall<SourceBasicInfo>("material.write_basic_info", { type, instance, basic_info: basicInfo }),
  contextCompletion: (type: string, instance: string) =>
    rpcCall<{ filled: number; total: number }>("material.context_completion", { type, instance }),

  // Subtitles + analyses (read). list_subtitle_languages → ISO codes with an SRT;
  // list_analyses → analysis.json filenames; analysis_summary → per-file preview;
  // read_analysis → the raw envelope (chapter editor source of truth).
  listSubtitleLanguages: (type: string, instance: string) =>
    rpcCall<string[]>("material.list_subtitle_languages", { type, instance }),
  // SRT text for the in-tab viewer; quality check + one-click auto-fix.
  readSubtitle: (type: string, instance: string, lang: string) =>
    rpcCall<{ text: string }>("material.read_subtitle", { type, instance, lang }),
  checkSubtitle: (type: string, instance: string, lang: string) =>
    rpcCall<SubtitleCheck>("material.check_subtitle", { type, instance, lang }),
  quickFixSubtitle: (type: string, instance: string, lang: string) =>
    rpcCall<SubtitleCheck>("material.quick_fix_subtitle", { type, instance, lang }),
  // Import an external .srt from disk (path from window.vc.pickSubtitle).
  importSubtitle: (type: string, instance: string, path: string, lang: string) =>
    rpcCall<{ lang: string }>("material.import_subtitle", { type, instance, path, lang }),
  // Existing analysis artifacts across all kinds + raw text of one (md/json viewer).
  listAnalysisArtifacts: (type: string, instance: string, lang: string) =>
    rpcCall<AnalysisArtifact[]>("material.list_analysis_artifacts", { type, instance, lang }),
  readAnalysisText: (type: string, instance: string, lang: string, kind: string) =>
    rpcCall<{ text: string }>("material.read_analysis_text", { type, instance, lang, kind }),
  listAnalyses: (type: string, instance: string) =>
    rpcCall<string[]>("material.list_analyses", { type, instance }),
  analysisSummary: (type: string, instance: string, filename: string) =>
    rpcCall<AnalysisSummary>("material.analysis_summary", { type, instance, filename }),
  readAnalysis: (type: string, instance: string, filename: string) =>
    rpcCall<Record<string, unknown>>("material.read_analysis", { type, instance, filename }),
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
    rpcCall<Record<string, unknown>>("material.save_chapters", {
      type,
      instance,
      filename,
      chapters,
      lang,
    }),

  // Long-running material jobs (sidecar threads). Each returns {job_id}
  // immediately; consume progress/terminal via runJob (ipc/runJob.ts).
  startSetSource: (type: string, instance: string, source: AcquireSource) =>
    rpcCall<{ job_id: string }>("material.set_source", { type, instance, source }),
  startRunAsr: (type: string, instance: string, sourceLang?: string) =>
    rpcCall<{ job_id: string }>("material.run_asr", {
      type,
      instance,
      ...(sourceLang ? { source_lang: sourceLang } : {}),
    }),
  startRunTranslate: (type: string, instance: string, targetLang: string) =>
    rpcCall<{ job_id: string }>("material.run_translate", { type, instance, target_lang: targetLang }),
  startRunAnalysis: (type: string, instance: string, lang: string, analysisKind: string) =>
    rpcCall<{ job_id: string }>("material.run_analysis", {
      type,
      instance,
      lang,
      analysis_kind: analysisKind,
    }),
  startAiFillContext: (type: string, instance: string) =>
    rpcCall<{ job_id: string }>("material.ai_fill_context", { type, instance }),

  // Cancel a running job by id (shared with the creation side; system.py).
  cancelJob: (jobId: string) => rpcCall<{ cancelled: boolean }>("job.cancel", { job_id: jobId }),

  /** Subscribe to server→client notifications; returns an unsubscribe fn. */
  onNotification: (cb: (method: string, params: unknown) => void): (() => void) =>
    window.vc.rpc.onNotification(cb),
};
