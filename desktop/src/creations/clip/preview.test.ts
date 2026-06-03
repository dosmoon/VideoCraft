import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { HotclipsRepo, type MaterialBridge } from "./hotclipsRepo";
import { ClipConfigOwner } from "./configOwner";
import { buildClipPreview, emptyClipPreview } from "./preview";

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

async function loadOwner(fs: Fs, cfg: Record<string, unknown>): Promise<ClipConfigOwner> {
  await fs.writeJson(`${INSTANCE}/config.json`, cfg);
  return ClipConfigOwner.load(fs, `${INSTANCE}/config.json`);
}

describe("buildClipPreview", () => {
  it("parses candidates, selected index, override, and snapshot SRTs", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.hotclips.json`, JSON.stringify({ clips: [{ hook: "a" }, { hook: "b" }] }));
    fs.files.set(`${SUBS}/en.srt`, "1\n00:00:01,000 --> 00:00:02,000\nhi\n");
    const owner = await loadOwner(fs, {
      source_subtitle: "en",
      selected_clip_indices: [1],
      clips_overrides: { "1": { start: 5 } },
      bound_material: { type_name: "news_video", instance_name: "default" },
    });
    const repo = new HotclipsRepo(fs, INSTANCE, bridge);

    const pd = await buildClipPreview(owner, repo);
    expect(pd.lang).toBe("en");
    expect(pd.candidates).toEqual([{ hook: "a" }, { hook: "b" }]);
    expect(pd.selectedIndex).toBe(1);
    expect(pd.override).toEqual({ start: 5 });
    expect(pd.availableLangs).toEqual(["en"]);
    expect(pd.subtitleLangs).toEqual(["en"]);
    // SRT snapshotted into the instance dir on load → resolves to the snapshot.
    expect(pd.subtitlePaths).toEqual({ en: `${INSTANCE}/source-subtitles.en.srt` });
    expect(pd.subtitlePath).toBe(`${INSTANCE}/source-subtitles.en.srt`);
  });

  it("clamps an out-of-range selected index to 0", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.hotclips.json`, JSON.stringify({ clips: [{ hook: "a" }, { hook: "b" }] }));
    const owner = await loadOwner(fs, {
      source_subtitle: "en",
      selected_clip_indices: [5],
      bound_material: { type_name: "news_video", instance_name: "default" },
    });
    const pd = await buildClipPreview(owner, new HotclipsRepo(fs, INSTANCE, bridge));
    expect(pd.selectedIndex).toBe(0);
    expect(pd.override).toBeNull();
  });

  it("falls back to the first available language when source_subtitle is unset", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/zh.hotclips.json`, JSON.stringify({ clips: [] }));
    const owner = await loadOwner(fs, {
      bound_material: { type_name: "news_video", instance_name: "default" },
    });
    const pd = await buildClipPreview(owner, new HotclipsRepo(fs, INSTANCE, bridge));
    expect(pd.lang).toBe("zh");
    expect(pd.candidates).toEqual([]);
  });

  it("emptyClipPreview carries the language and is otherwise empty", () => {
    expect(emptyClipPreview("en")).toEqual({
      lang: "en",
      candidates: [],
      selectedIndex: 0,
      subtitlePath: null,
      subtitlePaths: {},
      override: null,
      availableLangs: [],
      subtitleLangs: [],
    });
  });
});
