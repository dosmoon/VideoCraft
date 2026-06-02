/**
 * MaterialSidebar — the rich, guided node tree for one news_video instance
 * (ADR-0008 B3.2 sidebar-driven redesign). Replaces the read-only SlotRow +
 * 3-tab workbench: the pipeline (source → news_context → subtitles → lang →
 * analysis) is a selectable tree with inline status + the one-click actions
 * (AI fill / ASR / generate analysis). Selecting a node drives MaterialDetail in
 * the right panel; input-heavy actions (acquire / translate / import / edit) live
 * in that detail panel.
 *
 * Inline jobs reuse the same rpc.start* + project.* meta path the detail tabs use
 * (capability emits no domain events): on success the action persists meta where
 * needed (ASR → source language; AI fill → context) then calls onChanged to
 * refresh both the tree and the detail.
 */

import { useCallback, useEffect, useState } from "react";
import { ANALYSIS_TYPES, analysisType } from "@materials/news_video/analysisTypes";
import { buildMaterialTree, type MaterialNode } from "@materials/news_video/sidebarTree";
import { materialBackend } from "@materials/news_video/clientBackend";
import type { SlotId, SlotState } from "@materials/news_video/model";
import { rpc, RpcError, type SourceContext } from "../../ipc/client";
import { useJob } from "../../ipc/runJob";
import { getLang, tr } from "../../i18n/tr";

const SLOT_LABEL: Record<string, string> = {
  source: "hub.slot.source",
  news_context: "hub.slot.news_context",
  subtitles: "hub.slot.subtitles",
};
const SLOT_ICON: Record<string, string> = { source: "📹", news_context: "📰", subtitles: "📝" };

