import { describe, expect, it } from "vitest";

import type { Fs, FsEntry, FsStat } from "../../renderer/ipc/fs";
import { NewsVideoModel, SLOT_NEWS_CONTEXT, SLOT_SOURCE, SLOT_SUBTITLES } from "./model";

/** In-memory Fs backing files in a Map; list() synthesizes immediate children
 * from path prefixes (flat — enough for subtitles/ listing). */
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
    async list(dir: string): Promise<FsEntry[]> {
      const prefix = `${dir}/`;
      const out: FsEntry[] = [];
      for (const k of files.keys()) {
        if (!k.startsWith(prefix)) continue;
        const rest = k.slice(prefix.length);
        if (!rest.includes("/")) out.push({ name: rest, isDir: false });
      }
      return out;
    },
    async copy(_s, d: string) {
      return d;
    },
    async stat(p: string): Promise<FsStat> {
      const t = files.get(p);
      return t === undefined ? { exists: false } : { exists: true, isDir: false, size: t.length };
    },
    async remove(p: string) {
      files.delete(p);
    },
    async presetsDir() {
      return "/presets";
    },
  };
}

const INST = "/proj/materials/news_video/news-1";

describe("NewsVideoModel", () => {
  it("derives paths from the instance dir", () => {
    const m = new NewsVideoModel(makeFs(), INST);
    expect(m.sourceDir).toBe(`${INST}/source`);
    expect(m.subtitlesDir).toBe(`${INST}/subtitles`);
    expect(m.sourceVideoPath).toBe(`${INST}/source/video.mp4`);
    expect(m.subtitlePath("zh")).toBe(`${INST}/subtitles/zh.srt`);
  });

  it("context write/read round-trips and reports completion", async () => {
    const fs = makeFs();
    const m = new NewsVideoModel(fs, INST);
    expect((await m.contextCompletion())).toEqual({ filled: 0, total: 15 });
    await m.writeContextDict({ host: "李四", episode_topic: "预算", junk: 1 });
    const ctx = await m.readContext();
    expect(ctx.host).toBe("李四");
    expect((ctx as Record<string, unknown>).junk).toBeUndefined();
    expect(await m.contextCompletion()).toEqual({ filled: 2, total: 15 });
  });

  it("basic_info write/read round-trips", async () => {
    const fs = makeFs();
    const m = new NewsVideoModel(fs, INST);
    await m.writeBasicInfoDict({ host: "张三" });
    expect((await m.readBasicInfo()).host).toBe("张三");
  });

  it("listSubtitleLanguages filters to <lang>.srt stems (2..8 letters/'-'), sorted", async () => {
    const fs = makeFs();
    const subs = `${INST}/subtitles`;
    for (const n of ["zh.srt", "en.srt", "zh-Hans.srt", "x.srt", "toolonglang.srt", "e2.srt", "notes.txt", "en.analysis.json"]) {
      fs.files.set(`${subs}/${n}`, "x");
    }
    expect(await new NewsVideoModel(fs, INST).listSubtitleLanguages()).toEqual(["en", "zh", "zh-Hans"]);
  });

  it("lists + summarizes analyses; malformed surfaces via error, never throws", async () => {
    const fs = makeFs();
    const subs = `${INST}/subtitles`;
    fs.files.set(`${subs}/zh.analysis.json`, JSON.stringify({
      chapters: [{ start: "00:00" }, { end: "12:30" }, { end: "20:00" }],
      titles: ["A", "  ", "B"],
    }));
    fs.files.set(`${subs}/en.analysis.json`, "{ not json");
    const m = new NewsVideoModel(fs, INST);
    expect(await m.listAnalyses()).toEqual(["en.analysis.json", "zh.analysis.json"]);

    const ok = await m.analysisSummary("zh.analysis.json");
    expect(ok.chapterCount).toBe(3);
    expect(ok.titleCount).toBe(2); // blank dropped
    expect(ok.startStr).toBe("00:00");
    expect(ok.endStr).toBe("20:00");
    expect(ok.error).toBe("");

    const bad = await m.analysisSummary("en.analysis.json");
    expect(bad.error).not.toBe("");
    expect(bad.chapterCount).toBe(0);
  });

  it("slotReadiness locks context/subtitles until source is ready", async () => {
    const fs = makeFs();
    const m = new NewsVideoModel(fs, INST);
    const r0 = await m.slotReadiness();
    expect(r0[SLOT_SOURCE].isFilled).toBe(false);
    expect(r0[SLOT_NEWS_CONTEXT].isLocked).toBe(true);
    expect(r0[SLOT_SUBTITLES].isLocked).toBe(true);

    // Source present + some context + a subtitle → all unlocked, structured facts.
    fs.files.set(m.sourceVideoPath, "video-bytes");
    await m.writeContextDict({ host: "李四" });
    fs.files.set(`${INST}/subtitles/zh.srt`, "1\n");
    const r = await m.slotReadiness({ title: "晚间新闻", durationSec: 225, width: 1920, height: 1080 });
    expect(r[SLOT_SOURCE].isFilled).toBe(true);
    expect(r[SLOT_SOURCE].source).toEqual({ title: "晚间新闻", durationSec: 225, width: 1920, height: 1080 });
    expect(r[SLOT_NEWS_CONTEXT].context).toEqual({ filled: 1, total: 15 });
    expect(r[SLOT_SUBTITLES].subtitles).toEqual({ langs: ["zh"] });
  });

  it("getArtifact resolves existing files, null for missing / unknown keys", async () => {
    const fs = makeFs();
    const m = new NewsVideoModel(fs, INST);
    expect(await m.getArtifact("source")).toBeNull(); // absent
    fs.files.set(m.sourceVideoPath, "v");
    fs.files.set(`${INST}/subtitles/zh.srt`, "1\n");
    fs.files.set(`${INST}/subtitles/zh.hotclips.json`, "{}");
    expect(await m.getArtifact("source")).toBe(m.sourceVideoPath);
    expect(await m.getArtifact("subtitle:zh")).toBe(`${INST}/subtitles/zh.srt`);
    expect(await m.getArtifact("analysis:zh:hotclips")).toBe(`${INST}/subtitles/zh.hotclips.json`);
    expect(await m.getArtifact("analysis:zh:nope")).toBeNull(); // unknown kind
    expect(await m.getArtifact("subtitle:en")).toBeNull(); // missing file
    expect(await m.getArtifact("bogus")).toBeNull();
  });
});
