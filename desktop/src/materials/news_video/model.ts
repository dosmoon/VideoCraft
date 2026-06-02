/**
 * News-video material instance model — the data-layer single source of truth
 * (ADR-0008 TS port of `src/materials/news_video/model.py`, Phase B1).
 *
 * Owns the read side of one news_video instance: paths (via paths.ts), schema
 * read/write (context/basic_info via schema.ts), slot readiness, analyses, and
 * artifact resolution for creation plugins. Pure + Fs-backed so vitest can drive
 * it with an in-memory Fs; the instance dir is resolved upstream via the
 * `project.material_instance_dir` RPC and passed in.
 *
 * NOT ported here (they belong to the B2 capability gateway, not the data layer):
 * the business actions commit_source / ai_fill_context / run_asr / run_translate
 * / run_analysis / import_subtitle / quick_fix_subtitle / check_subtitle, plus
 * the project-meta accessors (source_language / translated_languages) — those
 * read project.meta, which the renderer already has via project.current.
 *
 * Deviation from model.py (intentional, [[feedback_i18n_symmetry]]): slotReadiness
 * returns STRUCTURED facts (filled/total counts, language list, source descriptor)
 * rather than the Python model's pre-formatted Chinese summary strings. UI text is
 * a renderer concern formatted via tr() at B3 wiring time — the data layer must
 * not emit user-facing strings ([[feedback_user_facing_naming]]).
 */

import type { Fs } from "../../renderer/ipc/fs";
import {
  CONTEXT_FIELDS,
  type SourceBasicInfo,
  type SourceContext,
  basicInfoFromDict,
  basicInfoPath,
  contextFromDict,
  contextPath,
  isEmpty,
  readBasicInfo,
  readContext,
  writeBasicInfo,
  writeContext,
} from "./schema";
import {
  sourceDir,
  sourceMetaPath,
  sourceStatus,
  sourceVideoPath,
  subtitlesDir,
} from "./paths";
import { ANALYSIS_TYPES, analysisFilename } from "./analysisTypes";

/** One existing analysis artifact on disk (camelCase; backend maps to the wire shape). */
export interface AnalysisArtifactInfo {
  kind: string;
  format: "json" | "md";
  icon: string;
  displayZh: string;
  displayEn: string;
  sizeBytes: number;
}

// ── Slot identifiers (stable strings the sidebar references) ──────────────────

export const SLOT_SOURCE = "source";
export const SLOT_NEWS_CONTEXT = "news_context";
export const SLOT_SUBTITLES = "subtitles";
export type SlotId = typeof SLOT_SOURCE | typeof SLOT_NEWS_CONTEXT | typeof SLOT_SUBTITLES;

/** Source descriptor + probe values from project meta (renderer supplies it;
 * the data layer does not read project.meta itself). */
export interface SourceMetaLike {
  title?: string;
  durationSec?: number;
  width?: number;
  height?: number;
}

/** One slot's render-ready state. Structured facts only — the renderer formats
 * the human-readable summary via tr() (see file header deviation note). */
export interface SlotState {
  slotId: SlotId;
  isLocked: boolean; // dependency not met (e.g. context locked w/o source)
  isFilled: boolean; // has data on disk
  source?: { title: string; durationSec?: number; width?: number; height?: number };
  context?: { filled: number; total: number };
  subtitles?: { langs: string[] };
}

/** Pre-import preview of an analysis.json (what a picker shows before commit).
 * `error` is set (and counts are 0) when the file failed to parse or was the
 * wrong shape. Mirrors model.py AnalysisSummary. */
export interface AnalysisSummary {
  filename: string;
  chapterCount: number;
  titleCount: number;
  startStr: string;
  endStr: string;
  error: string;
}

export class NewsVideoModel {
  constructor(
    private readonly fs: Fs,
    /** Absolute instance dir, resolved via project.material_instance_dir RPC. */
    public readonly instanceDir: string,
  ) {}

  // ── Identity / paths ────────────────────────────────────────────────────
  get sourceDir(): string {
    return sourceDir(this.instanceDir);
  }
  get subtitlesDir(): string {
    return subtitlesDir(this.instanceDir);
  }
  get sourceVideoPath(): string {
    return sourceVideoPath(this.instanceDir);
  }
  get sourceMetaPath(): string {
    return sourceMetaPath(this.instanceDir);
  }