function fmtDuration(sec: number): string {
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** Human status line for a slot node, from the structured SlotState. */
function slotStatus(node: MaterialNode): string {
  const slot = node.slot;
  if (!slot) return "";
  if (slot.isLocked) return tr("material.sidebar.locked");
  if (node.kind === "source") {
    if (!slot.isFilled) return tr("material.sidebar.no_source");
    const s = slot.source;
    const extra = [s?.durationSec ? fmtDuration(s.durationSec) : "", s?.width && s?.height ? `${s.width}×${s.height}` : ""].filter(Boolean).join(" · ");
    return `✓ ${s?.title || "video.mp4"}${extra ? " · " + extra : ""}`;
  }
  if (node.kind === "news_context") {
    const c = slot.context;
    return c && c.filled > 0 ? tr("material.sidebar.ctx_filled", { n: String(c.filled), total: String(c.total) }) : tr("material.sidebar.ctx_empty");
  }
  if (node.kind === "subtitles") {
    const langs = slot.subtitles?.langs ?? [];
    return langs.length ? `✓ ${tr("material.sidebar.langs", { n: String(langs.length) })}` : tr("material.sidebar.no_source");
  }
  return "";
}

function nodeLabel(node: MaterialNode): string {
  if (node.kind === "lang") return (node.lang ?? "").toUpperCase();
  if (node.kind === "analysis") {
    const at = node.analysisKind ? analysisType(node.analysisKind) : undefined;
    return at ? `${at.icon} ${getLang() === "zh" ? at.displayZh : at.displayEn}` : (node.analysisKind ?? "");
  }
  return `${SLOT_ICON[node.kind] ?? ""} ${tr(SLOT_LABEL[node.kind] ?? node.kind)}`.trim();
}

const ACT_BTN: React.CSSProperties = {
  border: "1px solid #3a3a40",
  background: "#26262b",
  color: "#cfcfd4",
  borderRadius: 4,
  fontSize: 11,
  padding: "1px 7px",
  cursor: "pointer",
};

export function MaterialSidebar(props: {
  type: string;
  instance: string;
  selectedNodeId: string | null;
  onSelect: (nodeId: string) => void;
  refreshKey: number;
  onChanged: () => void;
}) {
  const { type, instance, selectedNodeId, onSelect, refreshKey, onChanged } = props;
  const [readiness, setReadiness] = useState<Record<SlotId, SlotState> | null>(null);
  const [langs, setLangs] = useState<string[]>([]);
  const [analysesByLang, setAnalysesByLang] = useState<Record<string, string[]>>({});
  const [err, setErr] = useState("");
  const job = useJob();

  const load = useCallback(async () => {
    setErr("");
    try {
      const r = await materialBackend.slotReadinessStructured(instance);
      setReadiness(r);
      const ls = await rpc.listSubtitleLanguages(type, instance);
      setLangs(ls);
      const byLang: Record<string, string[]> = {};
      for (const l of ls) byLang[l] = (await rpc.listAnalysisArtifacts(type, instance, l)).map((a) => a.kind);
      setAnalysesByLang(byLang);
    } catch (e) {
      setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    }
  }, [type, instance]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // ── Inline one-click actions (persist meta on success, then refresh) ─────────
  const fill = useCallback(async () => {
    const res = await job.run<SourceContext>(() => rpc.startAiFillContext(type, instance));
    if (res !== undefined) {
      try {
        await rpc.writeContext(type, instance, res);
      } catch {
        /* surfaced by job.error; still refresh */
      }
      onChanged();
    }
  }, [job, type, instance, onChanged]);

  const asr = useCallback(async () => {
    const res = await job.run<{ lang_iso?: string }>(() => rpc.startRunAsr(type, instance));
    if (res?.lang_iso) {
      try {
        await rpc.setSourceLanguage(res.lang_iso);
      } catch {
        /* non-fatal */
      }
    }
    if (res !== undefined) onChanged();
  }, [job, type, instance, onChanged]);

  const analyze = useCallback(
    async (lang: string, kind: string) => {
      const res = await job.run(() => rpc.startRunAnalysis(type, instance, lang, kind));
      if (res !== undefined) onChanged();
    },
    [job, type, instance, onChanged],
  );

  const tree = readiness
    ? buildMaterialTree({ readiness, langs, analysesByLang })
    : [];

  const renderNode = (node: MaterialNode, depth: number): React.ReactNode => {
    const selected = node.id === selectedNodeId;
    const locked = node.slot?.isLocked ?? false;
    const actions: React.ReactNode[] = [];
    if (!job.running && !locked) {
      if (node.kind === "news_context") {
        actions.push(<button key="fill" style={ACT_BTN} onClick={(e) => { e.stopPropagation(); void fill(); }}>{tr("material.context.ai_fill_btn")}</button>);
      } else if (node.kind === "subtitles") {
        actions.push(<button key="asr" style={ACT_BTN} onClick={(e) => { e.stopPropagation(); void asr(); }}>{tr("material.subtitles_tab.run_asr_btn")}</button>);
      } else if (node.kind === "lang" && node.lang) {
        for (const t of ANALYSIS_TYPES.filter((x) => x.generatable)) {
          actions.push(
            <button key={t.kind} style={ACT_BTN} title={tr("material.sidebar.generate_title")} onClick={(e) => { e.stopPropagation(); void analyze(node.lang!, t.kind); }}>
              +{t.icon}
            </button>,
          );
        }
      }
    }
    return (
      <div key={node.id}>
        <div
          onClick={() => onSelect(node.id)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "3px 8px",
            paddingLeft: 8 + depth * 14,
            borderRadius: 4,
            cursor: "pointer",
            background: selected ? "#2d6cdf" : "transparent",
            color: locked ? "#777" : selected ? "#fff" : "#ccc",
            fontSize: 12,
          }}
        >
          <span style={{ flexShrink: 0 }}>{nodeLabel(node)}</span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: selected ? "#dde" : "#888", fontSize: 11 }}>
            {slotStatus(node)}
          </span>
          <span style={{ display: "flex", gap: 3, flexShrink: 0 }}>{actions}</span>
        </div>
        {node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div>
      {err && <div style={{ color: "#ff6b6b", fontSize: 11, padding: "2px 8px" }}>✗ {err}</div>}
      {job.running && (
        <div style={{ color: "#7fa6ff", fontSize: 11, padding: "2px 8px", display: "flex", gap: 6 }}>
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            ⏳ {job.progress?.status_text || tr("material.sidebar.running")}
            {job.progress?.pct != null ? ` · ${Math.round(job.progress.pct)}%` : ""}
          </span>
          <button style={ACT_BTN} onClick={job.cancel}>{tr("common.cancel")}</button>
        </div>
      )}
      {tree.map((n) => renderNode(n, 0))}
    </div>
  );
}
