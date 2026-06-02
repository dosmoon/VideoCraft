/**
 * MaterialSidebar — the rich, guided node tree for one news_video instance
 * (ADR-0008 B3.2 sidebar-driven redesign; lucide icons + shared tokens).
 *
 * Fully `+`-menu driven (symmetric): the subtitles node's "+" produces new
 * subtitle tracks (transcribe / import); each language node's "+" acts on that
 * track (translate-from-it / generate analysis). Parameterized actions (source
 * or target language, file pick) open a small picker popup inside the menu. The
 * source-language subtitle carries a "源" tag so the translate direction is
 * legible. Detail-heavy work (acquire / view / chapter edit) lives in the right
 * panel via MaterialDetail; this tree is navigation + light triggers.
 *
 * Inline jobs reuse the same rpc.start* + project.* meta path the detail tabs use
 * (capability emits no domain events): on success the action persists meta where
 * needed (ASR → source language) then calls onChanged to refresh tree + detail.
 */

import { useCallback, useEffect, useState } from "react";
import { ANALYSIS_TYPES, analysisType } from "@materials/news_video/analysisTypes";
import { buildMaterialTree, type MaterialNode } from "@materials/news_video/sidebarTree";
import { materialBackend } from "@materials/news_video/clientBackend";
import type { SlotId, SlotState } from "@materials/news_video/model";
import { rpc, RpcError, type KnownLanguage, type ProjectBrief, type SourceContext } from "../../ipc/client";
import { useJob } from "../../ipc/runJob";
import { getLang, tr } from "../../i18n/tr";
import { LanguagePicker } from "./LanguagePicker";
import { color, state as st, font, radius } from "../../ui/tokens";
import {
  SLOT_ICON,
  LANG_ICON,
  analysisIcon,
  Sparkles,
  AudioLines,
  Languages,
  FileUp,
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

function Pill({ children, tone }: { children: React.ReactNode; tone: "muted" | "partial" | "accent" }) {
  const map = {
    muted: { color: color.textSecondary, border: color.border },
    partial: { color: st.partial, border: "rgba(217,162,58,0.5)" },
    accent: { color: color.accentText, border: "rgba(45,108,223,0.55)" },
  } as const;
  const t = map[tone];
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

/** Compact right-aligned status badge — long detail lives in the right panel. */
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
    <button title={title} onClick={onClick} onMouseEnter={ghostHoverIn} onMouseLeave={ghostHoverOut} style={{ ...ghostBase, opacity }}>
      <Icon size={15} strokeWidth={2} />
    </button>
  );
}

// ── Node action "+" menu (two screens: item list → language-param picker) ────

/** One "+" menu entry. `run` fires immediately; `langParam` opens a picker
 * screen (source/target language, optional auto) then confirms with the chosen
 * iso ("" = auto when allowAuto). */
type ActionItem =
  | { id: string; label: string; icon: LucideIcon; kind: "run"; run: () => void }
  | {
      id: string;
      label: string;
      icon: LucideIcon;
      kind: "langParam";
      title?: string;
      allowAuto?: boolean;
      placeholder: string;
      confirmLabel: string;
      confirm: (iso: string) => void;
    };

const menuItemStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  textAlign: "left",
  background: "transparent",
  color: color.textPrimary,
  border: "none",
  borderRadius: radius.sm,
  padding: "6px 8px",
  fontSize: font.sm,
  cursor: "pointer",
};