  // ── Source video slot ─────────────────────────────────────────────────────
  async hasSourceVideo(): Promise<boolean> {
    return (await sourceStatus(this.fs, this.instanceDir)) === "ready";
  }

  // ── News context slot (basic_info + context) ──────────────────────────────
  readBasicInfo(): Promise<SourceBasicInfo> {
    return readBasicInfo(this.fs, this.sourceDir);
  }
  readContext(): Promise<SourceContext> {
    return readContext(this.fs, this.sourceDir);
  }

  /** Persist a plain context dict (sidecar shuttles JSON, never a dataclass —
   * keeps callers free of schema specifics). Returns the stored 15-field obj. */
  async writeContextDict(data: unknown): Promise<SourceContext> {
    const ctx = contextFromDict(data);
    await writeContext(this.fs, this.sourceDir, ctx);
    return ctx;
  }

  /** Persist a plain basic_info dict (the 5-field AI-fill seed). */
  async writeBasicInfoDict(data: unknown): Promise<SourceBasicInfo> {
    const info = basicInfoFromDict(data);
    await writeBasicInfo(this.fs, this.sourceDir, info);
    return info;
  }

  /** (filled, total) — drives the context-tab progress badge. */
  async contextCompletion(): Promise<{ filled: number; total: number }> {
    const ctx = await this.readContext();
    const filled = Object.values(ctx).filter((v) => typeof v === "string" && v.trim()).length;
    return { filled, total: CONTEXT_FIELDS.length };
  }

  // ── Subtitles slot ────────────────────────────────────────────────────────
  /** Sorted language codes for which <lang>.srt exists. Mirrors the Python
   * filter: .srt suffix (case-insensitive), stem 2..8 chars of letters/'-'. */
  async listSubtitleLanguages(): Promise<string[]> {
    const out: string[] = [];
    for (const e of await this.fs.list(this.subtitlesDir)) {
      if (e.isDir || !e.name.toLowerCase().endsWith(".srt")) continue;
      const stem = e.name.slice(0, -4);
      if (stem.length > 1 && stem.length <= 8 && /^[\p{L}-]+$/u.test(stem)) out.push(stem);
    }
    return out.sort();
  }

  subtitlePath(langIso: string): string {
    return `${this.subtitlesDir}/${langIso}.srt`;
  }
  async hasSubtitle(langIso: string): Promise<boolean> {
    return (await this.fs.stat(this.subtitlePath(langIso))).exists;
  }

  // ── Analysis artifacts (per-subtitle) ─────────────────────────────────────
  /** Filenames of `<iso>.analysis.json` artifacts on disk, sorted. */
  async listAnalyses(): Promise<string[]> {
    return (await this.fs.list(this.subtitlesDir))
      .filter((e) => !e.isDir && e.name.endsWith(".analysis.json"))
      .map((e) => e.name)
      .sort();
  }

  /** Raw analysis.json envelope. `filename` must be one listAnalyses() returned;
   * throws if the file vanished or is unreadable. */
  async readAnalysis(filename: string): Promise<Record<string, unknown>> {
    const env = await this.fs.readJson<Record<string, unknown>>(`${this.subtitlesDir}/${filename}`);
    if (env === null) throw new Error(`cannot read analysis ${filename}`);
    return env;
  }

  /** Quick summary for a UI picker. Never throws — malformed files surface via
   * the `error` field. Mirrors model.py analysis_summary. */
  async analysisSummary(filename: string): Promise<AnalysisSummary> {
    const base: AnalysisSummary = {
      filename,
      chapterCount: 0,
      titleCount: 0,
      startStr: "",
      endStr: "",
      error: "",
    };
    let env: unknown;
    try {
      env = await this.readAnalysis(filename);
    } catch (e) {
      return { ...base, error: e instanceof Error ? e.message : String(e) };
    }
    if (!env || typeof env !== "object") return { ...base, error: "envelope is not a dict" };
    const rec = env as Record<string, unknown>;
    const chapters = (rec.chapters ?? []) as unknown;
    const titles = (rec.titles ?? []) as unknown;
    if (!Array.isArray(chapters)) return { ...base, error: "chapters field is not a list" };
    let startStr = "";
    let endStr = "";
    if (chapters.length) {
      startStr = String((chapters[0] as Record<string, unknown> | null)?.start ?? "");
      endStr = String((chapters[chapters.length - 1] as Record<string, unknown> | null)?.end ?? "");
    }
    const titleCount = Array.isArray(titles)
      ? titles.filter((t) => typeof t === "string" && t.trim()).length
      : 0;
    return { ...base, chapterCount: chapters.length, titleCount, startStr, endStr };
  }

