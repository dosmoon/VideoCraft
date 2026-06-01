import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { ClipConfigOwner } from "./configOwner";

const PRESETS_DIR = "/userData/presets";

/** In-memory Fs fake — the injection seam (renderer/ipc/fs.ts Fs) lets these
 *  tests run without Electron / disk. */
function makeFs(): Fs & { files: Map<string, string> } {
  const files = new Map<string, string>();
  return {
    files,
    async readJson<T>(p: string): Promise<T | null> {
      const t = files.get(p);
      return t === undefined ? null : (JSON.parse(t) as T);
    },
    async writeJson(p: string, v: unknown): Promise<string> {
      files.set(p, JSON.stringify(v, null, 2));
      return p;
    },
    async readText(p: string): Promise<string | null> {
      return files.get(p) ?? null;
    },
    async writeText(p: string, t: string): Promise<string> {
      files.set(p, t);
      return p;
    },
    async list(): Promise<{ name: string; isDir: boolean }[]> {
      return [];
    },
    async copy(s: string, dest: string): Promise<string> {
      files.set(dest, files.get(s) ?? "");
      return dest;
    },
    async remove(p: string): Promise<void> {
      files.delete(p);
    },
    async stat(p: string) {
      return files.has(p) ? { exists: true, isDir: false, size: 0, mtimeMs: 0 } : { exists: false };
    },
    async presetsDir(): Promise<string> {
      return PRESETS_DIR;
    },
  };
}

const CONFIG = "/project/.creations/clip/inst/config.json";

describe("ClipConfigOwner — load / save", () => {
  it("missing file yields defaults; save + reload round-trips", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    expect(o.outputAspect).toBe("9:16");
    expect(o.components).toEqual([]);

    o.sourceSubtitle = "en";
    o.addComponent("clip_subtitle");
    await o.save();

    const o2 = await ClipConfigOwner.load(fs, CONFIG);
    expect(o2.sourceSubtitle).toBe("en");
    expect(o2.components).toHaveLength(1);
    expect(o2.components[0]!["kind"]).toBe("clip_subtitle");
  });

  it("repairs duplicate/missing component ids on load (Tk-era)", async () => {
    const fs = makeFs();
    fs.files.set(
      CONFIG,
      JSON.stringify({
        components: [
          { kind: "clip_subtitle", id: "sub" },
          { kind: "clip_subtitle", id: "sub" }, // collision
          { kind: "clip_hook_card" }, // missing id → falls back to kind
        ],
      }),
    );
    const o = await ClipConfigOwner.load(fs, CONFIG);
    const ids = o.components.map((c) => c["id"]);
    expect(ids).toEqual(["sub", "sub-2", "clip_hook_card"]);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("ClipConfigOwner — applyPatch", () => {
  it("honors only known fields + int short_edge", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    o.applyPatch({ output_aspect: "1:1", output_short_edge: 720.7, source_subtitle: "zh", unknown_x: 1 });
    expect(o.outputAspect).toBe("1:1");
    expect(o.outputShortEdge).toBe(720);
    expect(o.sourceSubtitle).toBe("zh");
    expect((o as unknown as Record<string, unknown>)["unknown_x"]).toBeUndefined();
  });

  it("clips_overrides_merge: set, null-deletes a key, drops emptied override", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    o.applyPatch({ clips_overrides_merge: { 2: { hook_text: "hi", title: "T" } } });
    expect(o.clipsOverrides["2"]).toEqual({ hook_text: "hi", title: "T" });
    o.applyPatch({ clips_overrides_merge: { 2: { title: null } } });
    expect(o.clipsOverrides["2"]).toEqual({ hook_text: "hi" });
    o.applyPatch({ clips_overrides_merge: { 2: { hook_text: null } } });
    expect(o.clipsOverrides["2"]).toBeUndefined(); // emptied → dropped
  });
});

describe("ClipConfigOwner — components", () => {
  it("addComponent assigns unique ids; subtitle inherits active language", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    o.sourceSubtitle = "en";
    o.addComponent("clip_subtitle");
    o.addComponent("clip_subtitle");
    const subs = o.components.filter((c) => c["kind"] === "clip_subtitle");
    expect(subs.map((c) => c["id"])).toEqual(["sub1", "sub1-2"]);
    expect(subs[0]!["language"]).toBe("en");
  });

  it("remove + move reorder", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    o.addComponent("clip_subtitle"); // sub1
    o.addComponent("clip_hook_card"); // hook
    o.moveComponent("hook", -1);
    expect(o.components.map((c) => c["kind"])).toEqual(["clip_hook_card", "clip_subtitle"]);
    o.removeComponent("sub1");
    expect(o.components.map((c) => c["id"])).toEqual(["hook"]);
  });

  it("addableKinds: registration order + multi_instance flags", () => {
    const a = ClipConfigOwner.addableKinds();
    expect(a[0]).toEqual({ kind: "clip_subtitle", multi_instance: true });
    expect(a.find((k) => k.kind === "clip_hook_card")?.multi_instance).toBe(false);
  });
});

describe("ClipConfigOwner — bind + presets", () => {
  it("bindMaterial sets and persists bound_material", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    o.bindMaterial("news_video", "news-1");
    expect(o.boundMaterial?.instance_name).toBe("news-1");
    await o.save();
    const reloaded = JSON.parse(fs.files.get(CONFIG)!);
    expect(reloaded.bound_material.type_name).toBe("news_video");
  });

  it("listPresets returns builtins first; apply replaces components + re-uniques", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    const list = await o.listPresets();
    expect(list.builtins).toContain("Default 9:16");
    expect(list.names[0]).toBe("Default 9:16"); // builtins first

    await o.applyPreset("Default 9:16");
    expect(o.presetName).toBe("Default 9:16");
    expect(o.components.map((c) => c["kind"])).toEqual(["clip_subtitle", "clip_hook_card"]);
    const ids = o.components.map((c) => c["id"]);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("save/delete user preset; builtins protected", async () => {
    const fs = makeFs();
    const o = await ClipConfigOwner.load(fs, CONFIG);
    o.addComponent("clip_subtitle");
    await o.savePreset("My Preset");
    expect((await o.listPresets()).names).toContain("My Preset");

    await expect(o.savePreset("Default 9:16")).rejects.toThrow(/builtin/);
    await expect(o.deletePreset("Default 9:16")).rejects.toThrow(/builtin/);

    await o.deletePreset("My Preset");
    expect((await o.listPresets()).names).not.toContain("My Preset");
  });
});
