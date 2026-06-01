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
import { tr } from "../../i18n/tr";
import { rpc, RpcError, type Component } from "../../ipc/client";
import { StyleTab } from "./StyleTab";
import { ClipsTab } from "./ClipsTab";
import { ExportTab } from "./ExportTab";

type Tab = "style" | "clips" | "export";

const TAB_IDS: Tab[] = ["style", "clips", "export"];
const TAB_LABEL_KEYS: Record<Tab, string> = {
  style: "clip.tab.style",
  clips: "clip.tab.clips",
  export: "clip.tab.export",
};

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
  // Tabs are mounted on first visit and kept alive (hidden via display) so
  // switching tabs never re-opens the GPU preview engine — faithful to the Tk
  // notebook, whose tab widgets persisted.
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set<Tab>(["style"]));
  const showTab = useCallback((t: Tab) => {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
  }, []);
  // Shared binding refresh key: bumped when the Style tab's binding bar (re-)binds
  // a material. Threaded into every tab's useClipPreview so all three reload the
  // source/candidates — not just the Style tab where the bar lives. (Mirrors
  // MaterialWorkbench's shared refreshKey.)
  const [bindRefreshKey, setBindRefreshKey] = useState(0);
  const onMaterialBound = useCallback(() => setBindRefreshKey((k) => k + 1), []);

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
        {TAB_IDS.map((id) => {
          const active = tab === id;
          return (
            <button
              key={id}
              onClick={() => showTab(id)}
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
              {tr(TAB_LABEL_KEYS[id])}
            </button>
          );
        })}
      </div>

      {error && <p style={{ color: "#ff6b6b", padding: "8px 16px 0" }}>✗ {error}</p>}

      {/* Each tab is mounted on first visit and kept in the DOM afterwards
          (display:contents when active, none when hidden) so its preview engine
          isn't torn down and rebuilt on every tab switch. */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {visited.has("style") && (
          <div style={{ display: tab === "style" ? "contents" : "none" }}>
            <StyleTab
              type={type}
              instance={instance}
              components={components}
              selectedId={selectedId}
              savingId={savingId}
              refreshKey={bindRefreshKey}
              onMaterialBound={onMaterialBound}
              onSelect={setSelectedId}
              onPatch={(c, f) => void patch(c, f)}
              onComponentsReplaced={setComponents}
            />
          </div>
        )}
        {visited.has("clips") && (
          <div style={{ display: tab === "clips" ? "contents" : "none" }}>
            <ClipsTab type={type} instance={instance} components={components} refreshKey={bindRefreshKey} />
          </div>
        )}
        {visited.has("export") && (
          <div style={{ display: tab === "export" ? "contents" : "none" }}>
            <ExportTab
              type={type}
              instance={instance}
              components={components}
              active={tab === "export"}
              refreshKey={bindRefreshKey}
            />
          </div>
        )}
      </div>
    </div>
  );
}
