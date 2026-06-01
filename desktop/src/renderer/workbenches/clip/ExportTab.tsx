/**
 * Export tab (导出) — faithful port of clip_tool.py::_build_tab_export.
 *
 * Batch-renders the selected candidates to mp4 (GPU/WebCodecs), one row per
 * candidate: "#out · 源#N · 时长 · 状态 · hook". The render runs here (the
 * renderer owns the GPU); the sidecar owns paths/naming/sidecar-JSON/rendered[]
 * (creation.plan_render → encode → vc:writeFile → creation.commit_render).
 *
 * Per-row actions (faithful to _on_act_*): play / open folder / rerender /
 * delete / error detail. Cancel stops between clips and mid-encode.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { tr } from "../../i18n/tr";
import { rpc, RpcError, type Component, type RenderPlan, type RenderedClip } from "../../ipc/client";
import { buildClipTimeline } from "@creations/clip/assemble.js";
import type { ClipComponentConfig } from "@creations/clip/types.js";
import { Backend } from "../../engine/gpu/Backend";
import { MediaSource } from "../../engine/source/MediaSource";
import { ClipReader } from "../../engine/source/ClipReader";
import { AudioReader } from "../../engine/source/AudioReader";
import { preloadImageOverlay } from "../../engine/overlay/canvas2d";
import { exportTimelineToMp4, ExportCancelled } from "../../engine/export/encode";
import { useClipPreview } from "./useClipPreview";
import { centerCropRect, parseAspect, targetDimsForAspect, type CropRect } from "./cropEditor";

const SOURCE_REF = "source";
const FPS = 30;

type RowStatus = "queued" | "rendering" | "done" | "failed";
interface Row {
  srcIdx: number;
  outIdx: number;
  outputPath: string;
  status: RowStatus;
  progress: number; // 0..1 while rendering
  error?: string;
  file?: string; // rendered basename (for play/open/delete)
}

function even(n: number): number {
  return n - (n % 2);
}

export function ExportTab(props: {
  type: string;
  instance: string;
  components: Component[] | null;
  /** True when this tab is the visible one (tabs are kept mounted/hidden). */
  active: boolean;
}) {
  const { type, instance, components, active } = props;
  const { status, message, data, reload } = useClipPreview(type, instance);

  const [plan, setPlan] = useState<RenderPlan | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [rendering, setRendering] = useState(false);
  const [err, setErr] = useState("");
  const cancelRef = useRef(false);
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);

  // Build the queue (selected candidates) merged with prior rendered[] state.
  // Preserve a row's live failed/rendering state across reloads — those aren't
  // in rendered[] (only successes are), so a naive rebuild would wipe a failure
  // back to "queued" and the error would vanish.
  const rebuildRows = useCallback((p: RenderPlan | null, rendered: RenderedClip[]) => {
    if (!p) {
      setRows([]);
      return;
    }
    const byOut = new Map(rendered.map((r) => [r.output_index, r]));
    setRows((prev) => {
      const prevByOut = new Map(prev.map((r) => [r.outIdx, r]));
      return p.clips.map((c) => {
        const done = byOut.get(c.outIdx);
        if (done) {
          return {
            srcIdx: c.srcIdx,
            outIdx: c.outIdx,
            outputPath: c.outputPath,
            status: "done" as RowStatus,
            progress: 1,
            file: done.file,
          };
        }
        const old = prevByOut.get(c.outIdx);
        if (old && (old.status === "failed" || old.status === "rendering")) {
          return { ...old, srcIdx: c.srcIdx, outIdx: c.outIdx, outputPath: c.outputPath };
        }
        return {
          srcIdx: c.srcIdx,
          outIdx: c.outIdx,
          outputPath: c.outputPath,
          status: "queued" as RowStatus,
          progress: 0,
        };
      });
    });
  }, []);

  const refresh = useCallback(async () => {
    setErr("");
    try {
      const p = await rpc.planRender(type, instance);
      setPlan(p);
      reload(); // refresh overrides/selection/rendered in the shared data
      rebuildRows(p, data?.rendered ?? []);
    } catch (e) {
      setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    }
  }, [type, instance, reload, rebuildRows, data?.rendered]);

  // Initial plan once the shared data is ready.
  useEffect(() => {
    if (status === "ready" && data && !plan) void refresh();
  }, [status, data, plan, refresh]);

  // Re-plan whenever this tab becomes visible — the selection (and overrides)
  // are edited in the Candidates tab while this one stays mounted/hidden, so
  // re-read on activation to reflect the current selected_clip_indices.
  useEffect(() => {
    if (active && status === "ready" && !rendering) void refresh();
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep rows' done-state in step when rendered[] refreshes.
  useEffect(() => {
    if (plan && data) rebuildRows(plan, data.rendered);
  }, [data?.rendered]); // eslint-disable-line react-hooks/exhaustive-deps

  const candidateFor = (srcIdx: number) => data?.candidates[srcIdx];

  const runRender = useCallback(
    async (only?: number) => {
      if (!data || rendering) return;
      cancelRef.current = false;
      setErr("");
      setRendering(true);

      let backend: Backend | null = null;
      let reader: ClipReader | null = null;
      try {
        // Fresh plan from disk (selection/overrides may have changed elsewhere).
        const p = await rpc.planRender(type, instance);
        setPlan(p);
        let clips = p.clips;
        if (only != null) clips = clips.filter((c) => c.srcIdx === only);
        if (clips.length === 0) {
          setErr(tr("clip.export.no_selected"));
          return;
        }

        const canvas = hiddenCanvasRef.current;
        if (!canvas) throw new Error("no render canvas");
        const ms = await MediaSource.open(window.vc.mediaUrl(data.srcPath));
        reader = new ClipReader(ms);
        backend = new Backend();
        await backend.init(canvas);

        const srcW = ms.width || 1280;
        const srcH = ms.height || 720;
        const aspect = parseAspect(p.aspect);
        const isPassthrough = p.mode === "passthrough";
        const target = isPassthrough
          ? { width: even(srcW), height: even(srcH) }
          : targetDimsForAspect(p.aspect, p.shortEdge);
        backend.resize(target.width, target.height);
        const overlayCanvas = new OffscreenCanvas(target.width, target.height);
        const overlayCtx = overlayCanvas.getContext("2d");
        if (!overlayCtx) throw new Error("failed to get 2d context");
        const drawDeps = {
          backend,
          sources: new Map([[SOURCE_REF, reader]]),
          fit: "contain" as const,
          overlayCanvas,
          overlayCtx,
        };

        // Decode the source audio once (shared across candidates); the export
        // mixes + muxes it per candidate window. Undefined when the source is
        // silent / has no audio track.
        // decodeAll() self-detects audio and returns null for a silent source —
        // do NOT gate on ms.audio (the fragile mp4box probe we route around).
        const decodedAudio = await new AudioReader(window.vc.mediaUrl(data.srcPath)).decodeAll();
        const audioSources = decodedAudio
          ? new Map([[SOURCE_REF, decodedAudio]])
          : undefined;

        // Preload any image-watermark assets once.
        for (const c of components ?? []) {
          if (c.kind === "clip_image_watermark") {
            const ip = c["image_path"];
            if (typeof ip === "string" && ip) {
              try {
                await preloadImageOverlay(ip, window.vc.mediaUrl(ip));
              } catch {
                /* unloadable → renders without it */
              }
            }
          }
        }

        for (const clip of clips) {
          if (cancelRef.current) break;
          setRows((rs) =>
            rs.map((r) => (r.outIdx === clip.outIdx ? { ...r, status: "rendering", progress: 0 } : r)),
          );
          const candidate = candidateFor(clip.srcIdx);
          if (!candidate) continue;
          const override = data.overrides[clip.srcIdx];
          try {
            const tl = buildClipTimeline({
              components: (components ?? []) as unknown as ClipComponentConfig[],
              candidate,
              srtByLang: data.srtByLang,
              mediaRef: SOURCE_REF,
              frameAspect: target.width / target.height,
              ...(override ? { override } : {}),
            });
            const cropRect: CropRect | undefined = isPassthrough
              ? undefined
              : (clip.cropRect ?? centerCropRect(srcW, srcH, aspect.aw, aspect.ah));
            const bytes = await exportTimelineToMp4({
              timeline: tl,
              drawDeps,
              backend,
              width: target.width,
              height: target.height,
              fps: FPS,
              durationSec: tl.durationSec,
              ...(cropRect ? { cropRect } : {}),
              onProgress: (d, t) =>
                setRows((rs) =>
                  rs.map((r) => (r.outIdx === clip.outIdx ? { ...r, progress: d / t } : r)),
                ),
              cancelCheck: () => cancelRef.current,
              ...(audioSources ? { audioSources } : {}),
            });
            await window.vc.writeFile(clip.outputPath, bytes);
            const rendered = await rpc.commitRender(
              type,
              instance,
              clip.srcIdx,
              clip.outIdx,
              tl.durationSec,
            );
            const file = rendered.find((r) => r.output_index === clip.outIdx)?.file;
            setRows((rs) =>
              rs.map((r) =>
                r.outIdx === clip.outIdx
                  ? { ...r, status: "done", progress: 1, ...(file ? { file } : {}) }
                  : r,
              ),
            );
          } catch (e) {
            if (e instanceof ExportCancelled) break;
            const msg = e instanceof Error ? e.message : String(e);
            setRows((rs) =>
              rs.map((r) => (r.outIdx === clip.outIdx ? { ...r, status: "failed", error: msg } : r)),
            );
          }
        }
        reload();
      } catch (e) {
        setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
      } finally {
        reader?.dispose();
        backend?.dispose();
        setRendering(false);
      }
    },
    [type, instance, data, components, rendering, reload],
  );

  const absPath = (file?: string) => (plan && file ? `${plan.instanceDir}/${file}` : null);
  const onPlay = (file?: string) => {
    const p = absPath(file);
    if (p) void window.vc.openPath(p);
  };
  const onOpenFolder = (file?: string) => {
    const p = absPath(file);
    if (p) void window.vc.showInFolder(p);
  };
  const onDelete = async (outIdx: number) => {
    if (!window.confirm(tr("clip.export.delete_confirm", { outIdx }))) return;
    try {
      await rpc.deleteRender(type, instance, outIdx);
      reload();
    } catch (e) {
      setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    }
  };

  if (status === "loading") return <Centered>{tr("common.loading")}</Centered>;
  if (status === "nobind") return <Centered>{tr("clip.no_material_bound")}</Centered>;
  if (status === "nosrc") return <Centered>{tr("clip.no_source_video")}</Centered>;
  if (status === "error") return <Centered>✗ {message}</Centered>;

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
      <canvas ref={hiddenCanvasRef} style={{ display: "none" }} />

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button onClick={() => void runRender()} disabled={rendering || rows.length === 0} style={primaryBtn}>
          {rendering ? tr("clip.export.rendering") : tr("clip.export.render_btn", { count: rows.length })}
        </button>
        {rendering && (
          <button onClick={() => (cancelRef.current = true)} style={btn}>
            {tr("common.cancel")}
          </button>
        )}
        <button onClick={() => void refresh()} disabled={rendering} style={btn}>
          {tr("clip.export.refresh")}
        </button>
        {err && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {err}</span>}
      </div>

      {rows.length === 0 ? (
        <p style={{ color: "#888", fontSize: 13 }}>{tr("clip.export.empty_hint")}</p>
      ) : (
        <div style={{ flex: 1, overflow: "auto", border: "1px solid #2a2a2e", borderRadius: 6 }}>
          <div
            style={{
              ...rowStyle,
              color: "#888",
              fontWeight: 600,
              position: "sticky",
              top: 0,
              background: "#1a1a1e",
            }}
          >
            <span style={{ width: 36 }}>#</span>
            <span style={{ width: 56 }}>{tr("clip.export.col_source")}</span>
            <span style={{ width: 70 }}>{tr("clip.export.col_duration")}</span>
            <span style={{ width: 90 }}>{tr("clip.export.col_status")}</span>
            <span style={{ flex: 1 }}>Hook</span>
            <span style={{ width: 150 }}>{tr("clip.export.col_actions")}</span>
          </div>
          {rows.map((r) => {
            const cand = candidateFor(r.srcIdx);
            const dur =
              typeof cand?.duration_sec === "number" ? `${cand.duration_sec.toFixed(1)}s` : "";
            const hook = (cand?.hook || cand?.suggested_title || "").trim();
            return (
              <div
                key={r.outIdx}
                onDoubleClick={() => r.status === "done" && onPlay(r.file)}
                style={{ ...rowStyle, borderTop: "1px solid #222" }}
              >
                <span style={{ width: 36 }}>{r.outIdx}</span>
                <span style={{ width: 56, color: "#888" }}>#{r.srcIdx + 1}</span>
                <span style={{ width: 70, color: "#aaa" }}>{dur}</span>
                <span style={{ width: 90 }}>{statusLabel(r)}</span>
                <span
                  style={{
                    flex: 1,
                    color: r.status === "failed" ? "#ff6b6b" : "#ddd",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={r.status === "failed" ? r.error : hook}
                >
                  {r.status === "failed" ? `✗ ${r.error || tr("clip.export.no_error_info")}` : hook}
                </span>
                <span style={{ width: 150, display: "flex", gap: 4 }}>
                  {r.status === "done" && (
                    <>
                      <button onClick={() => onPlay(r.file)} style={rowBtn} title={tr("clip.export.action_play")}>▶</button>
                      <button onClick={() => onOpenFolder(r.file)} style={rowBtn} title={tr("clip.export.action_open_folder")}>📁</button>
                      <button onClick={() => void runRender(r.srcIdx)} disabled={rendering} style={rowBtn} title={tr("clip.export.action_rerender")}>↻</button>
                      <button onClick={() => void onDelete(r.outIdx)} disabled={rendering} style={rowBtn} title={tr("common.delete")}>🗑</button>
                    </>
                  )}
                  {r.status === "failed" && (
                    <button onClick={() => window.alert(r.error || tr("clip.export.no_error_info"))} style={rowBtn} title={tr("clip.export.action_error_detail")}>
                      ⚠ {tr("clip.export.action_error_detail_short")}
                    </button>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function statusLabel(r: Row): React.ReactNode {
  switch (r.status) {
    case "queued":
      return <span style={{ color: "#888" }}>{tr("clip.export.status_queued")}</span>;
    case "rendering":
      return <span style={{ color: "#4a9eff" }}>{tr("clip.export.status_rendering", { pct: Math.round(r.progress * 100) })}</span>;
    case "done":
      return <span style={{ color: "#3ecf8e" }}>✓ {tr("clip.export.status_done")}</span>;
    case "failed":
      return <span style={{ color: "#ff6b6b" }}>✗ {tr("clip.export.status_failed")}</span>;
  }
}

function Centered(props: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: 24,
        color: "#777",
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
      }}
    >
      {props.children}
    </div>
  );
}

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 10px",
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
};
const btn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ddd",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "4px 12px",
  fontSize: 12,
  cursor: "pointer",
};
const primaryBtn: React.CSSProperties = { ...btn, background: "#2d6cdf", color: "#fff", border: "none" };
const rowBtn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "1px 6px",
  fontSize: 12,
  cursor: "pointer",
};
