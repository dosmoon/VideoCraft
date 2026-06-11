/**
 * Candidates tab (候选) — faithful port of clip_tool.py::_build_tab_clips +
 * clip_editor.py::ClipDetailPanel.
 *
 * Left: the candidate list. Each row is "#N · start→end · Ns · ⭐score" plus the
 * hook line, with two distinct interactions (mirrors _render_candidate_row):
 *   - the ☑ checkbox includes the candidate in the batch (→ selected_clip_indices)
 *   - clicking the row body opens that candidate's detail panel
 * Plus select-all / select-none and a "selected / total" header.
 *
 * Right: the selected candidate's detail editor (ClipDetailPanel) — its own
 * preview + crop, start/end nudge, hook/outro/title/tags overrides, SRT cues.
 *
 * Selection writes selected_clip_indices via creation.update_config; detail
 * edits write per-candidate overrides. Both go through the single config owner.
 */

import { useEffect, useMemo, useState } from "react";
import { tr } from "../../i18n/tr";
import { rpc, RpcError, type Component } from "../../ipc/client";
import type { HotclipCandidate } from "@creations/clip/types.js";
import { useClipPreview } from "./useClipPreview";
import { ClipDetailPanel } from "./ClipDetailPanel";

/** ⭐ colour by virality score — mirrors _render_candidate_row (≥8 / ≥6 / else). */
function scoreColor(score: number): string {
  if (score >= 8) return "#e0564f";
  if (score >= 6) return "#d97706";
  return "#888";
}

