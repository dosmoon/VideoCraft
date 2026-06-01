/**
 * Clip render orchestration (ADR-0008 TS port of `src/creations/clip/export.py`).
 *
 * The GPU encode runs in the renderer; this module owns what the Python export
 * provider used to: which candidates to render, output paths + naming
 * (clip_NNN[_hook]), the per-clip sidecar JSON, stale-file cleanup, the persisted
 * rendered[] state, and (best-effort) the publish.md / index.md docs.
 *
 * Faithful to export.py's _clip_basename / _sanitize_filename_part /
 * _existing_clip_files / the sidecar dict / _effective_* override-wins, plus the
 * publish wiring restored in the news_desk/clip publish.md work.
 */

import type { Fs } from "../../renderer/ipc/fs";
import type { ClipConfigOwner } from "./configOwner";
import type { ComponentDict } from "./componentDefs";
import { collectClipSidecars, renderClipIndex, renderClipPublish } from "./publish";

type Candidate = Record<string, unknown>;
type Override = Record<string, unknown>;

const TS_RE = /^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$/;

function parseTs(s: unknown): number {
  const m = TS_RE.exec(String(s ?? "").trim());
  if (!m) return 0;
  const h = parseInt(m[1] || "0", 10);
  const mn = parseInt(m[2]!, 10);
  const sec = parseInt(m[3]!, 10);
  let base = h * 3600 + mn * 60 + sec;
  if (m[4]) base += parseInt(m[4].slice(0, 3).padEnd(3, "0"), 10) / 1000;
  return base;
}

