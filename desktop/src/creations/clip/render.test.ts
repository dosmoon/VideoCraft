import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { ClipConfigOwner } from "./configOwner";
import { commitRender, deleteRender, planRender, type RenderCtx } from "./render";

const INST = "/proj/clip/inst";
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
    async list(dir: string) {
      const out: { name: string; isDir: boolean }[] = [];
      const seen = new Set<string>();
      for (const k of files.keys()) {
        if (k.startsWith(dir + "/")) {
          const name = k.slice(dir.length + 1).split("/")[0]!;
          if (!seen.has(name)) {
            seen.add(name);
            out.push({ name, isDir: false });
          }
        }
      }
      return out;
    },
    async remove(p: string): Promise<void> {
      files.delete(p);
    },
    async presetsDir(): Promise<string> {
      return "/presets";
    },
  };
}

const CANDIDATES = [
  { start: "00:00:05.000", end: "00:00:35.000", hook: "H0" },
  { start: "00:01:00.000", end: "00:01:20.000", hook: "H1", suggested_title: "T1", score: 9, transcript: "words" },
];

async function ownerWith(fs: Fs, sel: number[], overrides: Record<string, unknown> = {}): Promise<ClipConfigOwner> {
  const o = await ClipConfigOwner.load(fs, CONFIG);
  o.sourceSubtitle = "en";
  o.selectedClipIndices = sel;
  for (const [k, v] of Object.entries(overrides)) o.clipsOverrides[k] = v as Record<string, unknown>;
  return o;
}
const ctx = (fs: Fs, owner: ClipConfigOwner): RenderCtx => ({
  owner,
  fs,
  instanceDir: INST,
  candidates: CANDIDATES,
  projectTitle: "Src",
  langIso: "en",
});

describe("planRender", () => {
  it("selected → ascending out_idx, hook in basename, parsed times", async () => {
    const fs = makeFs();
    const o = await ownerWith(fs, [1]);
    const plan = planRender(o, INST, CANDIDATES);
    expect(plan.clips).toHaveLength(1);
    expect(plan.clips[0]!.srcIdx).toBe(1);
    expect(plan.clips[0]!.outIdx).toBe(1);
    expect(plan.clips[0]!.outputPath).toBe(`${INST}/clip_001_H1.mp4`);
    expect(plan.clips[0]!.startSec).toBe(60);
    expect(plan.clips[0]!.endSec).toBe(80);
  });

  it("override wins for hook (basename) and start/end", async () => {
    const fs = makeFs();
    const o = await ownerWith(fs, [1], { 1: { hook_text: "OVR", start_sec: 10 } });
    const plan = planRender(o, INST, CANDIDATES);
    expect(plan.clips[0]!.outputPath).toBe(`${INST}/clip_001_OVR.mp4`);
    expect(plan.clips[0]!.startSec).toBe(10);
  });
});

describe("commitRender", () => {
  it("writes sidecar + rendered[] + publish.md + index.md, persists owner", async () => {
    const fs = makeFs();
    const o = await ownerWith(fs, [1]);
    const rendered = await commitRender(ctx(fs, o), 1, 1, 20);

    expect(rendered[0]!["file"]).toBe("clip_001_H1.mp4");
    const sidecar = JSON.parse(fs.files.get(`${INST}/clip_001_H1.json`)!);
    expect(sidecar.title).toBe("T1");
    expect(sidecar.hook).toBe("H1");
    expect(sidecar.score).toBe(9);
    expect(sidecar.start_sec).toBe(60);
    // publish docs
    expect(fs.files.get(`${INST}/clip_001_H1.md`)).toContain("# T1");
    expect(fs.files.get(`${INST}/index.md`)).toContain("clip_001_H1.mp4");
    // owner persisted with rendered[]
    const config = JSON.parse(fs.files.get(CONFIG)!);
    expect(config.rendered.map((r: Record<string, unknown>) => r["output_index"])).toEqual([1]);
  });

  it("stale cleanup removes prior files for the same out_idx under a different basename", async () => {
    const fs = makeFs();
    const o = await ownerWith(fs, [1]);
    fs.files.set(`${INST}/clip_001_OLD.mp4`, "old");
    fs.files.set(`${INST}/clip_001_OLD.json`, "{}");
    await commitRender(ctx(fs, o), 1, 1, 20);
    expect(fs.files.has(`${INST}/clip_001_OLD.mp4`)).toBe(false);
    expect(fs.files.has(`${INST}/clip_001_OLD.json`)).toBe(false);
    expect(fs.files.has(`${INST}/clip_001_H1.json`)).toBe(true);
  });
});

describe("deleteRender", () => {
  it("unlinks the out_idx files, rebuilds index, drops from rendered[]", async () => {
    const fs = makeFs();
    const o = await ownerWith(fs, [1]);
    await commitRender(ctx(fs, o), 1, 1, 20);
    fs.files.set(`${INST}/clip_001_H1.mp4`, "bytes"); // renderer wrote the mp4

    const rendered = await deleteRender(
      { owner: o, fs, instanceDir: INST, projectTitle: "Src", langIso: "en" },
      1,
    );
    expect(rendered).toEqual([]);
    expect(fs.files.has(`${INST}/clip_001_H1.mp4`)).toBe(false);
    expect(fs.files.has(`${INST}/clip_001_H1.json`)).toBe(false);
    expect(fs.files.has(`${INST}/clip_001_H1.md`)).toBe(false);
    expect(fs.files.get(`${INST}/index.md`)).toContain("(no clips yet)");
  });
});
