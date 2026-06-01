/**
 * NewsDeskWorkbench — the per-plugin news_desk workbench, shaped after the
 * original Tk workbench (news_desk_tool.py): a component list + property editor,
 * plus an export view. news_desk composes the FULL source (no candidate
 * cutting), so unlike clip there is no 候选 tab — just 样式 Style and 导出 Export.
 *
 * This shell owns the cross-tab state (the component list + the component-patch
 * write path) exactly like ClipWorkbench, and hands each tab its slice. The Hub
 * hosts it generically (dispatch by creation type, workbenches/index.tsx).
 *
 * The Style tab edits config + shows the live GPU preview; the Export tab runs
 * the full-source render (buildNewsDeskTimeline → engine → encode →
 * vc:writeFile → commit_render). Both share the same compositor, so the
 * exported mp4 ≡ the preview.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type Component } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { StyleTab } from "./StyleTab";
import { ExportTab } from "./ExportTab";

type Tab = "style" | "export";

const TABS: { id: Tab; label: () => string }[] = [
  { id: "style", label: () => tr("news_desk.workbench.tab_style") },
  { id: "export", label: () => tr("news_desk.workbench.tab_export") },
];

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export function NewsDeskWorkbench(props: {
  type: string;
  instance: string;
  onClose: () => void;
}) {
  const { type, instance, onClose } = props;
  const [components, setComponents] = useState<Component[] | null>(null);
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("style");
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set<Tab>(["style"]));
  const showTab = useCallback((t: Tab) => {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
  }, []);

  useEffect(() => {
    let alive = true;
    setComponents(null);
    setError("");
    setSelectedId(null);
    void (async () => {
      try {
        const cs = await rpc.listComponents(type, instance);
        if (alive) setComponents(cs);
      } catch (err) {
        if (alive) setError(fmt(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [type, instance]);

  // Patch fields of one component → persist → splice the returned component back
  // into state (no full reload, so editing stays snappy). Mirrors ClipWorkbench.
  const patch = useCallback(
    async (comp: Component, fields: Record<string, unknown>) => {
      setSavingId(comp.id);
      setError("");
      try {
        const updated = await rpc.updateComponent(type, instance, comp.id, fields);
        setComponents((prev) => prev?.map((c) => (c.id === comp.id ? updated : c)) ?? null);
      } catch (err) {
        setError(fmt(err));
      } finally {
        setSavingId(null);
      }
    },
    [type, instance],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px 0" }}>
        <strong>{instance}</strong>
        <span style={{ color: "#777", fontSize: 12 }}>{type}</span>
        <button
          onClick={onClose}
          style={{
            marginLeft: "auto",
            padding: "2px 9px",
            background: "#2a2a2e",
            color: "#ddd",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          ✕
        </button>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 4, padding: "8px 16px 0", borderBottom: "1px solid #2a2a2e" }}>
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => showTab(t.id)}
              style={{
                padding: "6px 14px",
                background: "transparent",
                color: active ? "#fff" : "#999",
                border: "none",
                borderBottom: active ? "2px solid #2d6cdf" : "2px solid transparent",
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {t.label()}
            </button>
          );
        })}
      </div>

      {error && <p style={{ color: "#ff6b6b", padding: "8px 16px 0" }}>✗ {error}</p>}

      <div style={{ flex: 1, overflow: "auto" }}>
        {visited.has("style") && (
          <div style={{ display: tab === "style" ? "contents" : "none" }}>
            <StyleTab
              type={type}
              instance={instance}
              components={components}
              selectedId={selectedId}
              savingId={savingId}
              onSelect={setSelectedId}
              onPatch={(c, f) => void patch(c, f)}
              onComponentsReplaced={setComponents}
            />
          </div>
        )}
        {visited.has("export") && (
          <div style={{ display: tab === "export" ? "contents" : "none" }}>
            <ExportTab
              type={type}
              instance={instance}
              components={components}
              active={tab === "export"}
            />
          </div>
        )}
      </div>
    </div>
  );
}
