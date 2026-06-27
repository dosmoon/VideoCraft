/**
 * News-desk import logic (ADR-0008 B4 TS port of `src/creations/news_desk/imports.py`).
 *
 * The "import subtitle / import chapters" flows: both pull from the bound material
 * and SNAPSHOT into this creation instance ([[project_snapshot_principle]]) — a
 * subtitle component copies the chosen language's SRT into the instance dir and
 * points its srt_path at it; a chapter component copies the analysis.json chapter
 * rows into its schedule. The single owner persists the mutation (owner.save()).
 *
 * Pure + injectable (owner + Fs + a minimal material accessor) so vitest drives it
 * with an in-memory Fs; bound-material resolution stays in clientBackend (RPC).
 *
 *   params {kind:"subtitle", lang}            — snapshot that language's SRT
 *   params {kind:"chapters", filename}        — fill schedule from analysis.json
 */

import type { Fs } from "../../renderer/ipc/fs";
import type { ComponentDict } from "./componentDefs";
import type { NewsDeskConfigOwner } from "./configOwner";

/** One importable dubbing version (a voice under a language). */
export interface DubImport {
  lang: string;
  id: number;
  name: string;
}

/** One dub version with its resolved source audio (model.dubVersions shape). */
interface DubVersionLite {
  id: number;
  name: string;
  audioPath: string;
}

/** The subset of NewsVideoModel imports needs (structural — lets vitest fake it). */
export interface ImportMaterial {
  listSubtitleLanguages(): Promise<string[]>;
  listAnalyses(): Promise<string[]>;
  subtitlePath(lang: string): string;
  readAnalysis(filename: string): Promise<Record<string, unknown>>;
  /** Synthesized dubbing versions (voices) for a language. */
  dubVersions(lang: string): Promise<DubVersionLite[]>;
}

export async function listNewsDeskImports(
  model: ImportMaterial,
): Promise<{ subtitleLangs: string[]; analyses: string[]; dubVersions: DubImport[] }> {
  const subtitleLangs = await model.listSubtitleLanguages();
  // Every dub version across all languages — one importable entry per voice.
  const dubVersions: DubImport[] = [];
  for (const lang of subtitleLangs) {
    try {
      for (const v of await model.dubVersions(lang)) dubVersions.push({ lang, id: v.id, name: v.name });
    } catch {
      /* skip a language whose dub manifest can't be read */
    }
  }
  return { subtitleLangs, analyses: await model.listAnalyses(), dubVersions };
}

/** Perform one import into a component and return the updated component dict.
 *  Mutates the owner in place and persists via owner.save(); `fs` is used for the
 *  SRT copy (same backing store the owner saves through). */
export async function importNewsDeskResource(
  owner: NewsDeskConfigOwner,
  fs: Fs,
  instanceDir: string,
  model: ImportMaterial,
  componentId: string,
  params: Record<string, unknown>,
): Promise<ComponentDict> {
  if (!params || typeof params !== "object") throw new Error("import params must be an object");
  const comp = owner.components.find((c) => c["id"] === componentId);
  if (!comp) throw new Error(`no component with id ${componentId}`);
  const kind = params["kind"];

  if (kind === "subtitle") {
    if (comp["kind"] !== "subtitle") throw new Error("import subtitle: component is not a subtitle");
    const lang = String(params["lang"] ?? "");
    const src = model.subtitlePath(lang);
    if (!(await fs.stat(src)).exists) throw new Error(`subtitle not found for language ${lang}`);
    const rel = `subtitles/${componentId}.srt`;
    await fs.copy(src, `${instanceDir}/${rel}`);
    comp["srt_path"] = rel;
    await owner.save();
    return comp;
  }

  if (kind === "dubbing") {
    if (comp["kind"] !== "dubbing") throw new Error("import dubbing: component is not a dubbing track");
    const lang = String(params["lang"] ?? "");
    const versionId = Number(params["version_id"] ?? -1);
    const v = (await model.dubVersions(lang)).find((x) => x.id === versionId);
    if (!v) throw new Error(`dubbing version not found: ${lang} #${versionId}`);
    if (!(await fs.stat(v.audioPath)).exists) throw new Error(`dubbing audio missing: ${v.audioPath}`);
    const rel = `audio/${componentId}.mp3`;
    await fs.copy(v.audioPath, `${instanceDir}/${rel}`);
    comp["audio_path"] = rel;
    await owner.save();
    return comp;
  }

  if (kind === "chapters") {
    if (comp["kind"] !== "chapter") throw new Error("import chapters: component is not a chapter");
    const filename = String(params["filename"] ?? "");
    let env: Record<string, unknown>;
    try {
      env = await model.readAnalysis(filename);
    } catch (e) {
      throw new Error(`read analysis failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    const chapters = Array.isArray(env["chapters"]) ? (env["chapters"] as unknown[]) : null;
    if (!chapters || chapters.length === 0) throw new Error("analysis has no chapters");
    comp["schedule"] = chapters
      .filter((ch): ch is Record<string, unknown> => !!ch && typeof ch === "object")
      .map((r) => ({
        start_sec: Number(r["start_sec"] ?? 0) || 0,
        end_sec: Number(r["end_sec"] ?? 0) || 0,
        title: String(r["title"] ?? ""),
        refined: String(r["refined"] ?? ""),
        key_points: Array.isArray(r["key_points"]) ? r["key_points"] : [],
      }));
    // Snapshot the AI-suggested video titles too: the same analysis call emits
    // both chapters and a top-level titles[]. publish.md's "Candidate Titles"
    // section reads them off the chapter component (render.ts), so without this
    // they silently never appear in the export.
    comp["titles"] = Array.isArray(env["titles"])
      ? (env["titles"] as unknown[]).map((t) => String(t).trim()).filter(Boolean)
      : [];
    await owner.save();
    return comp;
  }

  throw new Error(`unknown import kind: ${String(kind)}`);
}
