import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { NewsDeskConfigOwner } from "./configOwner";
import { commitRender, deleteRender, type NewsDeskRenderCtx } from "./render";

const PRESETS_DIR = "/userData/presets";
const INST = "/proj/news_desk/inst";
const CONFIG = `${INST}/config.json`;

function makeFs(): Fs & { files: Map<string, string> } {
  const files = new Map<string, string>();
  return {
    files,
    async stat(p: string) {
      return files.has(p) ? { exists: true, isDir: false, size: 0, mtimeMs: 0 } : { exists: false };
    },
    async copy(s: string, d: string): Promise<string> {
      files.set(d, files.get(s) ?? "");
      return d;
    },
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
    async list() {
      return [];
    },
    async remove(p: string): Promise<void> {
      files.delete(p);
    },
    async presetsDir(): Promise<string> {
      return PRESETS_DIR;
    },
  };
}

describe("NewsDeskConfigOwner", () => {
  it("load/save round-trip + id repair", async () => {
    const fs = makeFs();
    fs.files.set(
      CONFIG,
      JSON.stringify({
        preset_name: "演讲",
        components: [
          { kind: "subtitle", id: "s" },
          { kind: "subtitle", id: "s" }, // collision
          { kind: "chapter" }, // missing id → kind
        ],
      }),
    );
    const o = await NewsDeskConfigOwner.load(fs, CONFIG);
    expect(o.presetName).toBe("演讲");
    expect(o.components.map((c) => c["id"])).toEqual(["s", "s-2", "chapter"]);

    o.addComponent("text_watermark");
    await o.save();
    const reloaded = JSON.parse(fs.files.get(CONFIG)!);
    expect(reloaded.components.map((c: Record<string, unknown>) => c["kind"])).toContain("text_watermark");
  });

  it("applyPatch only honors preset_name; CRUD + bind", async () => {
    const fs = makeFs();
    const o = await NewsDeskConfigOwner.load(fs, CONFIG);
    o.applyPatch({ preset_name: "极简", output_aspect: "9:16" });
    expect(o.presetName).toBe("极简");
    expect((o as unknown as Record<string, unknown>)["outputAspect"]).toBeUndefined();

    o.addComponent("subtitle");
    o.addComponent("subtitle");
    expect(o.components.map((c) => c["id"])).toEqual(["subtitle", "subtitle-2"]);
    o.moveComponent("subtitle-2", -1);
    expect(o.components.map((c) => c["id"])).toEqual(["subtitle-2", "subtitle"]);
    o.removeComponent("subtitle");
    expect(o.components.map((c) => c["id"])).toEqual(["subtitle-2"]);

    o.bindMaterial("news_video", "n1");
    expect(o.boundMaterial?.instance_name).toBe("n1");
  });

  it("applyPatch honors export settings (engine/resolution/fps/bitrate); round-trips", async () => {
    const fs = makeFs();
    const o = await NewsDeskConfigOwner.load(fs, CONFIG);
    expect(o.exportEngine).toBe("");
    expect(o.exportResolution).toBe("source");
    o.applyPatch({
      export_engine: "chromium",
      export_resolution: "720",
      export_fps: 24,
      export_bitrate_mode: "mbps",
      export_bitrate_mbps: 9,
    });
    expect(o.exportEngine).toBe("chromium");
    expect(o.exportResolution).toBe("720");
    expect(o.exportFps).toBe(24);
    expect(o.exportBitrateMode).toBe("mbps");
    expect(o.exportBitrateMbps).toBe(9);
    await o.save();
    const o2 = await NewsDeskConfigOwner.load(fs, CONFIG);
    expect(o2.exportResolution).toBe("720");
    expect(o2.exportFps).toBe(24);
  });
});

describe("NewsDeskConfigOwner — presets", () => {
  it("builtins present; apply replaces components; save drops project content", async () => {
    const fs = makeFs();
    const o = await NewsDeskConfigOwner.load(fs, CONFIG);
    const list = await o.listPresets();
    expect(list.builtins).toEqual(["新闻发布会", "演讲", "极简"]);
    expect(list.names[0]).toBe("新闻发布会");

    await o.applyPreset("极简");
    expect(o.presetName).toBe("极简");
    expect(o.components.map((c) => c["kind"])).toEqual(["subtitle"]);

    // Give the subtitle a project-content srt_path, save as a user preset, and
    // confirm it's stripped on disk.
    o.components[0]!["srt_path"] = "subtitles/x.srt";
    await o.savePreset("我的预设");
    const store = JSON.parse(fs.files.get(`${PRESETS_DIR}/news_desk.json`)!);
    expect(store.user_presets["我的预设"].components[0].srt_path).toBeUndefined();
    expect((await o.listPresets()).names).toContain("我的预设");

    await expect(o.savePreset("演讲")).rejects.toThrow(/builtin/);
    await o.deletePreset("我的预设");
    expect((await o.listPresets()).names).not.toContain("我的预设");
  });
});

describe("news_desk render", () => {
  const ctx = (fs: Fs, o: NewsDeskConfigOwner): NewsDeskRenderCtx => ({
    owner: o,
    fs,
    instanceDir: INST,
    context: { episode_topic: "预算听证会", host: "张三" },
    projectTitle: "Src",
    sourceUrl: null,
    langIso: "zh",
  });

  it("commitRender writes output.json + rendered[] + publish.md", async () => {
    const fs = makeFs();
    const o = await NewsDeskConfigOwner.load(fs, CONFIG);
    o.addComponent("chapter");
    o.components[0]!["schedule"] = [
      { start_sec: 0, end_sec: 30, title: "开场" },
      { start_sec: 30, end_sec: 90, title: "正文" },
    ];

    const rendered = await commitRender(ctx(fs, o), 42);
    expect(rendered[0]!["file"]).toBe("output.mp4");
    const sidecar = JSON.parse(fs.files.get(`${INST}/output.json`)!);
    expect(sidecar.duration_sec).toBe(42);
    const md = fs.files.get(`${INST}/publish.md`)!;
    expect(md).toContain("# 预算听证会"); // episode_topic wins the title
    expect(md).toContain("张三"); // host from context
    expect(md).toContain("正文"); // snapshotted chapter title
    // persisted rendered[]
    expect(JSON.parse(fs.files.get(CONFIG)!).rendered[0].output_index).toBe(1);
  });

  it("deleteRender clears output + publish.md + rendered[]", async () => {
    const fs = makeFs();
    const o = await NewsDeskConfigOwner.load(fs, CONFIG);
    await commitRender(ctx(fs, o), 10);
    fs.files.set(`${INST}/output.mp4`, "bytes");
    const rendered = await deleteRender({ owner: o, fs, instanceDir: INST });
    expect(rendered).toEqual([]);
    expect(fs.files.has(`${INST}/output.mp4`)).toBe(false);
    expect(fs.files.has(`${INST}/output.json`)).toBe(false);
    expect(fs.files.has(`${INST}/publish.md`)).toBe(false);
  });
});
