import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { HotclipsRepo, type MaterialBridge } from "./hotclipsRepo";

const INSTANCE = "/proj/clip/inst";
const SUBS = "/proj/material/subs";

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
          const rest = k.slice(dir.length + 1);
          const name = rest.split("/")[0]!;
          if (!seen.has(name)) {
            seen.add(name);
            out.push({ name, isDir: rest.includes("/") });
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

const bridge: MaterialBridge = { async subtitlesDir() { return SUBS; } };

describe("HotclipsRepo", () => {
  it("ensureSnapshot copies upstream hotclips + SRT into the instance dir", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.hotclips.json`, JSON.stringify({ clips: [{ hook: "H" }] }));
    fs.files.set(`${SUBS}/en.srt`, "1\n00:00:01,000 --> 00:00:02,000\nhi\n");

    const repo = new HotclipsRepo(fs, INSTANCE, bridge);
    const snap = await repo.ensureSnapshot("en");
    expect(snap).toBe(`${INSTANCE}/source-hotclips.en.json`);
    expect(fs.files.has(`${INSTANCE}/source-hotclips.en.json`)).toBe(true);
    expect(fs.files.has(`${INSTANCE}/source-subtitles.en.srt`)).toBe(true);
  });

  it("snapshot is copy-once — upstream regeneration doesn't change the instance (ADR-0003)", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.hotclips.json`, JSON.stringify({ clips: ["original"] }));
    const repo = new HotclipsRepo(fs, INSTANCE, bridge);

    const first = await repo.loadHotclips("en");
    expect(first).toEqual({ clips: ["original"] });

    // Upstream regenerates with different content.
    fs.files.set(`${SUBS}/en.hotclips.json`, JSON.stringify({ clips: ["CHANGED"] }));
    const second = await repo.loadHotclips("en");
    expect(second).toEqual({ clips: ["original"] }); // still the snapshot
  });

  it("ensureSnapshot returns null when upstream hotclips is absent", async () => {
    const fs = makeFs();
    const repo = new HotclipsRepo(fs, INSTANCE, bridge);
    expect(await repo.ensureSnapshot("en")).toBeNull();
    expect(await repo.loadHotclips("en")).toBeNull();
  });

  it("listAvailableLangs unions instance snapshots + upstream hotclips", async () => {
    const fs = makeFs();
    fs.files.set(`${INSTANCE}/source-hotclips.zh.json`, "{}"); // already snapshotted
    fs.files.set(`${SUBS}/en.hotclips.json`, "{}"); // upstream only
    fs.files.set(`${SUBS}/en.srt`, "x");
    const repo = new HotclipsRepo(fs, INSTANCE, bridge);
    expect(await repo.listAvailableLangs()).toEqual(["en", "zh"]);
  });

  it("resolveSourceSrt prefers the snapshot, falls back to upstream", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.srt`, "upstream");
    const repo = new HotclipsRepo(fs, INSTANCE, bridge);
    // No snapshot yet → upstream.
    expect(await repo.resolveSourceSrt("en")).toBe(`${SUBS}/en.srt`);
    // After snapshotting → the instance copy.
    fs.files.set(`${INSTANCE}/source-subtitles.en.srt`, "snap");
    expect(await repo.resolveSourceSrt("en")).toBe(`${INSTANCE}/source-subtitles.en.srt`);
  });
});
