/**
 * Clip instance config — single in-memory owner (ADR-0008 TS port of
 * `src/creations/clip/config.py`).
 *
 * The on-disk `config.json` for a clip creation has ONE in-memory owner. All
 * reads/writes funnel through `load()` / `save()` (via the injected `Fs`, which
 * writes through the Electron main process). No other code constructs the dict
 * and writes the file — add a field here if a new one needs to persist.
 *
 * `save()` matches Python `*.save()` byte-for-byte (vc.fs.writeJson = 2-space
 * indent, no trailing newline, raw non-ASCII) so existing config.json is stable.
 * Mutators do NOT auto-save (faithful to config.py — the workbench calls save()
 * after a mutation); preset methods persist the separate preset store.
 */

import type { Fs } from "../../renderer/ipc/fs";
import { ADDABLE, type AddableKind, type ComponentDict, defaultInstance } from "./componentDefs";
import * as presets from "./presets";
import {
  normalizeBitrateMode,
  normalizeEngine,
  normalizeFps,
  normalizeMbps,
  type BitrateMode,
  type ExportEngineChoice,
} from "../exportSettings";

export interface BoundMaterial {
  type_name: string;
  instance_name: string;
  bound_at: string;
}

/** Give every component a unique, non-empty `id` in place (Tk-era dedup). */
function ensureUniqueIds(components: ComponentDict[]): void {
  const seen = new Set<string>();
  for (const c of components) {
    const base = String(c["id"] || c["kind"] || "component");
    let id = base;
    let n = 2;
    while (seen.has(id)) id = `${base}-${n++}`;
    c["id"] = id;
    seen.add(id);
  }
}

export class ClipConfigOwner {
  boundMaterial: BoundMaterial | null = null;
  sourceSubtitle = "";
  selectedClipIndices: number[] = [];
  presetName = "";
  components: ComponentDict[] = [];
  outputAspect = "9:16";
  outputShortEdge = 1080;
  outputMode = "reframe";
  encodePreset = "medium";
  // Export settings (engine + params); resolution reuses outputShortEdge above.
  exportEngine: ExportEngineChoice = "";
  exportFps = 30;
  exportBitrateMode: BitrateMode = "auto";
  exportBitrateMbps = 12;
  /** keyed by candidate index (decimal string, matching on-disk str keys). */
  clipsOverrides: Record<string, ComponentDict> = {};
  rendered: ComponentDict[] = [];

  private constructor(
    private readonly fs: Fs,
    private readonly path: string,
  ) {}

  /** Load from disk. A missing/malformed file yields a fresh empty config
   *  (pre-alpha — no migration shim). */
  static async load(fs: Fs, path: string): Promise<ClipConfigOwner> {
    const self = new ClipConfigOwner(fs, path);
    const raw = await fs.readJson<Record<string, unknown>>(path);
    if (!raw || typeof raw !== "object") return self;

    const bound = raw["bound_material"];
    if (
      bound && typeof bound === "object" &&
      (bound as Record<string, unknown>)["type_name"] &&
      (bound as Record<string, unknown>)["instance_name"]
    ) {
      const b = bound as Record<string, unknown>;
      self.boundMaterial = {
        type_name: String(b["type_name"] ?? ""),
        instance_name: String(b["instance_name"] ?? ""),
        bound_at: String(b["bound_at"] ?? ""),
      };
    }

    self.sourceSubtitle = String(raw["source_subtitle"] ?? "");
    const sel = raw["selected_clip_indices"];
    self.selectedClipIndices = Array.isArray(sel) ? sel.filter((i): i is number => Number.isInteger(i)) : [];
    self.presetName = String(raw["preset_name"] ?? "");

    self.outputAspect = String(raw["output_aspect"] ?? "9:16");
    const shortEdge = Number(raw["output_short_edge"]);
    self.outputShortEdge = Number.isFinite(shortEdge) ? Math.trunc(shortEdge) : 1080;
    self.outputMode = String(raw["output_mode"] ?? "reframe");
    self.encodePreset = String(raw["encode_preset"] ?? "medium");
    self.exportEngine = normalizeEngine(raw["export_engine"]);
    self.exportFps = normalizeFps(raw["export_fps"] ?? 30);
    self.exportBitrateMode = normalizeBitrateMode(raw["export_bitrate_mode"]);
    self.exportBitrateMbps = normalizeMbps(raw["export_bitrate_mbps"]);

    const comps = raw["components"];
    self.components = Array.isArray(comps)
      ? comps.filter((c): c is ComponentDict => typeof c === "object" && c !== null)
      : [];
    ensureUniqueIds(self.components);

    const ovs = raw["clips_overrides"];
    if (ovs && typeof ovs === "object") {
      for (const [k, v] of Object.entries(ovs as Record<string, unknown>)) {
        const idx = Number(k);
        if (Number.isInteger(idx) && v && typeof v === "object") {
          self.clipsOverrides[String(idx)] = v as ComponentDict;
        }
      }
    }

    const rendered = raw["rendered"];
    self.rendered = Array.isArray(rendered)
      ? rendered.filter((r): r is ComponentDict => typeof r === "object" && r !== null)
      : [];

    return self;
  }

