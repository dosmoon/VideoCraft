import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import { fmtDur, fmtHashtags, isZh, t } from "../shared/markdownFmt";
import { collectClipSidecars, renderClipIndex, renderClipPublish } from "./publish";

describe("markdownFmt", () => {
  it("fmtDur", () => {
    expect(fmtDur(5)).toBe("0:05");
    expect(fmtDur(75)).toBe("1:15");
    expect(fmtDur(3661)).toBe("1:01:01");
    expect(fmtDur(-3)).toBe("0:00");
  });
  it("fmtHashtags", () => {
    expect(fmtHashtags(["a", "#b", " c "])).toBe("#a #b #c");
    expect(fmtHashtags("nope")).toBe("");
    expect(fmtHashtags([])).toBe("");
  });
  it("isZh / t pick by source language", () => {
    expect(isZh("zh-CN")).toBe(true);
    expect(isZh("en")).toBe(false);
    expect(t("zh", "中", "en")).toBe("中");
    expect(t("en", "中", "EN")).toBe("EN");
  });
});

describe("renderClipPublish", () => {
  const sidecar = {
    output_index: 1,
    filename: "clip_001_H.mp4",
    title: "My Clip",
    hashtags: ["viral", "fyp"],
    hook: "Wait for it",
    outro: "Follow for more",
    transcript: "the spoken words",
    why_viral: "surprising",
    duration_sec: 20,
    start_sec: 60,
    end_sec: 80,
    score: 9,
  };

  it("English: caption block + hook + source footer", () => {
    const md = renderClipPublish({ projectTitle: "Src", sidecar, langIso: "en" });
    expect(md).toContain("# My Clip");
    expect(md).toContain("Duration 0:20");
    expect(md).toContain("Score 9/10");
    expect(md).toContain("## Hook");
    expect(md).toContain("Caption (copy to X / TikTok)");
    expect(md).toContain("the spoken words");
    expect(md).toContain("#viral #fyp");
    expect(md).toContain("Source: clip_001.mp4 · 1:00 – 1:20 · Src");
    expect(md.endsWith("\n")).toBe(true);
  });

  it("Chinese localization + no-title fallback", () => {
    const md = renderClipPublish({ projectTitle: null, sidecar: { duration_sec: 5 }, langIso: "zh" });
    expect(md).toContain("# （无标题）");
    expect(md).toContain("时长 0:05");
    expect(md).not.toContain("评分"); // no score
  });
});

describe("renderClipIndex", () => {
  it("table rows sorted by output_index; missing filename → dash", () => {
    const md = renderClipIndex({
      projectTitle: "Proj",
      instanceName: "inst",
      sidecars: [
        { output_index: 2, title: "B", duration_sec: 10, score: 7, filename: "clip_002_x.mp4" },
        { output_index: 1, title: "A", duration_sec: 5, score: 8 }, // no filename
      ],
      renderedAt: "2026-06-01 19:00",
      langIso: "en",
    });
    const lines = md.split("\n").filter((l) => l.startsWith("| 0"));
    expect(lines[0]).toContain("001"); // sorted: 001 before 002
    expect(lines[0]).toContain("| — | — |"); // no filename → dashes
    expect(lines[1]).toContain("[clip_002_x.mp4](clip_002_x.mp4)");
    expect(lines[1]).toContain("[clip_002_x.md](clip_002_x.md)");
  });

  it("empty → (no clips yet)", () => {
    const md = renderClipIndex({ projectTitle: "P", instanceName: "i", sidecars: [], renderedAt: null, langIso: "en" });
    expect(md).toContain("(no clips yet)");
  });
});

describe("collectClipSidecars", () => {
  it("reads clip_*.json, sorts by output_index, ignores others", async () => {
    const files = new Map<string, string>([
      ["/inst/clip_002.json", JSON.stringify({ output_index: 2 })],
      ["/inst/clip_001.json", JSON.stringify({ output_index: 1 })],
      ["/inst/config.json", JSON.stringify({ not: "a clip" })],
    ]);
    const fs = {
      async list() {
        return [
          { name: "clip_002.json", isDir: false },
          { name: "clip_001.json", isDir: false },
          { name: "config.json", isDir: false },
        ];
      },
      async readJson<T>(p: string): Promise<T | null> {
        const t2 = files.get(p);
        return t2 === undefined ? null : (JSON.parse(t2) as T);
      },
    } as unknown as Fs;

    const out = await collectClipSidecars(fs, "/inst");
    expect(out.map((s) => s["output_index"])).toEqual([1, 2]);
  });
});