function sanitizeFilenamePart(text: string, maxLen = 30): string {
  if (!text) return "";
  let t = text.replace(/[<>:"/\\|?*\x00-\x1f]/g, "");
  t = t.replace(/\s+/g, " ").trim().replace(/[. ]+$/, "");
  if (t.length > maxLen) t = t.slice(0, maxLen).replace(/[. ]+$/, "");
  return t;
}

function basename(outIdx: number, hook: string): string {
  const suffix = sanitizeFilenamePart(hook || "");
  const idx = String(outIdx).padStart(3, "0");
  return suffix ? `clip_${idx}_${suffix}` : `clip_${idx}`;
}

// ── effective values (override-wins, faithful to export.py._eff_*) ───────────

function effStartEnd(cand: Candidate, ov: Override): [number, number] {
  const start = ov["start_sec"] != null ? Number(ov["start_sec"]) : parseTs(cand["start"]);
  const end = ov["end_sec"] != null ? Number(ov["end_sec"]) : parseTs(cand["end"]);
  return [start, end];
}
function effHook(cand: Candidate, ov: Override): string {
  return "hook_text" in ov ? String(ov["hook_text"]) : String(cand["hook"] ?? "").trim();
}
function effOutro(cand: Candidate, ov: Override): string {
  return "outro_text" in ov ? String(ov["outro_text"]) : String(cand["outro"] ?? "").trim();
}
function effTitle(cand: Candidate, ov: Override): string {
  return "title" in ov ? String(ov["title"]) : String(cand["suggested_title"] ?? "").trim();
}
function effTags(cand: Candidate, ov: Override): string[] {
  if ("hashtags" in ov) {
    const t = ov["hashtags"];
    if (Array.isArray(t)) return t.map(String);
    if (typeof t === "string") return t.split(/\s+/).filter(Boolean);
    return [];
  }
  const t = cand["suggested_hashtags"] ?? cand["hashtags"] ?? [];
  return Array.isArray(t) ? t.map(String) : [];
}

function existingClipFiles(entries: { name: string }[], outIdx: number): string[] {
  const prefix = `clip_${String(outIdx).padStart(3, "0")}`;
  const out: string[] = [];
  for (const e of entries) {
    if (!e.name.startsWith(prefix)) continue;
    const tail = e.name.slice(prefix.length);
    if (tail && !(tail.startsWith(".") || tail.startsWith("_"))) continue;
    if (!(e.name.endsWith(".mp4") || e.name.endsWith(".json") || e.name.endsWith(".md"))) continue;
    out.push(e.name);
  }
  return out;
}

// ── plan ─────────────────────────────────────────────────────────────────────

export interface RenderClip {
  srcIdx: number;
  outIdx: number;
  outputPath: string;
  startSec: number;
  endSec: number;
  cropRect: Record<string, unknown> | null;
}
export interface RenderPlan {
  lang: string;
  mode: string;
  aspect: string;
  shortEdge: number;
  instanceDir: string;
  clips: RenderClip[];
}

/** Output paths + geometry for the selected candidates (ascending → out_idx 1..N). */
export function planRender(owner: ClipConfigOwner, instanceDir: string, candidates: Candidate[]): RenderPlan {
  const selected = [...owner.selectedClipIndices].filter((i) => i >= 0 && i < candidates.length).sort((a, b) => a - b);
  const clips: RenderClip[] = [];
  selected.forEach((srcIdx, i) => {
    const cand = candidates[srcIdx]!;
    const ov = owner.clipsOverrides[String(srcIdx)] ?? {};
    const [start, end] = effStartEnd(cand, ov);
    const crop = ov["crop_rect"];
    clips.push({
      srcIdx,
      outIdx: i + 1,
      outputPath: `${instanceDir}/${basename(i + 1, effHook(cand, ov))}.mp4`,
      startSec: start,
      endSec: end,
      cropRect: crop && typeof crop === "object" ? (crop as Record<string, unknown>) : null,
    });
  });
  return {
    lang: owner.sourceSubtitle,
    mode: owner.outputMode,
    aspect: owner.outputAspect,
    shortEdge: Math.trunc(owner.outputShortEdge),
    instanceDir,
    clips,
  };
}

// ── commit / delete (mutate + persist owner.rendered; write sidecar + docs) ──

function isoSeconds(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}
function localStamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export interface RenderCtx {
  owner: ClipConfigOwner;
  fs: Fs;
  instanceDir: string;
  candidates: Candidate[];
  projectTitle: string | null;
  langIso: string;
}

/** Write the per-clip sidecar JSON, clean stale files for this out_idx, record
 *  rendered[], emit publish.md + index.md, and persist the owner. */
export async function commitRender(ctx: RenderCtx, srcIdx: number, outIdx: number, durationSec: number): Promise<ComponentDict[]> {
  const { owner, fs, instanceDir } = ctx;
  const cand = srcIdx >= 0 && srcIdx < ctx.candidates.length ? ctx.candidates[srcIdx]! : {};
  const ov = owner.clipsOverrides[String(srcIdx)] ?? {};
  const [start, end] = effStartEnd(cand, ov);
  const base = basename(outIdx, effHook(cand, ov));
  const filename = base + ".mp4";
  const renderedAt = isoSeconds();

  const sidecar: ComponentDict = {
    source_clip_idx: srcIdx,
    output_index: outIdx,
    filename,
    title: effTitle(cand, ov),
    hashtags: effTags(cand, ov),
    hook: effHook(cand, ov),
    outro: effOutro(cand, ov),
    transcript: cand["transcript"] ?? "",
    why_viral: cand["why_viral"] ?? "",
    duration_sec: durationSec,
    start_sec: start,
    end_sec: end,
    score: cand["score"] ?? null,
    rendered_at: renderedAt,
  };
  await fs.writeJson(`${instanceDir}/${base}.json`, sidecar);

  // Stale cleanup: drop older files for this out_idx under a different basename.
  const keep = new Set([base + ".mp4", base + ".json", base + ".md"]);
  let entries: { name: string }[] = [];
  try {
    entries = await fs.list(instanceDir);
  } catch {
    entries = [];
  }
  for (const name of existingClipFiles(entries, outIdx)) {
    if (!keep.has(name)) {
      try {
        await fs.remove(`${instanceDir}/${name}`);
      } catch {
        // best-effort
      }
    }
  }

  // rendered[]: newest first, one entry per out_idx.
  const rendered = owner.rendered.filter((r) => Number(r["output_index"]) !== outIdx);
  rendered.unshift({ file: filename, source_clip_idx: srcIdx, output_index: outIdx, duration_sec: durationSec, rendered_at: renderedAt });
  owner.rendered = rendered;
  await owner.save();

  // Publish docs — best-effort, never blocks (the mp4 + state are committed).
  try {
    await writeClipPublish(ctx, base, sidecar);
  } catch {
    // publish.md is nice-to-have
  }
  return rendered;
}

/** Unlink all files for an output index, rebuild index.md, drop from rendered[]. */
export async function deleteRender(ctx: Omit<RenderCtx, "candidates">, outIdx: number): Promise<ComponentDict[]> {
  const { owner, fs, instanceDir } = ctx;
  let entries: { name: string }[] = [];
  try {
    entries = await fs.list(instanceDir);
  } catch {
    entries = [];
  }
  for (const name of existingClipFiles(entries, outIdx)) {
    try {
      await fs.remove(`${instanceDir}/${name}`);
    } catch {
      // best-effort
    }
  }
  owner.rendered = owner.rendered.filter((r) => Number(r["output_index"]) !== outIdx);
  await owner.save();
  try {
    await rebuildClipIndex(ctx);
  } catch {
    // index.md is nice-to-have
  }
  return owner.rendered;
}

// ── publish docs ─────────────────────────────────────────────────────────────

async function writeClipPublish(ctx: RenderCtx | Omit<RenderCtx, "candidates">, base: string, sidecar: ComponentDict): Promise<void> {
  const md = renderClipPublish({ projectTitle: ctx.projectTitle, sidecar, langIso: ctx.langIso });
  await ctx.fs.writeText(`${ctx.instanceDir}/${base}.md`, md);
  await rebuildClipIndex(ctx);
}

async function rebuildClipIndex(ctx: Pick<RenderCtx, "owner" | "fs" | "instanceDir" | "projectTitle" | "langIso">): Promise<void> {
  const sidecars = await collectClipSidecars(ctx.fs, ctx.instanceDir);
  const instanceName = ctx.instanceDir.split(/[\\/]/).filter(Boolean).pop() ?? "";
  const indexMd = renderClipIndex({
    projectTitle: ctx.projectTitle,
    instanceName,
    sidecars,
    renderedAt: localStamp(),
    langIso: ctx.langIso,
  });
  await ctx.fs.writeText(`${ctx.instanceDir}/index.md`, indexMd);
}