  /** Mutate from a wire patch (the workbench's update-config). Only known fields
   *  are honored. `clips_overrides_merge` deep-merges per-candidate overrides:
   *  a null value deletes the key, and an emptied override is dropped. */
  applyPatch(patch: Record<string, unknown>): void {
    if (!patch || typeof patch !== "object") return;
    for (const key of ["output_aspect", "output_mode", "encode_preset", "source_subtitle", "preset_name"] as const) {
      if (key in patch) {
        const v = String(patch[key]);
        if (key === "output_aspect") this.outputAspect = v;
        else if (key === "output_mode") this.outputMode = v;
        else if (key === "encode_preset") this.encodePreset = v;
        else if (key === "source_subtitle") this.sourceSubtitle = v;
        else this.presetName = v;
      }
    }
    if ("output_short_edge" in patch) {
      const n = Number(patch["output_short_edge"]);
      if (Number.isFinite(n)) this.outputShortEdge = Math.trunc(n);
    }
    if ("export_engine" in patch) this.exportEngine = normalizeEngine(patch["export_engine"]);
    if ("export_fps" in patch) this.exportFps = normalizeFps(patch["export_fps"]);
    if ("export_bitrate_mode" in patch) this.exportBitrateMode = normalizeBitrateMode(patch["export_bitrate_mode"]);
    if ("export_bitrate_mbps" in patch) this.exportBitrateMbps = normalizeMbps(patch["export_bitrate_mbps"]);
    if (Array.isArray(patch["selected_clip_indices"])) {
      this.selectedClipIndices = (patch["selected_clip_indices"] as unknown[]).filter(
        (i): i is number => Number.isInteger(i),
      );
    }
    const merge = patch["clips_overrides_merge"];
    if (merge && typeof merge === "object") {
      for (const [rawIdx, fields] of Object.entries(merge as Record<string, unknown>)) {
        const idx = Number(rawIdx);
        if (!Number.isInteger(idx) || !fields || typeof fields !== "object") continue;
        const key = String(idx);
        const ov = (this.clipsOverrides[key] ??= {});
        for (const [k, val] of Object.entries(fields as Record<string, unknown>)) {
          if (val === null) delete ov[k];
          else ov[k] = val;
        }
        if (Object.keys(ov).length === 0) delete this.clipsOverrides[key];
      }
    }
  }

  bindMaterial(materialType: string, materialInstance: string): void {
    const mt = String(materialType).trim();
    const mi = String(materialInstance).trim();
    if (!mt || !mi) throw new Error("material_type and material_instance are required");
    this.boundMaterial = { type_name: mt, instance_name: mi, bound_at: new Date().toISOString().replace(/\.\d+Z$/, "Z") };
  }

  // ── component add / remove / reorder ──────────────────────────────────────

  static addableKinds(): AddableKind[] {
    return ADDABLE.map((d) => ({ ...d }));
  }

  private uniqueId(base: string): string {
    const existing = new Set(this.components.map((c) => c["id"]));
    if (!existing.has(base)) return base;
    let n = 2;
    while (existing.has(`${base}-${n}`)) n++;
    return `${base}-${n}`;
  }

