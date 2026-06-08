/**
 * News-desk instance config — single in-memory owner (ADR-0008 TS port of
 * `src/creations/news_desk/config.py`).
 *
 * Simpler than clip: news_desk renders the full source at source resolution (no
 * reframe geometry, no candidates), so the config is just bound_material +
 * preset_name + components + rendered[]. apply_patch only honors preset_name;
 * component edits go through the *_component methods. save() matches Python
 * *.save() byte format (via vc.fs.writeJson) for golden stability; mutators don't
 * auto-save (the workbench calls save()).
 */

import type { Fs } from "../../renderer/ipc/fs";
import type { CropRect } from "../../composition/ir.js";
import { parseCropRect } from "../../composition/crop.js";
import { ADDABLE, type AddableKind, type ComponentDict, defaultInstance } from "./componentDefs";
import * as presets from "./presets";
import {
  normalizeBitrateMode,
  normalizeEngine,
  normalizeFps,
  normalizeMbps,
  normalizeResolution,
  type BitrateMode,
  type ExportEngineChoice,
} from "../exportSettings";

export interface BoundMaterial {
  type_name: string;
  instance_name: string;
  bound_at: string;
}

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

export class NewsDeskConfigOwner {
  boundMaterial: BoundMaterial | null = null;
  presetName = "";
  components: ComponentDict[] = [];
  rendered: ComponentDict[] = [];
  // Output framing (spatial reframe). Defaults are a no-op = today's behavior:
  // passthrough renders the full source verbatim and ignores aspect/short-edge;
  // cropRect=null means whole source. aspect/short-edge/cropRect only bite in
  // reframe/letterbox. (In passthrough, export_resolution below still drives the
  // source downscale; in reframe/letterbox the target short-edge is outputShortEdge.)
  outputMode = "passthrough";
  outputAspect = "16:9";
  outputShortEdge = 1080;
  cropRect: CropRect | null = null;
  // Export settings (engine + params). News_desk is full-source, so resolution
  // is a downscale-from-source preset ("source" | short-edge px).
  exportEngine: ExportEngineChoice = "";
  exportResolution = "source";
  exportFps = 30;
  exportBitrateMode: BitrateMode = "auto";
  exportBitrateMbps = 12;

  private constructor(
    private readonly fs: Fs,
    private readonly path: string,
  ) {}

  static async load(fs: Fs, path: string): Promise<NewsDeskConfigOwner> {
    const self = new NewsDeskConfigOwner(fs, path);
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
    self.presetName = String(raw["preset_name"] ?? "");
    self.outputMode = String(raw["output_mode"] ?? "passthrough");
    self.outputAspect = String(raw["output_aspect"] ?? "16:9");
    const shortEdge = Number(raw["output_short_edge"]);
    self.outputShortEdge = Number.isFinite(shortEdge) ? Math.trunc(shortEdge) : 1080;
    self.cropRect = parseCropRect(raw["crop_rect"]);
    self.exportEngine = normalizeEngine(raw["export_engine"]);
    self.exportResolution = normalizeResolution(raw["export_resolution"]);
    self.exportFps = normalizeFps(raw["export_fps"] ?? 30);
    self.exportBitrateMode = normalizeBitrateMode(raw["export_bitrate_mode"]);
    self.exportBitrateMbps = normalizeMbps(raw["export_bitrate_mbps"]);
    const comps = raw["components"];
    self.components = Array.isArray(comps)
      ? comps.filter((c): c is ComponentDict => typeof c === "object" && c !== null)
      : [];
    ensureUniqueIds(self.components);
    const rendered = raw["rendered"];
    self.rendered = Array.isArray(rendered)
      ? rendered.filter((r): r is ComponentDict => typeof r === "object" && r !== null)
      : [];
    return self;
  }

