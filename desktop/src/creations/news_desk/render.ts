/**
 * News-desk render orchestration (ADR-0008 TS port of
 * `src/creations/news_desk/export.py`).
 *
 * Single full-source output (out_idx always 1): plan → the renderer encodes
 * output.mp4 → commitRender writes the sidecar JSON + rendered[] + best-effort
 * publish.md. The GPU encode stays in the renderer; this owns the render state.
 *
 * publish.md reads the bound material's context.json (passed in — the clip
 * backend resolves it via the material.read_context bridge in Phase A), the
 * snapshotted chapter schedule (in config), the subtitle components' snapshot
 * SRTs (read via fs), and the project meta. Content language follows the source.
 */

import type { Fs } from "../../renderer/ipc/fs";
import type { ComponentDict } from "./componentDefs";
import type { NewsDeskConfigOwner } from "./configOwner";
import { renderNewsDeskPublish, type PublishChapter, type TranscriptCue } from "./publish";

const OUT_IDX = 1;
const BASENAME = "output";

function isoSeconds(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}
function localStamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** Seconds → HH:MM:SS (faithful to core.chapters_io.fmt_time_str). */
function fmtTimeStr(sec: number): string {
  const total = Math.max(0, Math.trunc(sec));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.trunc(total / 3600))}:${p(Math.trunc((total % 3600) / 60))}:${p(total % 60)}`;
}
function parseSrtCues(text: string): TranscriptCue[] {
  const cues: TranscriptCue[] = [];
  for (const block of text.replace(/\r/g, "").split(/\n\n+/)) {
    const lines = block.split("\n").filter((l) => l.trim() !== "");
    const tIdx = lines.findIndex((l) => l.includes("-->"));
    if (tIdx < 0) continue;
    const m = /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/.exec(lines[tIdx]!);
    if (!m) continue;
    const startSec = +m[1]! * 3600 + +m[2]! * 60 + +m[3]! + +m[4]! / 1000;
    cues.push({ startSec, text: lines.slice(tIdx + 1).join(" ").trim() });
  }
  return cues;
}

export interface NewsDeskRenderPlan {
  instanceDir: string;
  mediaRef: string | null;
  durationSec: number;
  outIdx: number;
  outputPath: string;
}

/** The single full-source render: media reference + output path. */
export function planRender(instanceDir: string, mediaRef: string | null, durationSec: number): NewsDeskRenderPlan {
  return { instanceDir, mediaRef, durationSec, outIdx: OUT_IDX, outputPath: `${instanceDir}/${BASENAME}.mp4` };
}

export interface NewsDeskRenderCtx {
  owner: NewsDeskConfigOwner;
  fs: Fs;
  instanceDir: string;
  /** Bound material context.json (15 fields), or {} when AI Fill hasn't run. */
  context: Record<string, unknown>;
  projectTitle: string | null;
  sourceUrl: string | null;
  /** Project source language (fallback when no subtitle component picks one). */
  langIso: string;
}

export async function commitRender(ctx: NewsDeskRenderCtx, durationSec: number): Promise<ComponentDict[]> {
  const { owner, fs, instanceDir } = ctx;
  const filename = BASENAME + ".mp4";
  const renderedAt = isoSeconds();
  await fs.writeJson(`${instanceDir}/${BASENAME}.json`, {
    output_index: OUT_IDX,
    filename,
    duration_sec: durationSec,
    rendered_at: renderedAt,
  });
  owner.rendered = [{ file: filename, output_index: OUT_IDX, duration_sec: durationSec, rendered_at: renderedAt }];
  await owner.save();

  try {
    await writePublish(ctx);
  } catch {
    // publish.md is nice-to-have, never blocks the render
  }
  return owner.rendered;
}

export async function deleteRender(ctx: Omit<NewsDeskRenderCtx, "context" | "projectTitle" | "sourceUrl" | "langIso">): Promise<ComponentDict[]> {
  const { owner, fs, instanceDir } = ctx;
  for (const name of [BASENAME + ".mp4", BASENAME + ".json", "publish.md"]) {
    try {
      await fs.remove(`${instanceDir}/${name}`);
    } catch {
      // best-effort
    }
  }
  owner.rendered = [];
  await owner.save();
  return owner.rendered;
}

// ── publish.md ────────────────────────────────────────────────────────────────

function chapterComponent(owner: NewsDeskConfigOwner): ComponentDict | undefined {
  return owner.components.find((c) => c["kind"] === "chapter");
}
function firstEnabledSubtitle(owner: NewsDeskConfigOwner): ComponentDict | undefined {
  return owner.components.find((c) => c["kind"] === "subtitle" && (c["enabled"] ?? true));
}

function chaptersForPublish(schedule: unknown): PublishChapter[] {
  if (!Array.isArray(schedule)) return [];
  return schedule.map((ch) => {
    const c = ch as Record<string, unknown>;
    const startSec = Number(c["start_sec"] ?? 0);
    const endSec = Number(c["end_sec"] ?? 0);
    return {
      start: fmtTimeStr(startSec),
      end: fmtTimeStr(endSec),
      start_sec: startSec,
      end_sec: endSec,
      title: String(c["title"] ?? ""),
      refined: String(c["refined"] ?? ""),
      key_points: Array.isArray(c["key_points"]) ? (c["key_points"] as unknown[]) : [],
    };
  });
}

async function readSubtitleCues(fs: Fs, instanceDir: string, comp: ComponentDict | undefined): Promise<TranscriptCue[]> {
  if (!comp) return [];
  const rel = String(comp["srt_path"] ?? "").trim();
  if (!rel) return [];
  const abs = rel.match(/^([a-zA-Z]:[\\/]|[\\/])/) ? rel : `${instanceDir}/${rel}`;
  const text = await fs.readText(abs);
  return text ? parseSrtCues(text) : [];
}

async function writePublish(ctx: NewsDeskRenderCtx): Promise<void> {
  const { owner, fs, instanceDir } = ctx;
  const chapterComp = chapterComponent(owner);
  const chapters = chaptersForPublish(chapterComp?.["schedule"]);
  const candidateTitles = (Array.isArray(chapterComp?.["titles"]) ? (chapterComp!["titles"] as unknown[]) : [])
    .map((t) => String(t).trim())
    .filter(Boolean);

  const subComp = firstEnabledSubtitle(owner);
  const langIso = subComp ? (subComp["is_chinese"] ? "zh" : "en") : ctx.langIso;
  const adaptedSrts = owner.components
    .filter((c) => c["kind"] === "subtitle" && c["srt_path"])
    .map((c) => String(c["srt_path"]));
  const transcriptCues = await readSubtitleCues(fs, instanceDir, subComp);

  const md = renderNewsDeskPublish({
    projectTitle: ctx.projectTitle,
    sourceUrl: ctx.sourceUrl,
    context: ctx.context,
    chapters,
    candidateTitles,
    adaptedSrts,
    renderedAt: localStamp(),
    langIso,
    transcriptCues,
  });
  await fs.writeText(`${instanceDir}/publish.md`, md);
}
