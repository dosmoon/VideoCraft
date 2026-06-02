/**
 * MaterialSidebar — the rich, guided node tree for one news_video instance
 * (ADR-0008 B3.2 sidebar-driven redesign; visual refresh: lucide icons + shared
 * tokens). The pipeline (source → news_context → subtitles → lang → analysis) is
 * a compact, VSCode-explorer-style tree:
 *   - state is encoded in the leading icon's tint (empty / partial / done / locked)
 *   - status is a compact right-aligned badge (✓ + duration · n/total · n langs),
 *     NOT a long truncated sentence — heavy detail lives in the right detail panel
 *   - one-click actions (AI fill / ASR / generate) hover-reveal as ghost icons
 *     instead of always-on bordered buttons
 *   - one softened selection style (accent-soft fill + left bar), and a single
 *     selection that won't clash with the instance header's
 *
 * Selecting a node drives MaterialDetail in the right panel; input-heavy actions
 * (acquire / translate / import / edit) live in that detail panel.
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
import { color, state as st, font, radius } from "../../ui/tokens";
import {
  SLOT_ICON,
  LANG_ICON,
  analysisIcon,
  Sparkles,
  AudioLines,
  Plus,
  ChevronRight,
  ChevronDown,
  Check,
  Loader2,
  AlertCircle,
  type LucideIcon,
} from "../../ui/icons";

const INDENT = 14;
const ICON = 15;

const SLOT_LABEL: Record<string, string> = {
  source: "hub.slot.source",
  news_context: "hub.slot.news_context",
  subtitles: "hub.slot.subtitles",
};
// Menu label for each user-generatable analysis kind (mirrors the Tk generate menu).
const GEN_LABEL: Record<string, string> = {
  analysis: "material.sidebar.gen_analysis",
  hotclips: "material.sidebar.gen_hotclips",
};

function fmtDuration(sec: number): string {
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

// ── Per-node presentation derived from structured SlotState ──────────────────

/** Tint for a node's leading icon, encoding its readiness. */
function nodeStateColor(node: MaterialNode): string {
  if (node.slot?.isLocked) return st.locked;
  switch (node.kind) {
    case "source":
      return node.slot?.isFilled ? st.done : st.empty;
    case "news_context": {
      const c = node.slot?.context;
      if (!c || c.filled === 0) return st.empty;
      return c.filled >= c.total ? st.done : st.partial;
    }
    case "subtitles":
      return (node.slot?.subtitles?.langs.length ?? 0) > 0 ? st.done : st.empty;
    default:
      return color.textSecondary; // lang / analysis — neutral (state colors reserved for slots)
  }
}

function nodeIcon(node: MaterialNode): LucideIcon {
  if (node.kind === "lang") return LANG_ICON;
  if (node.kind === "analysis") return analysisIcon(node.analysisKind ?? "");
  return SLOT_ICON[node.kind]!;
}

function nodeLabel(node: MaterialNode): string {
  if (node.kind === "lang") return (node.lang ?? "").toUpperCase();
  if (node.kind === "analysis") {
    const at = node.analysisKind ? analysisType(node.analysisKind) : undefined;
    return at ? (getLang() === "zh" ? at.displayZh : at.displayEn) : (node.analysisKind ?? "");
  }
  return tr(SLOT_LABEL[node.kind] ?? node.kind);
}

// ── Small presentational atoms ───────────────────────────────────────────────