  /** preset_name + export settings are patchable (full-source, no reframe geometry). */
  applyPatch(patch: Record<string, unknown>): void {
    if (!patch || typeof patch !== "object") return;
    if ("preset_name" in patch) this.presetName = String(patch["preset_name"]);
    if ("output_mode" in patch) this.outputMode = String(patch["output_mode"]);
    if ("output_aspect" in patch) this.outputAspect = String(patch["output_aspect"]);
    if ("output_short_edge" in patch) {
      const n = Number(patch["output_short_edge"]);
      if (Number.isFinite(n)) this.outputShortEdge = Math.trunc(n);
    }
    // crop_rect is a single instance-level rect (no per-candidate merge); null clears it.
    if ("crop_rect" in patch) this.cropRect = parseCropRect(patch["crop_rect"]);
    if ("export_engine" in patch) this.exportEngine = normalizeEngine(patch["export_engine"]);
    if ("export_resolution" in patch) this.exportResolution = normalizeResolution(patch["export_resolution"]);
    if ("export_fps" in patch) this.exportFps = normalizeFps(patch["export_fps"]);
    if ("export_bitrate_mode" in patch) this.exportBitrateMode = normalizeBitrateMode(patch["export_bitrate_mode"]);
    if ("export_bitrate_mbps" in patch) this.exportBitrateMbps = normalizeMbps(patch["export_bitrate_mbps"]);
  }

  bindMaterial(materialType: string, materialInstance: string): void {
    const mt = String(materialType).trim();
    const mi = String(materialInstance).trim();
    if (!mt || !mi) throw new Error("material_type and material_instance are required");
    this.boundMaterial = { type_name: mt, instance_name: mi, bound_at: new Date().toISOString().replace(/\.\d+Z$/, "Z") };
  }

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
    instance["id"] = this.uniqueId(String(instance["id"] || kind));
    this.components.push(instance);
    return instance;
  }

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

  // ── presets (news_desk: an ordered component list; apply replaces wholesale) ─

  async listPresets(): Promise<{ names: string[]; builtins: string[]; lastUsed: string }> {
    return {
      names: await presets.listPresetNames(this.fs),
      builtins: presets.builtinNames(),
      lastUsed: this.presetName || presets.DEFAULT_PRESET_NAME,
    };
  }

  async applyPreset(name: string): Promise<void> {
    const preset = await presets.getPreset(this.fs, name);
    if (preset === null) throw new Error(`unknown preset: ${name}`);
    this.components = JSON.parse(JSON.stringify(preset.components)) as ComponentDict[];
    ensureUniqueIds(this.components);
    this.presetName = name;
  }

  async savePreset(name: string): Promise<void> {
    if (presets.isBuiltin(name)) throw new Error(`cannot overwrite builtin preset: ${name}`);
    await presets.saveUserPreset(this.fs, { name, description: "", components: this.components });
    this.presetName = name;
  }

  async deletePreset(name: string): Promise<void> {
    if (presets.isBuiltin(name)) throw new Error(`cannot delete builtin preset: ${name}`);
    await presets.deleteUserPreset(this.fs, name);
  }

  toJSON(): Record<string, unknown> {
    const out: Record<string, unknown> = {
      preset_name: this.presetName,
      output_mode: this.outputMode,
      output_aspect: this.outputAspect,
      output_short_edge: Math.trunc(this.outputShortEdge),
      crop_rect: this.cropRect ? { ...this.cropRect } : null,
      export_engine: this.exportEngine,
      export_resolution: this.exportResolution,
      export_fps: Math.trunc(this.exportFps),
      export_bitrate_mode: this.exportBitrateMode,
      export_bitrate_mbps: Math.trunc(this.exportBitrateMbps),
      components: [...this.components],
      rendered: [...this.rendered],
    };
    if (this.boundMaterial !== null) out["bound_material"] = { ...this.boundMaterial };
    return out;
  }

  async save(): Promise<void> {
    await this.fs.writeJson(this.path, this.toJSON());
  }
}
