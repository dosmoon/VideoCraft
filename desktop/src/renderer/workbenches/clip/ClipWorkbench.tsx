/**
 * ClipWorkbench — the per-plugin clip workbench (migration §3.1), faithfully
 * shaped as the original three-tab Tk workbench (clip_tool.py docstring):
 * 样式 Style / 候选 Clips / 导出 Export.
 *
 * This shell owns the cross-tab state — the loaded component list, the
 * component-patch write path (creation.update_component → persist → splice),
 * and the active tab — and hands each tab the slice it needs. Inc2 fills the
 * Style tab with the real (already-built) preview + component + property
 * editing; the Clips and Export tabs are honest stubs for Inc3 / Inc5.
 *
 * The Hub hosts this generically (dispatch by creation type); the Hub knows
 * nothing clip-specific.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type Component } from "../../ipc/client";
import { StyleTab } from "./StyleTab";
import { ClipsTab } from "./ClipsTab";
import { ExportTab } from "./ExportTab";

type Tab = "style" | "clips" | "export";

const TABS: { id: Tab; label: string }[] = [
  { id: "style", label: "样式" },
  { id: "clips", label: "候选" },
  { id: "export", label: "导出" },
];

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export function ClipWorkbench(props: { type: string; instance: string; onClose: () => void }) {
  const { type, instance, onClose } = props;
  const [components, setComponents] = useState<Component[] | null>(null);
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("style");

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

  // Patch fields of one component → persist → splice the returned component
  // back into state (no full reload, so editing stays snappy).
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 16px 0",
        }}
      >
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
              onClick={() => setTab(t.id)}
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
              {t.label}
            </button>
          );
        })}
      </div>

      {error && <p style={{ color: "#ff6b6b", padding: "8px 16px 0" }}>✗ {error}</p>}

      <div style={{ flex: 1, overflow: "auto" }}>
        {tab === "style" && (
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
        )}
        {tab === "clips" && <ClipsTab type={type} instance={instance} components={components} />}
        {tab === "export" && <ExportTab type={type} instance={instance} />}
      </div>
    </div>
  );
}
