/**
 * Analysis-type registry — TS port of `core.subtitle_analysis.ANALYSIS_TYPES`
 * (ADR-0008 B3.2c). Each subtitle analysis kind has a stable on-disk suffix +
 * presentation metadata (icon, bilingual display name, format). Artifacts land
 * flat under subtitles/ as `<iso>.<suffix>`. The material sidebar uses this to
 * list/label existing analysis artifacts per language; the data layer (model.ts)
 * uses it to resolve analysis paths.
 *
 * Registry order = the order shown in the UI. Note (mirrors the Tk app): only
 * `analysis` + `hotclips` are user-generatable; transcript / chapter_transcript
 * are produced internally by news_desk export/publish, shown only when present.
 */

export interface AnalysisType {
  kind: string;
  suffix: string; // appended after "<iso>." → the on-disk filename
  format: "json" | "md";
  icon: string;
  displayZh: string;
  displayEn: string;
  generatable: boolean; // shown in the "generate analysis" menu (Tk hidden filter)
}

export const ANALYSIS_TYPES: readonly AnalysisType[] = [
  { kind: "analysis", suffix: "analysis.json", format: "json", icon: "📑", displayZh: "标题与章节", displayEn: "Titles & Chapters", generatable: true },
  { kind: "transcript", suffix: "transcript.md", format: "md", icon: "📄", displayZh: "全文文字稿", displayEn: "Transcript", generatable: false },
  { kind: "chapter_transcript", suffix: "chapter_transcript.md", format: "md", icon: "📜", displayZh: "分章节全文", displayEn: "Chapter Transcript", generatable: false },
  { kind: "hotclips", suffix: "hotclips.json", format: "json", icon: "🔥", displayZh: "热点片段", displayEn: "Hot Clips", generatable: true },
];

const BY_KIND = new Map(ANALYSIS_TYPES.map((t) => [t.kind, t]));

export function analysisType(kind: string): AnalysisType | undefined {
  return BY_KIND.get(kind);
}

/** On-disk filename for a (lang, kind) analysis artifact; null on unknown kind. */
export function analysisFilename(langIso: string, kind: string): string | null {
  const t = BY_KIND.get(kind);
  return t ? `${langIso}.${t.suffix}` : null;
}