function NodeActionMenu(props: { items: ActionItem[]; knownLangs: KnownLanguage[]; opacity: number }) {
  const { items, knownLangs, opacity } = props;
  const [open, setOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [paramLang, setParamLang] = useState("");

  const close = () => {
    setOpen(false);
    setActiveId(null);
    setParamLang("");
  };

  const active = items.find((i) => i.id === activeId);
  const requireValue = active?.kind === "langParam" && !active.allowAuto;
  const canConfirm = !requireValue || !!paramLang.trim();

  return (
    <div style={{ position: "relative", display: "inline-flex" }}>
      <button
        title={tr("material.sidebar.add_title")}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
          setActiveId(null);
          setParamLang("");
        }}
        onMouseEnter={ghostHoverIn}
        onMouseLeave={ghostHoverOut}
        style={{ ...ghostBase, opacity: open ? 1 : opacity }}
      >
        <Plus size={15} strokeWidth={2} />
      </button>
      {open && (
        <>
          <div onClick={(e) => { e.stopPropagation(); close(); }} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "absolute",
              top: "100%",
              right: 0,
              zIndex: 41,
              background: color.bgRaised,
              border: `1px solid ${color.border}`,
              borderRadius: radius.md,
              padding: active ? 8 : 4,
              minWidth: active ? 230 : 190,
              boxShadow: "0 6px 16px rgba(0,0,0,0.45)",
            }}
          >
            {!active ? (
              items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (item.kind === "run") {
                        close();
                        item.run();
                      } else {
                        setActiveId(item.id);
                        setParamLang("");
                      }
                    }}
                    style={menuItemStyle}
                    onMouseEnter={(e) => (e.currentTarget.style.background = color.bgHover)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <Icon size={14} strokeWidth={2} style={{ flexShrink: 0, color: color.textSecondary }} />
                    <span>{item.label}</span>
                  </button>
                );
              })
            ) : active.kind === "langParam" ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {active.title && <div style={{ fontSize: font.xs, color: color.textSecondary }}>{active.title}</div>}
                <LanguagePicker
                  value={paramLang}
                  onChange={setParamLang}
                  languages={knownLangs}
                  allowAuto={active.allowAuto === true}
                  placeholder={active.placeholder}
                  width={214}
                />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!canConfirm) return;
                    const iso = paramLang.trim();
                    close();
                    active.confirm(iso);
                  }}
                  disabled={!canConfirm}
                  style={{
                    alignSelf: "flex-end",
                    padding: "5px 12px",
                    background: color.accent,
                    color: "#fff",
                    border: "none",
                    borderRadius: radius.sm,
                    fontSize: font.sm,
                    cursor: canConfirm ? "pointer" : "default",
                    opacity: canConfirm ? 1 : 0.5,
                  }}
                >
                  {active.confirmLabel}
                </button>
              </div>
            ) : null}
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
  const [knownLangs, setKnownLangs] = useState<KnownLanguage[]>([]);
  const [sourceLang, setSourceLang] = useState("");
  const [err, setErr] = useState("");
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const job = useJob();

  // Preset language catalog for the "+" pickers (loaded once).
  useEffect(() => {
    let alive = true;
    void rpc.listLanguages().then((ls) => alive && setKnownLangs(ls)).catch(() => {});
    return () => { alive = false; };
  }, []);

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
      // The project's source language (ASR / first import stamps it) — marks the
      // source subtitle node and is the default translate-from.
      const cur = (await rpc.currentProject()) as ProjectBrief | null;
      const meta = (cur?.meta ?? {}) as { language?: { source?: string } };
      setSourceLang(meta.language?.source ?? "");
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

  // ── Inline actions (persist meta on success, then refresh) ──────────────────
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

  const asr = useCallback(
    async (lang: string) => {
      const res = await job.run<{ lang_iso?: string }>(() => rpc.startRunAsr(type, instance, lang || undefined));
      if (res?.lang_iso) {
        try {
          await rpc.setSourceLanguage(res.lang_iso);
        } catch {
          /* non-fatal */
        }
      }
      if (res !== undefined) onChanged();
    },
    [job, type, instance, onChanged],
  );

  const translate = useCallback(
    async (src: string, target: string) => {
      const res = await job.run(() => rpc.startRunTranslate(type, instance, target, src));
      if (res !== undefined && type === "news_video") {
        try {
          await rpc.addTranslatedLanguage(target);
        } catch {
          /* non-fatal */
        }
      }
      if (res !== undefined) onChanged();
    },
    [job, type, instance, onChanged],
  );

  const importSrt = useCallback(
    async (lang: string) => {
      const path = await window.vc.pickSubtitle();
      if (!path) return;
      setErr("");
      try {
        await rpc.importSubtitle(type, instance, path, lang);
        onChanged();
      } catch (e) {
        setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
      }
    },
    [type, instance, onChanged],
  );

  const analyze = useCallback(
    async (lang: string, kind: string) => {
      const res = await job.run(() => rpc.startRunAnalysis(type, instance, lang, kind));
      if (res !== undefined) onChanged();
    },
    [job, type, instance, onChanged],
  );

  const tree = readiness ? buildMaterialTree({ readiness, langs, analysesByLang }) : [];

  // "+" menu items for the subtitles node (transcribe / import).
  const subtitlesMenu: ActionItem[] = [
    {
      id: "asr",
      label: tr("material.sidebar.menu_asr"),
      icon: AudioLines,
      kind: "langParam",
      allowAuto: true,
      placeholder: tr("material.subtitles_tab.asr_lang_placeholder"),
      confirmLabel: tr("material.subtitles_tab.run_asr_btn"),
      confirm: (iso) => void asr(iso),
    },
    {
      id: "import",
      label: tr("material.sidebar.menu_import"),
      icon: FileUp,
      kind: "langParam",
      placeholder: tr("material.subtitles_tab.import_lang_placeholder"),
      confirmLabel: tr("material.subtitles_tab.import_srt_btn"),
      confirm: (iso) => void importSrt(iso),
    },
  ];

  // "+" menu items for a language node (translate-from-it / generate analysis).
  const langMenu = (lang: string): ActionItem[] => [
    {
      id: "translate",
      label: tr("material.sidebar.menu_translate"),
      icon: Languages,
      kind: "langParam",
      title: tr("material.subtitles_tab.translate_from", { lang: lang.toUpperCase() }),
      placeholder: tr("material.subtitles_tab.translate_target_placeholder"),
      confirmLabel: tr("material.subtitles_tab.translate_btn"),
      confirm: (target) => void translate(lang, target),
    },
    ...ANALYSIS_TYPES.filter((t) => t.generatable).map(
      (t): ActionItem => ({
        id: `gen-${t.kind}`,
        label: GEN_LABEL[t.kind] ? tr(GEN_LABEL[t.kind]!) : getLang() === "zh" ? t.displayZh : t.displayEn,
        icon: analysisIcon(t.kind),
        kind: "run",
        run: () => void analyze(lang, t.kind),
      }),
    ),
  ];

  const renderNode = (node: MaterialNode, depth: number): React.ReactNode => {
    const selected = node.id === selectedNodeId;
    const hovered = node.id === hoveredId;
    const locked = node.slot?.isLocked ?? false;
    const expandable = node.children.length > 0;
    const collapsed = collapsedIds.has(node.id);
    const Icon = nodeIcon(node);
    const opacity = hovered ? 1 : 0.35;
    const isSource = node.kind === "lang" && !!node.lang && node.lang === sourceLang;

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
        action = <NodeActionMenu items={subtitlesMenu} knownLangs={knownLangs} opacity={opacity} />;
      } else if (node.kind === "lang" && node.lang) {
        action = <NodeActionMenu items={langMenu(node.lang)} knownLangs={knownLangs} opacity={opacity} />;
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
          {Array.from({ length: depth }, (_, i) => (
            <span key={i} style={{ width: INDENT, flexShrink: 0, alignSelf: "stretch", borderLeft: `1px solid ${color.borderSubtle}` }} />
          ))}
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
          <span style={{ flex: 1, minWidth: 0, fontSize: font.sm, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {nodeLabel(node)}
          </span>
          {isSource && <Pill tone="accent">{tr("material.sidebar.source_tag")}</Pill>}
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
          <button onClick={job.cancel} onMouseEnter={ghostHoverIn} onMouseLeave={ghostHoverOut} style={{ ...ghostBase, width: "auto", padding: "0 8px", fontSize: font.xs, color: color.textSecondary }}>
            {tr("common.cancel")}
          </button>
        </div>
      )}
      {tree.map((n) => renderNode(n, 0))}
    </div>
  );
}