  /** Canonical path for an analysis artifact; null on unknown kind. */
  analysisPath(langIso: string, kind: string): string | null {
    const name = analysisFilename(langIso, kind);
    return name ? `${this.subtitlesDir}/${name}` : null;
  }

  /** Existing analysis artifacts for one subtitle language, in registry order
   * (port of core.subtitle_analysis.existing_artifacts). Each kind whose
   * `<lang>.<suffix>` file is present is returned with its display metadata. */
  async listAnalysisArtifacts(langIso: string): Promise<AnalysisArtifactInfo[]> {
    const out: AnalysisArtifactInfo[] = [];
    for (const t of ANALYSIS_TYPES) {
      const st = await this.fs.stat(`${this.subtitlesDir}/${langIso}.${t.suffix}`);
      if (st.exists && !st.isDir) {
        out.push({
          kind: t.kind,
          format: t.format,
          icon: t.icon,
          displayZh: t.displayZh,
          displayEn: t.displayEn,
          sizeBytes: st.size ?? 0,
        });
      }
    }
    return out;
  }

  // ── Slot readiness (drives sidebar tree rendering) ────────────────────────
  /** One SlotState per top-level slot. `sourceMeta` is the project-meta source
   * descriptor (renderer supplies it). Structured facts only — see header. */
  async slotReadiness(sourceMeta: SourceMetaLike = {}): Promise<Record<SlotId, SlotState>> {
    const srcReady = await this.hasSourceVideo();

    const src: SlotState = srcReady
      ? {
          slotId: SLOT_SOURCE,
          isLocked: false,
          isFilled: true,
          source: {
            title: sourceMeta.title || "video.mp4",
            ...(sourceMeta.durationSec != null ? { durationSec: sourceMeta.durationSec } : {}),
            ...(sourceMeta.width != null ? { width: sourceMeta.width } : {}),
            ...(sourceMeta.height != null ? { height: sourceMeta.height } : {}),
          },
        }
      : { slotId: SLOT_SOURCE, isLocked: false, isFilled: false };

    let ctx: SlotState;
    if (!srcReady) {
      ctx = { slotId: SLOT_NEWS_CONTEXT, isLocked: true, isFilled: false };
    } else {
      const completion = await this.contextCompletion();
      ctx = {
        slotId: SLOT_NEWS_CONTEXT,
        isLocked: false,
        isFilled: completion.filled > 0,
        context: completion,
      };
    }

    let subs: SlotState;
    if (!srcReady) {
      subs = { slotId: SLOT_SUBTITLES, isLocked: true, isFilled: false };
    } else {
      const langs = await this.listSubtitleLanguages();
      subs = {
        slotId: SLOT_SUBTITLES,
        isLocked: false,
        isFilled: langs.length > 0,
        subtitles: { langs },
      };
    }

    return { [SLOT_SOURCE]: src, [SLOT_NEWS_CONTEXT]: ctx, [SLOT_SUBTITLES]: subs };
  }

  // ── Artifact resolver (for creation plugins per ADR-0005) ─────────────────
  /** Resolve an artifact key to an absolute file path; null if absent.
   *
   *   source                  → source/video.mp4
   *   source_meta             → source/meta.json
   *   basic_info              → source/basic_info.json
   *   context                 → source/context.json
   *   subtitle:<lang>         → subtitles/<lang>.srt
   *   analysis:<lang>:<kind>  → subtitles/<lang>.<suffix>
   */
  async getArtifact(key: string): Promise<string | null> {
    const path = this.artifactPath(key);
    if (path === null) return null;
    return (await this.fs.stat(path)).exists ? path : null;
  }

  private artifactPath(key: string): string | null {
    if (key === "source") return this.sourceVideoPath;
    if (key === "source_meta") return this.sourceMetaPath;
    if (key === "basic_info") return basicInfoPath(this.sourceDir);
    if (key === "context") return contextPath(this.sourceDir);
    if (key.startsWith("subtitle:")) return this.subtitlePath(key.slice("subtitle:".length));
    if (key.startsWith("analysis:")) {
      const [, lang, kind] = key.split(":");
      if (lang === undefined || kind === undefined || key.split(":").length !== 3) return null;
      return this.analysisPath(lang, kind);
    }
    return null;
  }
}

/** Convenience for callers that already know if context is empty. */
export { isEmpty };