function Pill({ children, tone }: { children: React.ReactNode; tone: "muted" | "partial" }) {
  const t =
    tone === "partial"
      ? { color: st.partial, border: "rgba(217,162,58,0.5)" }
      : { color: color.textSecondary, border: color.border };
  return (
    <span
      style={{
        fontSize: font.xs,
        color: t.color,
        border: `1px solid ${t.border}`,
        borderRadius: radius.pill,
        padding: "0 6px",
        lineHeight: "15px",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function MutedTag({ children }: { children: React.ReactNode }) {
  return <span style={{ fontSize: font.xs, color: color.textMuted, whiteSpace: "nowrap" }}>{children}</span>;
}

/** Compact right-aligned status badge — the long detail (title, resolution) lives
 * in the right detail panel, not crammed into the row. */
function StatusBadge({ node }: { node: MaterialNode }): React.ReactNode {
  const slot = node.slot;
  if (slot?.isLocked) return <MutedTag>{tr("material.sidebar.locked")}</MutedTag>;
  if (node.kind === "source") {
    if (!slot?.isFilled) return <MutedTag>{tr("material.sidebar.no_source")}</MutedTag>;
    const d = slot.source?.durationSec;
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        <Check size={13} color={st.done} strokeWidth={2.5} />
        {d ? <Pill tone="muted">{fmtDuration(d)}</Pill> : null}
      </span>
    );
  }
  if (node.kind === "news_context") {
    const c = slot?.context;
    if (!c || c.filled === 0) return <MutedTag>{tr("material.sidebar.ctx_empty")}</MutedTag>;
    return c.filled >= c.total ? (
      <Check size={13} color={st.done} strokeWidth={2.5} />
    ) : (
      <Pill tone="partial">
        {c.filled}/{c.total}
      </Pill>
    );
  }
  if (node.kind === "subtitles") {
    const n = slot?.subtitles?.langs.length ?? 0;
    return n > 0 ? <Pill tone="muted">{tr("material.sidebar.langs", { n: String(n) })}</Pill> : null;
  }
  return null;
}

// ── Ghost (hover-reveal) action buttons ──────────────────────────────────────

const ghostBase: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 22,
  height: 22,
  padding: 0,
  border: "none",
  borderRadius: radius.sm,
  background: "transparent",
  color: color.textSecondary,
  cursor: "pointer",
  transition: "opacity 120ms ease, background 120ms ease, color 120ms ease",
};

function ghostHoverIn(e: React.MouseEvent<HTMLButtonElement>) {
  e.currentTarget.style.background = color.bgHover;
  e.currentTarget.style.color = color.accentText;
}
function ghostHoverOut(e: React.MouseEvent<HTMLButtonElement>) {
  e.currentTarget.style.background = "transparent";
  e.currentTarget.style.color = color.textSecondary;
}

function GhostIconButton(props: {
  icon: LucideIcon;
  title: string;
  opacity: number;
  onClick: (e: React.MouseEvent) => void;
}) {
  const { icon: Icon, title, opacity, onClick } = props;
  return (
    <button
      title={title}
      onClick={onClick}
      onMouseEnter={ghostHoverIn}
      onMouseLeave={ghostHoverOut}
      style={{ ...ghostBase, opacity }}
    >
      <Icon size={15} strokeWidth={2} />
    </button>
  );
}

/** The "+" generate action on a language row → dropdown of generatable kinds. */
function GenerateMenu(props: { lang: string; opacity: number; onPick: (kind: string) => void }) {
  const { opacity, onPick } = props;
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative", display: "inline-flex" }}>
      <button
        title={tr("material.sidebar.generate_title")}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        onMouseEnter={ghostHoverIn}
        onMouseLeave={ghostHoverOut}
        style={{ ...ghostBase, opacity: open ? 1 : opacity }}
      >
        <Plus size={15} strokeWidth={2} />
      </button>
      {open && (
        <>
          <div
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
            }}
            style={{ position: "fixed", inset: 0, zIndex: 40 }}
          />
          <div
            style={{
              position: "absolute",
              top: "100%",
              right: 0,
              zIndex: 41,
              background: color.bgRaised,
              border: `1px solid ${color.border}`,
              borderRadius: radius.md,
              padding: 4,
              minWidth: 170,
              boxShadow: "0 6px 16px rgba(0,0,0,0.45)",
            }}
          >
            {ANALYSIS_TYPES.filter((t) => t.generatable).map((t) => {
              const Icon = analysisIcon(t.kind);
              const label = GEN_LABEL[t.kind]
                ? tr(GEN_LABEL[t.kind]!)
                : getLang() === "zh"
                  ? t.displayZh
                  : t.displayEn;
              return (
                <button
                  key={t.kind}
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen(false);
                    onPick(t.kind);
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    width: "100%",
                    textAlign: "left",
                    background: "transparent",
                    color: color.textPrimary,
                    border: "none",
                    borderRadius: radius.sm,
                    padding: "5px 8px",
                    fontSize: font.sm,
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = color.bgHover)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <Icon size={14} strokeWidth={2} style={{ flexShrink: 0, color: color.textSecondary }} />
                  <span>{label}</span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────

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
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
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

  const toggleCollapse = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

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

  const tree = readiness ? buildMaterialTree({ readiness, langs, analysesByLang }) : [];

  const renderNode = (node: MaterialNode, depth: number): React.ReactNode => {
    const selected = node.id === selectedNodeId;
    const hovered = node.id === hoveredId;
    const locked = node.slot?.isLocked ?? false;
    const expandable = node.children.length > 0;
    const collapsed = collapsedIds.has(node.id);
    const Icon = nodeIcon(node);
    const opacity = hovered ? 1 : 0.35;

    let action: React.ReactNode = null;
    if (!job.running && !locked) {
      if (node.kind === "news_context") {
        action = (
          <GhostIconButton
            icon={Sparkles}
            title={tr("material.context.ai_fill_btn")}
            opacity={opacity}
            onClick={(e) => {
              e.stopPropagation();
              void fill();
            }}
          />
        );
      } else if (node.kind === "subtitles") {
        action = (
          <GhostIconButton
            icon={AudioLines}
            title={tr("material.subtitles_tab.run_asr_btn")}
            opacity={opacity}
            onClick={(e) => {
              e.stopPropagation();
              void asr();
            }}
          />
        );
      } else if (node.kind === "lang" && node.lang) {
        action = <GenerateMenu lang={node.lang} opacity={opacity} onPick={(kind) => void analyze(node.lang!, kind)} />;
      }
    }

    return (
      <div key={node.id}>
        <div
          onClick={() => onSelect(node.id)}
          onMouseEnter={() => setHoveredId(node.id)}
          onMouseLeave={() => setHoveredId((h) => (h === node.id ? null : h))}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "0 8px",
            minHeight: 27,
            borderRadius: radius.sm,
            cursor: "pointer",
            background: selected ? color.accentSoft : hovered ? color.bgHover : "transparent",
            boxShadow: selected ? `inset 2px 0 0 ${color.accent}` : "none",
            color: locked ? st.locked : selected ? color.accentText : color.textPrimary,
          }}
        >
          {/* indent guide lines, one per ancestor depth */}
          {Array.from({ length: depth }, (_, i) => (
            <span
              key={i}
              style={{ width: INDENT, flexShrink: 0, alignSelf: "stretch", borderLeft: `1px solid ${color.borderSubtle}` }}
            />
          ))}
          {/* disclosure chevron (expandable) or aligning spacer */}
          {expandable ? (
            <span
              onClick={(e) => {
                e.stopPropagation();
                toggleCollapse(node.id);
              }}
              style={{ display: "inline-flex", width: 16, flexShrink: 0, color: color.textMuted, cursor: "pointer" }}
            >
              {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
            </span>
          ) : (
            <span style={{ width: 16, flexShrink: 0 }} />
          )}
          <Icon size={ICON} color={nodeStateColor(node)} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span
            style={{
              flex: 1,
              minWidth: 0,
              fontSize: font.sm,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {nodeLabel(node)}
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
            <StatusBadge node={node} />
            {action}
          </span>
        </div>
        {expandable && !collapsed && node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div style={{ paddingTop: 2 }}>
      {err && (
        <div style={{ display: "flex", alignItems: "center", gap: 5, color: color.danger, fontSize: font.xs, padding: "3px 8px" }}>
          <AlertCircle size={13} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{err}</span>
        </div>
      )}
      {job.running && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.accentText, fontSize: font.xs, padding: "3px 8px" }}>
          <Loader2 size={13} strokeWidth={2} className="vc-spin" style={{ flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {job.progress?.status_text || tr("material.sidebar.running")}
            {job.progress?.pct != null ? ` · ${Math.round(job.progress.pct)}%` : ""}
          </span>
          <button
            onClick={job.cancel}
            onMouseEnter={ghostHoverIn}
            onMouseLeave={ghostHoverOut}
            style={{ ...ghostBase, width: "auto", padding: "0 8px", fontSize: font.xs, color: color.textSecondary }}
          >
            {tr("common.cancel")}
          </button>
        </div>
      )}
      {tree.map((n) => renderNode(n, 0))}
    </div>
  );
}
