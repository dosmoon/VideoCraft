/**
 * MaterialDetail — the right-panel detail for whichever sidebar node is selected
 * (ADR-0008 B3.2 sidebar-driven redesign). Reuses the existing tab/viewer
 * components as per-node detail panels instead of a 3-tab workbench:
 *
 *   source        → SourceTab (acquire picker + video preview)
 *   news_context  → ContextTab (15-field form)
 *   subtitles     → SubtitlesTab (ASR / translate / import management)
 *   lang:<iso>    → SubtitleViewer (SRT text + quality check)
 *   analysis:<iso>:analysis        → ChapterScheduleEditor
 *   analysis:<iso>:<other-kind>    → AnalysisTextViewer (read-only md/json)
 */

import { analysisType } from "@materials/news_video/analysisTypes";
import { getLang, tr } from "../../i18n/tr";
import { SourceTab } from "./SourceTab";
import { ContextTab } from "./ContextTab";
import { SubtitleViewer } from "./SubtitleViewer";
import { ChapterScheduleEditor } from "./ChapterScheduleEditor";
import { AnalysisTextViewer } from "./AnalysisTextViewer";
import { HotclipsViewer } from "./HotclipsViewer";

function Placeholder({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: 24, color: "#666", fontSize: 13 }}>{children}</div>;
}

export function MaterialDetail(props: {
  type: string;
  instance: string;
  nodeId: string | null;
  refreshKey: number;
  onChanged: () => void;
  onDeselect: () => void;
}) {
  const { type, instance, nodeId, refreshKey, onChanged, onDeselect } = props;

  if (!nodeId) return <Placeholder>{tr("material.detail.pick_node")}</Placeholder>;
  if (nodeId === "source")
    return <SourceTab type={type} instance={instance} refreshKey={refreshKey} onChanged={onChanged} />;
  if (nodeId === "news_context")
    return <ContextTab type={type} instance={instance} refreshKey={refreshKey} onChanged={onChanged} />;
  if (nodeId === "subtitles") return <Placeholder>{tr("material.detail.subtitles_hint")}</Placeholder>;

  if (nodeId.startsWith("lang:")) {
    const lang = nodeId.slice("lang:".length);
    return (
      <SubtitleViewer type={type} instance={instance} lang={lang} onClose={onDeselect} onChanged={onChanged} />
    );
  }

  if (nodeId.startsWith("analysis:")) {
    const [, lang, kind] = nodeId.split(":");
    if (lang && kind === "analysis") {
      return (
        <ChapterScheduleEditor
          type={type}
          instance={instance}
          filename={`${lang}.analysis.json`}
          lang={lang}
          onClose={onDeselect}
          onSaved={onChanged}
        />
      );
    }
    if (lang && kind) {
      const at = analysisType(kind);
      const title = at ? (getLang() === "zh" ? at.displayZh : at.displayEn) : kind;
      if (kind === "hotclips") {
        return <HotclipsViewer type={type} instance={instance} lang={lang} title={title} onClose={onDeselect} />;
      }
      return (
        <AnalysisTextViewer type={type} instance={instance} lang={lang} kind={kind} title={title} onClose={onDeselect} />
      );
    }
  }

  return <Placeholder>{tr("material.detail.pick_node")}</Placeholder>;
}
