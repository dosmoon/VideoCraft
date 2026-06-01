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
import { ADDABLE, type AddableKind, type ComponentDict, defaultInstance } from "./componentDefs";
import * as presets from "./presets";

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

  /** Only preset_name is patchable at top level (full-source, no geometry). */
  applyPatch(patch: Record<string, unknown>): void {
    if (!patch || typeof patch !== "object") return;
    if ("preset_name" in patch) this.presetName = String(patch["preset_name"]);
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
