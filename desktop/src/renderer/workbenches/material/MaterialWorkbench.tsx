/**
 * MaterialWorkbench — the per-plugin news_video material workbench, shaped after
 * the Tk sidebar's three-slot model (materials/news_video/ui/node_panes.py):
 * source / subtitles / news_context map 1:1 to three tabs. Unlike a creation
 * workbench (which edits a config.json via a single owner), the material side
 * drives the NewsVideoModel through RPC: source acquisition, ASR / translate /
 * chapter analysis (all sidecar jobs), and the 15-field context.
 *
 * The shell owns the slot-readiness snapshot (which gates the locked tabs) and a
 * refresh counter bumped whenever a tab mutates the instance, so sibling tabs
 * and the gate re-read. The Hub dispatches to this generically by material type.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type SlotState } from "../../ipc/client";
import { SourceTab } from "./SourceTab";
import { SubtitlesTab } from "./SubtitlesTab";
import { ContextTab } from "./ContextTab";

type Tab = "source" | "subtitles" | "context";

const TABS: { id: Tab; label: string; slot: string }[] = [
  { id: "source", label: "源视频", slot: "source" },
  { id: "subtitles", label: "字幕与分析", slot: "subtitles" },
  { id: "context", label: "新闻背景", slot: "news_context" },
];

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export function MaterialWorkbench(props: { type: string; instance: string; onClose: () => void }) {
  const { type, instance, onClose } = props;
  const [readiness, setReadiness] = useState<Record<string, SlotState> | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("source");
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set<Tab>(["source"]));
  // Bumped whenever a tab mutates the instance; tabs + the gate re-read on change.
  const [refreshKey, setRefreshKey] = useState(0);
  const onChanged = useCallback(() => setRefreshKey((k) => k + 1), []);

  const showTab = useCallback((t: Tab) => {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const r = await rpc.slotReadiness(type, instance);
        if (alive) setReadiness(r);
      } catch (err) {
        if (alive) setError(fmt(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [type, instance, refreshKey]);

  const sourceReady = readiness?.source?.is_filled ?? false;

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

      <div style={{ display: "flex", gap: 4, padding: "8px 16px 0", borderBottom: "1px solid #2a2a2e" }}>
        {TABS.map((t) => {
          const active = tab === t.id;
          // Subtitles + context are gated on source readiness (model's lock rule).
          const locked = t.id !== "source" && !sourceReady;
          return (
            <button
              key={t.id}
              onClick={() => showTab(t.id)}
              title={locked ? "待源视频就绪" : undefined}
              style={{
                padding: "6px 14px",
                background: "transparent",
                color: active ? "#fff" : locked ? "#666" : "#999",
                border: "none",
                borderBottom: active ? "2px solid #2d6cdf" : "2px solid transparent",
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {locked ? "🔒 " : ""}
              {t.label}
            </button>
          );
        })}
      </div>

      {error && <p style={{ color: "#ff6b6b", padding: "8px 16px 0" }}>✗ {error}</p>}

      <div style={{ flex: 1, overflow: "auto" }}>
        {visited.has("source") && (
          <div style={{ display: tab === "source" ? "block" : "none", padding: 16 }}>
            <SourceTab type={type} instance={instance} refreshKey={refreshKey} onChanged={onChanged} />
          </div>
        )}
        {visited.has("subtitles") && (
          <div style={{ display: tab === "subtitles" ? "block" : "none", padding: 16 }}>
            {sourceReady ? (
              <SubtitlesTab
                type={type}
                instance={instance}
                refreshKey={refreshKey}
                onChanged={onChanged}
              />
            ) : (
              <Locked />
            )}
          </div>
        )}
        {visited.has("context") && (
          <div style={{ display: tab === "context" ? "block" : "none", padding: 16 }}>
            {sourceReady ? (
              <ContextTab type={type} instance={instance} refreshKey={refreshKey} onChanged={onChanged} />
            ) : (
              <Locked />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Locked() {
  return <div style={{ color: "#666", fontSize: 13 }}>🔒 待源视频就绪</div>;
}
