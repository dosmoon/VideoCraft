import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { NewsDeskConfigOwner } from "./configOwner";
import { type ImportMaterial, importNewsDeskResource, listNewsDeskImports } from "./imports";

const DIR = "/proj/news_desk/inst";
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
    async list() {
      return [];
    },
    async remove(p: string): Promise<void> {
      files.delete(p);
    },
    async presetsDir(): Promise<string> {
      return "/presets";
    },
  };
}

const model: ImportMaterial = {
  async listSubtitleLanguages() {
    return ["en", "zh"];
  },
  async listAnalyses() {
    return ["en.analysis.json"];
  },
  subtitlePath(lang: string) {
    return `${SUBS}/${lang}.srt`;
  },
  async dubVersions(lang: string) {
    return lang === "en" ? [{ id: 1, name: "Yunxi", audioPath: `${SUBS}/en.dub.1.mp3` }] : [];
  },
  async readAnalysis() {
    return {
      titles: ["Title A", "  Title B  ", ""], // trimmed + blank entries dropped
      chapters: [
        { start_sec: 1, end_sec: 2, title: "T", refined: "R", key_points: ["k"] },
        "junk", // non-dict rows are dropped
      ],
    };
  },
};

async function loadOwner(fs: Fs): Promise<NewsDeskConfigOwner> {
  await fs.writeJson(`${DIR}/config.json`, {
    bound_material: { type_name: "news_video", instance_name: "default" },
    components: [
      { kind: "subtitle", id: "s1" },
      { kind: "chapter", id: "c1" },
      { kind: "dubbing", id: "d1", enabled: true, audio_path: "", mode: "replace" },
    ],
  });
  return NewsDeskConfigOwner.load(fs, `${DIR}/config.json`);
}

describe("listNewsDeskImports", () => {
  it("returns the material's subtitle languages + analysis filenames + dub versions", async () => {
    expect(await listNewsDeskImports(model)).toEqual({
      subtitleLangs: ["en", "zh"],
      analyses: ["en.analysis.json"],
      dubVersions: [{ lang: "en", id: 1, name: "Yunxi" }], // only "en" has a dub version
    });
  });
});

describe("importNewsDeskResource", () => {
  it("snapshots a subtitle SRT into the instance dir and persists srt_path", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.srt`, "SRT");
    const owner = await loadOwner(fs);

    const updated = await importNewsDeskResource(owner, fs, DIR, model, "s1", { kind: "subtitle", lang: "en" });
    expect(updated["srt_path"]).toBe("subtitles/s1.srt");
    expect(fs.files.get(`${DIR}/subtitles/s1.srt`)).toBe("SRT");

    // Persisted by owner.save() — a fresh load sees the new srt_path.
    const reloaded = await NewsDeskConfigOwner.load(fs, `${DIR}/config.json`);
    expect(reloaded.components.find((c) => c["id"] === "s1")?.["srt_path"]).toBe("subtitles/s1.srt");
  });

  it("fills a chapter schedule + candidate titles from analysis.json, dropping non-dict rows", async () => {
    const fs = makeFs();
    const owner = await loadOwner(fs);
    const updated = await importNewsDeskResource(owner, fs, DIR, model, "c1", {
      kind: "chapters",
      filename: "en.analysis.json",
    });
    expect(updated["schedule"]).toEqual([
      { start_sec: 1, end_sec: 2, title: "T", refined: "R", key_points: ["k"] },
    ]);
    // Candidate titles must be snapshotted too (trimmed, blanks dropped) — they
    // feed publish.md's "Candidate Titles" section via render.ts.
    expect(updated["titles"]).toEqual(["Title A", "Title B"]);

    // Persisted: a fresh load sees both schedule and titles.
    const reloaded = await NewsDeskConfigOwner.load(fs, `${DIR}/config.json`);
    const c1 = reloaded.components.find((c) => c["id"] === "c1");
    expect(c1?.["titles"]).toEqual(["Title A", "Title B"]);
  });

  it("snapshots the chosen dubbing version (<lang>.dub.<id>.mp3) and persists audio_path", async () => {
    const fs = makeFs();
    fs.files.set(`${SUBS}/en.dub.1.mp3`, "MP3");
    const owner = await loadOwner(fs);

    const updated = await importNewsDeskResource(owner, fs, DIR, model, "d1", {
      kind: "dubbing",
      lang: "en",
      version_id: 1,
    });
    expect(updated["audio_path"]).toBe("audio/d1.mp3");
    expect(fs.files.get(`${DIR}/audio/d1.mp3`)).toBe("MP3");

    const reloaded = await NewsDeskConfigOwner.load(fs, `${DIR}/config.json`);
    expect(reloaded.components.find((c) => c["id"] === "d1")?.["audio_path"]).toBe("audio/d1.mp3");
  });

  it("rejects a dubbing import for an unknown version", async () => {
    const fs = makeFs();
    const owner = await loadOwner(fs);
    await expect(
      importNewsDeskResource(owner, fs, DIR, model, "d1", { kind: "dubbing", lang: "en", version_id: 9 }),
    ).rejects.toThrow(/dubbing version not found/);
  });

  it("rejects unknown component, wrong kind, missing SRT, and unknown import kind", async () => {
    const fs = makeFs();
    const owner = await loadOwner(fs);
    await expect(importNewsDeskResource(owner, fs, DIR, model, "nope", { kind: "subtitle", lang: "en" })).rejects.toThrow(
      /no component with id/,
    );
    await expect(importNewsDeskResource(owner, fs, DIR, model, "c1", { kind: "subtitle", lang: "en" })).rejects.toThrow(
      /not a subtitle/,
    );
    await expect(importNewsDeskResource(owner, fs, DIR, model, "s1", { kind: "subtitle", lang: "fr" })).rejects.toThrow(
      /subtitle not found/,
    );
    await expect(importNewsDeskResource(owner, fs, DIR, model, "s1", { kind: "bogus" })).rejects.toThrow(
      /unknown import kind/,
    );
  });
});
