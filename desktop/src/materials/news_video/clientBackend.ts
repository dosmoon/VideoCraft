/**
 * News-video material backend — TS owner behind the `material.*` client surface
 * (ADR-0008 Phase B3.2). Mirrors the creation-side clientBackend pattern: client.ts
 * dispatches `type === "news_video"` here instead of the Python sidecar.
 *
 * B3.2a scope = the PURE READ methods only. They go through NewsVideoModel over the
 * real (main-process) fs and read the very files the Python writers still produce,
 * so disk stays the single source of truth while reads and writes straddle the two
 * paths. Wire shapes match the existing client.ts types exactly (e.g. analysisSummary
 * is mapped back to snake_case) so the workbench tabs are unchanged.
 *
 * Still on Python (next increments / Phase A bridge): writes + sync QC (their
 * event.material.changed refresh needs renderer-side handling once capability.* —
 * which emits no domain events — backs them), all long jobs + the ai_fill
 * recomposition (B3.2b), slotReadiness (needs the Hub summary i18n reshape),
 * source_meta + importSubtitle (project.meta), listAnalysisArtifacts (analysis
 * registry not yet ported to TS).
 */

import { realFs } from "../../renderer/ipc/fs";
import { rpcCall } from "../../renderer/ipc/client";
import type {
  AnalysisSummary,
  ProjectBrief,
  SourceBasicInfo,
  SourceContext,
  SubtitleCheck,
} from "../../renderer/ipc/client";
import { NewsVideoModel } from "./model";

async function loadModel(instance: string): Promise<NewsVideoModel> {
  const dir = await rpcCall<string>("project.material_instance_dir", {
    type: "news_video",
    instance,
  });
  return new NewsVideoModel(realFs, dir);
}

/** The project's source language (for the subtitle-check reference). Read from
 * project meta — the data layer doesn't carry it. "" when unset. */
async function projectSourceLang(): Promise<string> {
  const cur = await rpcCall<ProjectBrief | null>("project.current");
  const meta = (cur?.meta ?? {}) as { language?: { source?: string } };
  return meta.language?.source ?? "";
}

async function fileExists(path: string): Promise<boolean> {
  return (await realFs.stat(path)).exists;
}

/** Map the model's camelCase AnalysisSummary back to the snake_case wire shape the
 * workbench/pickers expect (faithful to material.analysis_summary). */
function summaryToWire(s: Awaited<ReturnType<NewsVideoModel["analysisSummary"]>>): AnalysisSummary {
  return {
    filename: s.filename,
    chapter_count: s.chapterCount,
    title_count: s.titleCount,
    start_str: s.startStr,
    end_str: s.endStr,
    error: s.error,
  };
}

export const materialBackend = {
  readContext: async (instance: string): Promise<SourceContext> =>
    (await loadModel(instance)).readContext() as Promise<SourceContext>,

  contextCompletion: async (instance: string): Promise<{ filled: number; total: number }> =>
    (await loadModel(instance)).contextCompletion(),

  listSubtitleLanguages: async (instance: string): Promise<string[]> =>
    (await loadModel(instance)).listSubtitleLanguages(),

  readSubtitle: async (instance: string, lang: string): Promise<{ text: string }> => {
    const m = await loadModel(instance);
    const text = await realFs.readText(m.subtitlePath(lang));
    if (text === null) throw new Error(`no subtitle for language ${lang}`);
    return { text };
  },

  getArtifact: async (instance: string, key: string): Promise<string | null> =>
    (await loadModel(instance)).getArtifact(key),

  listAnalyses: async (instance: string): Promise<string[]> =>
    (await loadModel(instance)).listAnalyses(),

  analysisSummary: async (instance: string, filename: string): Promise<AnalysisSummary> =>
    summaryToWire(await (await loadModel(instance)).analysisSummary(filename)),

  readAnalysis: async (instance: string, filename: string): Promise<Record<string, unknown>> =>
    (await loadModel(instance)).readAnalysis(filename),

  readAnalysisText: async (instance: string, lang: string, kind: string): Promise<{ text: string }> => {
    const m = await loadModel(instance);
    const path = m.analysisPath(lang, kind);
    if (path === null) throw new Error(`unknown analysis kind: ${kind}`);
    const text = await realFs.readText(path);
    if (text === null) throw new Error(`analysis artifact missing: ${lang}.${kind}`);
    return { text };
  },

  // ── Writes + sync QC (B3.2b) ──────────────────────────────────────────────
  // Hub-sidebar refresh after a mutation rides the workbench's onChanged →
  // emitLocal("event.material.changed") path (MaterialWorkbench), the single
  // mechanism that also covers async jobs; capability.* emits no domain events.

  writeContext: async (instance: string, context: SourceContext): Promise<SourceContext> =>
    (await (await loadModel(instance)).writeContextDict(context)) as SourceContext,

  writeBasicInfo: async (instance: string, basicInfo: SourceBasicInfo): Promise<SourceBasicInfo> =>
    (await (await loadModel(instance)).writeBasicInfoDict(basicInfo)) as SourceBasicInfo,

  checkSubtitle: async (instance: string, lang: string): Promise<SubtitleCheck> => {
    const m = await loadModel(instance);
    // Reference = the project source-language SRT (cue-count parity), when it
    // exists and differs from the checked language — mirrors model.check_subtitle.
    const src = await projectSourceLang();
    const refPath = src && src !== lang ? m.subtitlePath(src) : null;
    const reference = refPath && (await fileExists(refPath)) ? refPath : undefined;
    return rpcCall<SubtitleCheck>("capability.subtitle_check", {
      srt_path: m.subtitlePath(lang),
      expected_lang: lang,
      ...(reference ? { reference_srt_path: reference } : {}),
    });
  },

  quickFixSubtitle: async (instance: string, lang: string): Promise<SubtitleCheck> => {
    const m = await loadModel(instance);
    return rpcCall<SubtitleCheck>("capability.subtitle_quick_fix", {
      srt_path: m.subtitlePath(lang),
      expected_lang: lang,
    });
  },

  saveChapters: async (
    instance: string,
    filename: string,
    chapters: Record<string, unknown>[],
    lang: string,
  ): Promise<Record<string, unknown>> => {
    const m = await loadModel(instance);
    return rpcCall<Record<string, unknown>>("capability.save_chapters", {
      analysis_path: `${m.subtitlesDir}/${filename}`,
      chapters,
      srt_path: m.subtitlePath(lang),
      lang,
    });
  },

  // ── Analysis job (B3.2b — no project-meta coupling) ───────────────────────
  // Thin forward to capability.analyze (returns {job_id}; runJob consumes it).
  startRunAnalysis: async (
    instance: string,
    lang: string,
    analysisKind: string,
  ): Promise<{ job_id: string }> => {
    const m = await loadModel(instance);
    return rpcCall<{ job_id: string }>("capability.analyze", {
      kind: analysisKind,
      srt_path: m.subtitlePath(lang),
      subtitles_dir: m.subtitlesDir,
      lang,
    });
  },
};