export function ClipsTab(props: {
  type: string;
  instance: string;
  components: Component[] | null;
  /** True when this tab is the visible one (tabs are kept mounted/hidden). */
  active: boolean;
  /** Shared binding refresh key — reload source/candidates when (re-)bound. */
  refreshKey: number;
}) {
  const { type, instance, components, active, refreshKey } = props;
  // Bumped after the one-time candidate-language pick — forces a full preview
  // reload (candidates change), which the lightweight reload() can't do.
  const [langBump, setLangBump] = useState(0);
  const { status, message, data, reload } = useClipPreview(type, instance, refreshKey + langBump);

  // Output config (mode / aspect) is edited in the Style tab while this one stays
  // mounted-but-hidden, so its preview data goes stale. Re-read config on
  // activation so the candidate previews follow reframe/letterbox/passthrough
  // (the lightweight reload patches mode/aspect in place — no engine reopen).
  useEffect(() => {
    if (active) reload();
  }, [active, reload]);

  // Batch selection (selected_clip_indices) — local truth, mirrored to the
  // sidecar. Detail panel index — which candidate's editor is open.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detailIdx, setDetailIdx] = useState<number | null>(null);
  const [selError, setSelError] = useState("");

  // Sync selection from config whenever it loads/refreshes (our writes keep the
  // server in step, so re-syncing to the same set is a no-op).
  useEffect(() => {
    if (data) setSelected(new Set(data.selectedIndices));
  }, [data]);

  // Auto-open the first selected (or first) candidate's detail — mirrors the
  // tail of _reload_candidates.
  useEffect(() => {
    if (!data || detailIdx !== null || data.candidates.length === 0) return;
    const firstSel = data.selectedIndices.find((i) => i >= 0 && i < data.candidates.length);
    setDetailIdx(firstSel ?? 0);
  }, [data, detailIdx]);

  const candidates = data?.candidates ?? [];
  const total = candidates.length;

  const writeSelection = async (next: Set<number>) => {
    setSelError("");
    const indices = [...next].sort((a, b) => a - b);
    try {
      await rpc.updateConfig(type, instance, { selected_clip_indices: indices });
    } catch (err) {
      setSelError(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
    }
  };

  const toggle = (i: number) => {
    const next = new Set(selected);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    setSelected(next);
    void writeSelection(next);
  };
  const selectAll = () => {
    const next = new Set(candidates.map((_, i) => i));
    setSelected(next);
    void writeSelection(next);
  };
  const selectNone = () => {
    const next = new Set<number>();
    setSelected(next);
    void writeSelection(next);
  };

  const detailCandidate: HotclipCandidate | null =
    detailIdx !== null ? candidates[detailIdx] ?? null : null;

  const headerLabel = useMemo(() => tr("clip.candidates.header", { sel: selected.size, total }), [selected.size, total]);

  if (status === "loading") return <Centered>{tr("clip.candidates.loading")}</Centered>;
  if (status === "nobind") return <Centered>{tr("clip.no_material_bound")}</Centered>;
  if (status === "nosrc") return <Centered>{tr("clip.no_source_video")}</Centered>;
  if (status === "error") return <Centered>✗ {message}</Centered>;
  if (!data) return <Centered>{tr("clip.candidates.no_data")}</Centered>;

  // Several hotclips languages exist and this instance hasn't picked one:
  // a one-time human decision, persisted to source_subtitle and then locked
  // (changing language mid-flight would mis-key selections/overrides).
  if (data.needsLangChoice) {
    const pickLang = async (l: string) => {
      setSelError("");
      try {
        await rpc.updateConfig(type, instance, { source_subtitle: l });
        setLangBump((b) => b + 1);
      } catch (err) {
        setSelError(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
      }
    };
    return (
      <Centered>
        <div style={{ textAlign: "center", maxWidth: 460 }}>
          <div style={{ color: "#ddd", fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
            {tr("clip.candidates.pick_lang")}
          </div>
          <div style={{ color: "#888", fontSize: 12, marginBottom: 16 }}>
            {tr("clip.candidates.pick_lang_hint")}
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
            {data.availableLangs.map((l) => (
              <button key={l} onClick={() => void pickLang(l)} style={langBtn}>
                {l.toUpperCase()}
              </button>
            ))}
          </div>
          {selError && <p style={{ color: "#ff6b6b", fontSize: 12, marginTop: 12 }}>✗ {selError}</p>}
        </div>
      </Centered>
    );
  }

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {/* Left: candidate list */}
      <div style={{ flex: "0 0 380px", borderRight: "1px solid #2a2a2e", display: "flex", flexDirection: "column" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 12px",
            borderBottom: "1px solid #2a2a2e",
          }}
        >
          <span style={{ fontSize: 12, color: "#bbb" }}>{headerLabel}</span>
          <button onClick={selectAll} style={hdrBtn}>{tr("clip.candidates.select_all")}</button>
          <button onClick={selectNone} style={hdrBtn}>{tr("clip.candidates.select_none")}</button>
        </div>
        {selError && <p style={{ color: "#ff6b6b", fontSize: 12, padding: "6px 12px", margin: 0 }}>✗ {selError}</p>}

        <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
          {total === 0 ? (
            <p style={{ color: "#888", fontSize: 13, padding: 8 }}>{tr("clip.candidates.empty")}</p>
          ) : (
            candidates.map((c, i) => {
              const isDetail = detailIdx === i;
              const dur = c.duration_sec;
              // Row shows the raw AI hook (faithful to _render_candidate_row,
              // which reads the hotclips dict, not the per-candidate override).
              const hook = (c.hook || c.suggested_title || "").trim();
              return (
                <div
                  key={i}
                  onClick={() => setDetailIdx(i)}
                  style={{
                    display: "flex",
                    gap: 8,
                    padding: "8px 8px",
                    marginBottom: 4,
                    borderRadius: 6,
                    border: `1px solid ${isDetail ? "#2d6cdf" : "#262629"}`,
                    background: isDetail ? "#172033" : "#1a1a1e",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(i)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggle(i)}
                    style={{ marginTop: 2 }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 0 }}>
                      <span style={{ color: "#888", fontWeight: 700, fontSize: 12 }}>#{i + 1}</span>
                      <span style={{ color: "#4a9eff", fontFamily: "Consolas, monospace", fontSize: 12, marginLeft: 6 }}>
                        {c.start} → {c.end}
                      </span>
                      {typeof dur === "number" && (
                        <span style={{ color: "#888", fontSize: 12, marginLeft: 6 }}>{Math.trunc(dur)}s</span>
                      )}
                      {c.score != null && (
                        <span
                          style={{
                            marginLeft: "auto",
                            color: scoreColor(c.score),
                            fontWeight: 700,
                            fontSize: 13,
                          }}
                        >
                          ⭐ {c.score}
                        </span>
                      )}
                    </div>
                    {hook && (
                      <div style={{ color: "#ddd", fontWeight: 600, fontSize: 13, marginTop: 3 }}>{hook}</div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Right: detail editor */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {detailCandidate && detailIdx !== null ? (
          // No `key` per index — keep the panel (and its GPU preview engine)
          // mounted across candidate switches; the panel resets its local field
          // state from props on candidateIndex change, and CropPreview just
          // rebuilds the timeline for the new window instead of re-opening.
          <ClipDetailPanel
            type={type}
            instance={instance}
            candidateIndex={detailIdx}
            candidate={detailCandidate}
            override={data.overrides[detailIdx]}
            components={components ?? []}
            srcPath={data.srcPath}
            srtByLang={data.srtByLang}
            lang={data.lang}
            mode={data.mode}
            aspect={data.aspect}
            onChanged={reload}
          />
        ) : (
          <Centered>{tr("clip.candidates.pick_to_edit")}</Centered>
        )}
      </div>
    </div>
  );
}

function Centered(props: { children: React.ReactNode }) {
  return (
    <div style={{ padding: 24, color: "#777", fontSize: 13, display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
      {props.children}
    </div>
  );
}

const hdrBtn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "2px 8px",
  fontSize: 12,
  cursor: "pointer",
};

const langBtn: React.CSSProperties = {
  background: "#172033",
  color: "#cfe0ff",
  border: "1px solid #2d6cdf",
  borderRadius: 6,
  padding: "8px 22px",
  fontSize: 14,
  fontWeight: 700,
  cursor: "pointer",
};