  addComponent(kind: string): ComponentDict {
    const instance = defaultInstance(kind);
    // A new subtitle inherits the active language so the first add "just works".
    if (kind === "clip_subtitle") instance["language"] = this.sourceSubtitle;
    instance["id"] = this.uniqueId(String(instance["id"] || kind));
    this.components.push(instance);
    return instance;
  }

  /** Shallow-merge a patch into one component dict (faithful to the base RPC
   *  layer's creation.update_component). Returns the updated component or null. */
  updateComponent(componentId: string, patch: Record<string, unknown>): ComponentDict | null {
    const c = this.components.find((x) => x["id"] === componentId);
    if (!c) return null;
    Object.assign(c, patch);
    return c;
  }

  removeComponent(componentId: string): void {
    this.components = this.components.filter((c) => c["id"] !== componentId);
  }

  moveComponent(componentId: string, delta: number): void {
    const idx = this.components.findIndex((c) => c["id"] === componentId);
    if (idx < 0) return;
    const target = idx + delta;
    if (target < 0 || target >= this.components.length) return;
    const c = this.components;
    const moved = c[idx]!;
    c[idx] = c[target]!;
    c[target] = moved;
  }

  // ── presets (Style-tab toolbar) ───────────────────────────────────────────

  async listPresets(): Promise<{ names: string[]; builtins: string[]; lastUsed: string }> {
    const store = await presets.loadStore(this.fs);
    return { names: presets.listPresets(store), builtins: presets.builtinNames(), lastUsed: presets.getLastUsed(store) };
  }

  async applyPreset(name: string): Promise<void> {
    const store = await presets.loadStore(this.fs);
    const preset = presets.getPreset(store, name);
    if (preset === null) throw new Error(`unknown preset: ${name}`);
    const out = preset.output ?? {};
    this.outputAspect = String(out.aspect ?? this.outputAspect);
    const se = Number(out.short_edge);
    if (Number.isFinite(se)) this.outputShortEdge = Math.trunc(se);
    this.outputMode = String(out.mode ?? this.outputMode);
    this.encodePreset = String(preset.encode_preset ?? this.encodePreset);
    this.components = JSON.parse(JSON.stringify(preset.components ?? [])) as ComponentDict[];
    ensureUniqueIds(this.components);
    this.presetName = name;
    presets.setLastUsed(store, name);
    await presets.saveStore(this.fs, store);
  }

  async savePreset(name: string): Promise<void> {
    if (presets.isBuiltin(name)) throw new Error(`cannot overwrite builtin preset: ${name}`);
    const store = await presets.loadStore(this.fs);
    presets.upsertPreset(store, name, {
      components: this.components,
      outputAspect: this.outputAspect,
      outputShortEdge: this.outputShortEdge,
      outputMode: this.outputMode,
      encodePreset: this.encodePreset,
    });
    presets.setLastUsed(store, name);
    await presets.saveStore(this.fs, store);
    this.presetName = name;
  }

  async deletePreset(name: string): Promise<void> {
    if (presets.isBuiltin(name)) throw new Error(`cannot delete builtin preset: ${name}`);
    const store = await presets.loadStore(this.fs);
    presets.deletePreset(store, name);
    await presets.saveStore(this.fs, store);
  }

  /** The on-disk dict, key order matching config.py::save for golden stability. */
  toJSON(): Record<string, unknown> {
    const out: Record<string, unknown> = {
      source_subtitle: this.sourceSubtitle,
      selected_clip_indices: [...this.selectedClipIndices],
      preset_name: this.presetName,
      components: [...this.components],
      output_aspect: this.outputAspect,
      output_short_edge: Math.trunc(this.outputShortEdge),
      output_mode: this.outputMode,
      encode_preset: this.encodePreset,
      export_engine: this.exportEngine,
      export_fps: Math.trunc(this.exportFps),
      export_bitrate_mode: this.exportBitrateMode,
      export_bitrate_mbps: Math.trunc(this.exportBitrateMbps),
      clips_overrides: { ...this.clipsOverrides },
      rendered: [...this.rendered],
    };
    if (this.boundMaterial !== null) out["bound_material"] = { ...this.boundMaterial };
    return out;
  }

  /** The single write path for config.json (atomic via the main process). */
  async save(): Promise<void> {
    await this.fs.writeJson(this.path, this.toJSON());
  }
}
