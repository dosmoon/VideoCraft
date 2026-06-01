import { describe, expect, it } from "vitest";

import type { Fs, FsStat } from "../../renderer/ipc/fs";
import {
  SOURCE_META_FILENAME,
  SOURCE_VIDEO_FILENAME,
  sourceDir,
  sourceMetaPath,
  sourceStatus,
  sourceVideoPath,
  subtitlesDir,
} from "./paths";

/** Minimal Fs whose stat reports byte-size from a seeded map (for sourceStatus). */
function makeFs(sizes: Record<string, number> = {}): Fs {
  return {
    async readJson() {
      return null;
    },
    async writeJson(p) {
      return p;
    },
    async readText() {
      return null;
    },
    async writeText(p) {
      return p;
    },
    async list() {
      return [];
    },
    async copy(_s, d) {
      return d;
    },
    async stat(p: string): Promise<FsStat> {
      return p in sizes ? { exists: true, isDir: false, size: sizes[p] ?? 0 } : { exists: false };
    },
    async remove() {},
    async presetsDir() {
      return "/presets";
    },
  };
}

describe("news_video paths", () => {
  const inst = "/proj/materials/news_video/news-1";

  it("derives slot dirs and well-known files from the instance dir", () => {
    expect(sourceDir(inst)).toBe(`${inst}/source`);
    expect(subtitlesDir(inst)).toBe(`${inst}/subtitles`);
    expect(sourceVideoPath(inst)).toBe(`${inst}/source/${SOURCE_VIDEO_FILENAME}`);
    expect(sourceMetaPath(inst)).toBe(`${inst}/source/${SOURCE_META_FILENAME}`);
  });

  it("sourceStatus is ready only for a non-empty video file", async () => {
    expect(await sourceStatus(makeFs(), inst)).toBe("missing"); // absent
    expect(await sourceStatus(makeFs({ [sourceVideoPath(inst)]: 0 }), inst)).toBe("missing"); // empty
    expect(await sourceStatus(makeFs({ [sourceVideoPath(inst)]: 12345 }), inst)).toBe("ready");
  });
});
