import { describe, expect, it } from "vitest";

import type { Fs } from "../../renderer/ipc/fs";
import {
  basicInfoFromDict,
  contextFromDict,
  isEmpty,
  readContext,
  writeContext,
  CONTEXT_FIELDS,
} from "./schema";

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
    async readText() {
      return null;
    },
    async writeText(p: string, t: string): Promise<string> {
      files.set(p, t);
      return p;
    },
    async list() {
      return [];
    },
    async copy(_s, d: string) {
      return d;
    },
    async stat(p: string) {
      return files.has(p) ? { exists: true, isDir: false, size: 0, mtimeMs: 0 } : { exists: false };
    },
    async remove(p: string) {
      files.delete(p);
    },
    async presetsDir() {
      return "/presets";
    },
  };
}

describe("news_video schema", () => {
  it("fromDict keeps known string fields, defaults the rest, drops junk", () => {
    const ctx = contextFromDict({ host: "张三", guests: 42, unknown_x: "y" });
    expect(ctx.host).toBe("张三");
    expect(ctx.guests).toBe(""); // non-string dropped → default
    expect(Object.keys(ctx).sort()).toEqual([...CONTEXT_FIELDS].sort());
    expect((ctx as Record<string, unknown>)["unknown_x"]).toBeUndefined();
  });

  it("isEmpty", () => {
    expect(isEmpty(basicInfoFromDict({}))).toBe(true);
    expect(isEmpty(basicInfoFromDict({ host: " " }))).toBe(true);
    expect(isEmpty(basicInfoFromDict({ host: "x" }))).toBe(false);
  });

  it("read/write context round-trips via Fs", async () => {
    const fs = makeFs();
    const dir = "/proj/material/n1/source";
    expect(isEmpty(await readContext(fs, dir))).toBe(true); // missing → empty
    await writeContext(fs, dir, contextFromDict({ host: "李四", episode_topic: "预算" }));
    const back = await readContext(fs, dir);
    expect(back.host).toBe("李四");
    expect(back.episode_topic).toBe("预算");
    expect(back.notes).toBe("");
  });
});
