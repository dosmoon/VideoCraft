import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { buildNewsDeskPreview, emptyNewsDeskPreview, isAbsPath } from "./preview";

const DIR = "/proj/news_desk/inst";

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

describe("isAbsPath", () => {
  it("recognizes POSIX, Windows drive, and UNC absolute paths", () => {
    expect(isAbsPath("/a/b")).toBe(true);
    expect(isAbsPath("C:\\a\\b")).toBe(true);
    expect(isAbsPath("C:/a/b")).toBe(true);
    expect(isAbsPath("\\\\srv\\share")).toBe(true);
    expect(isAbsPath("subtitles/x.srt")).toBe(false);
    expect(isAbsPath("x.srt")).toBe(false);
  });
});

describe("buildNewsDeskPreview", () => {
  it("keeps only subtitle components whose snapshot SRT is on disk, keyed by srt_path", async () => {
    const fs = makeFs();
    fs.files.set(`${DIR}/subtitles/s1.srt`, "x");
    const comps = [
      { kind: "subtitle", id: "s1", srt_path: "subtitles/s1.srt" }, // on disk
      { kind: "subtitle", id: "s2", srt_path: "subtitles/missing.srt" }, // absent
      { kind: "subtitle", id: "s3", srt_path: "" }, // empty
      { kind: "chapter", id: "c1" }, // not a subtitle
    ];
    const r = await buildNewsDeskPreview(comps, DIR, fs, "/src/video.mp4", 42);
    expect(r.mediaRef).toBe("/src/video.mp4");
    expect(r.durationSec).toBe(42);
    expect(r.subtitlePaths).toEqual({ "subtitles/s1.srt": `${DIR}/subtitles/s1.srt` });
  });

  it("resolves an absolute srt_path as-is", async () => {
    const fs = makeFs();
    fs.files.set("/abs/ext.srt", "x");
    const comps = [{ kind: "subtitle", id: "s1", srt_path: "/abs/ext.srt" }];
    const r = await buildNewsDeskPreview(comps, DIR, fs, null, 0);
    expect(r.subtitlePaths).toEqual({ "/abs/ext.srt": "/abs/ext.srt" });
  });

  it("emptyNewsDeskPreview is the unbound shape", () => {
    expect(emptyNewsDeskPreview()).toEqual({ mediaRef: null, durationSec: 0, subtitlePaths: {} });
  });
});
