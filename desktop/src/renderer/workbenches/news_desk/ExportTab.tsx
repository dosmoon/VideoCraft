/**
 * Export tab (导出) — news_desk composes the FULL source into ONE output
 * (news_desk_tool.py::_do_export), unlike clip's per-candidate batch.
 *
 * The render runs here (the renderer owns the GPU); the sidecar owns
 * paths/naming/sidecar-JSON/rendered[] (creation.plan_render → encode →
 * vc:writeFile → creation.commit_render). Mirrors clip's ExportTab render loop
 * but for a single full-source output: no candidate iteration, no reframe crop,
 * target = source dimensions, out_idx pinned to 1 (src_idx unused).
 *
 * One compositor feeds preview and export via buildNewsDeskTimeline →
 * resolveFrameAt → encode, so the exported mp4 ≡ what the Style-tab preview
 * shows.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { rpc, rpcCall, RpcError, type Component } from "../../ipc/client";
import { buildNewsDeskTimeline } from "@creations/news_desk/assemble.js";
import type { NewsDeskComponentConfig } from "@creations/news_desk/types.js";
import { Backend } from "../../engine/gpu/Backend";
import { MediaSource } from "../../engine/source/MediaSource";
import { ClipReader } from "../../engine/source/ClipReader";
import { AudioReader } from "../../engine/source/AudioReader";
import { preloadImageOverlay } from "../../engine/overlay/canvas2d";
import { exportTimelineToMp4, ExportCancelled } from "../../engine/export/encode";
import { useNewsDeskPreview } from "./useNewsDeskPreview";

const SOURCE_REF = "source";
const FPS = 30;

/** news_desk render plan (creation.plan_render — single full-source output). */
interface NewsDeskRenderPlan {
  instanceDir: string;
  mediaRef: string | null;
  durationSec: number;
  outIdx: number;
  outputPath: string;
}

interface RenderedEntry {
  file: string;
  output_index: number;
  duration_sec: number;
  rendered_at: string;
}

type RenderStatus = "idle" | "rendering" | "done" | "failed";

function even(n: number): number {
  return n - (n % 2);
}

function fmtErr(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

function fmtDuration(sec: number): string {
  if (!sec || sec <= 0) return "—";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export function ExportTab(props: {
  type: string;
  instance: string;
  components: Component[] | null;
  active: boolean;
}) {
  const { type, instance, components, active } = props;
  const { status: previewStatus, message: previewMsg, data, reload } = useNewsDeskPreview(type, instance);

  const [plan, setPlan] = useState<NewsDeskRenderPlan | null>(null);
  const [rendered, setRendered] = useState<RenderedEntry[]>([]);
  const [renderStatus, setRenderStatus] = useState<RenderStatus>("idle");
  const [progress, setProgress] = useState(0); // 0..1 while rendering
  const [error, setError] = useState("");
  const cancelRef = useRef(false);
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [p, cfg] = await Promise.all([
        rpcCall<NewsDeskRenderPlan>("creation.plan_render", { type, instance }),
        rpcCall<Record<string, unknown>>("creation.load_config", { type, instance }),
      ]);
      setPlan(p);
      const r = cfg["rendered"];
      setRendered(Array.isArray(r) ? (r as RenderedEntry[]) : []);
    } catch (err) {
      setError(fmtErr(err));
    }
  }, [type, instance]);

  // Refresh plan/rendered + preview inputs when this tab becomes active (the
  // Style tab may have changed config / imported new subtitles meanwhile).
  useEffect(() => {
    if (active) {
      void refresh();
      reload();
    }
  }, [active, refresh, reload]);

  const runRender = useCallback(async () => {
    if (renderStatus === "rendering") return;
    if (!data) {
      setError("源数据未就绪");
      return;
    }
    cancelRef.current = false;
    setError("");
    setProgress(0);
    setRenderStatus("rendering");

    let backend: Backend | null = null;
    let reader: ClipReader | null = null;
    try {
      // Fresh plan from disk (config may have changed in the Style tab).
      const p = await rpcCall<NewsDeskRenderPlan>("creation.plan_render", { type, instance });
      setPlan(p);
      if (!p.mediaRef) throw new Error("未绑定素材 — 无法导出");

      const canvas = hiddenCanvasRef.current;
      if (!canvas) throw new Error("no render canvas");
      const ms = await MediaSource.open(window.vc.mediaUrl(data.srcPath));
      reader = new ClipReader(ms);
      backend = new Backend();
      await backend.init(canvas);

      // Full-source render → target = source dimensions (even for the encoder).
      const srcW = even(ms.width || 1280);
      const srcH = even(ms.height || 720);
      const durationSec = ms.durationUs / 1_000_000 || data.durationSec;
      backend.resize(srcW, srcH);
      const overlayCanvas = new OffscreenCanvas(srcW, srcH);
      const overlayCtx = overlayCanvas.getContext("2d");
      if (!overlayCtx) throw new Error("failed to get 2d context");
      const drawDeps = {
        backend,
        sources: new Map([[SOURCE_REF, reader]]),
        fit: "contain" as const,
        overlayCanvas,
        overlayCtx,
      };

      // Decode the source audio once. decodeAll() self-detects audio and returns
      // null for a silent source — do NOT gate on ms.audio (fragile mp4box probe).
      const decodedAudio = await new AudioReader(window.vc.mediaUrl(data.srcPath)).decodeAll();
      const audioSources = decodedAudio ? new Map([[SOURCE_REF, decodedAudio]]) : undefined;

      // Preload any image-watermark assets once.
      for (const c of components ?? []) {
        if (c.kind === "image_watermark") {
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

      const tl = buildNewsDeskTimeline({
        components: (components ?? []) as unknown as NewsDeskComponentConfig[],
        durationSec,
        cuesBySrtPath: data.cuesBySrtPath,
        mediaRef: SOURCE_REF,
        frameAspect: srcW / srcH,
      });

      const bytes = await exportTimelineToMp4({
        timeline: tl,
        drawDeps,
        backend,
        width: srcW,
        height: srcH,
        fps: FPS,
        durationSec: tl.durationSec,
        onProgress: (d, t) => setProgress(d / t),
        cancelCheck: () => cancelRef.current,
        ...(audioSources ? { audioSources } : {}),
      });
      await window.vc.writeFile(p.outputPath, bytes);
      // src_idx unused for news_desk; out_idx pinned to 1.
      const list = await rpc.commitRender(type, instance, 0, p.outIdx, tl.durationSec);
      setRendered(list as RenderedEntry[]);
      setRenderStatus("done");
      setProgress(1);
    } catch (e) {
      if (e instanceof ExportCancelled) {
        setRenderStatus("idle");
      } else {
        setError(fmtErr(e));
        setRenderStatus("failed");
      }
    } finally {
      reader?.dispose();
      backend?.dispose();
    }
  }, [type, instance, data, components, renderStatus]);

  const absPath = (file?: string) => (plan && file ? `${plan.instanceDir}/${file}` : null);
  const onPlay = (file?: string) => {
    const p = absPath(file);
    if (p) void window.vc.openPath(p);
  };
  const onOpenFolder = (file?: string) => {
    const p = absPath(file);
    if (p) void window.vc.showInFolder(p);
  };
  const onDelete = async () => {
    if (!plan) return;
    if (!window.confirm("删除已渲染的输出？")) return;
    try {
      await rpc.deleteRender(type, instance, plan.outIdx);
      setRendered([]);
      setRenderStatus("idle");
    } catch (e) {
      setError(fmtErr(e));
    }
  };

  const row: React.CSSProperties = { display: "flex", gap: 10, padding: "4px 0", fontSize: 13 };
  const keyStyle: React.CSSProperties = { color: "#888", minWidth: 90 };
  const valStyle: React.CSSProperties = { color: "#ddd", wordBreak: "break-all" };
  const rendering = renderStatus === "rendering";
  const canRender = !rendering && !!plan?.mediaRef && previewStatus === "ready";

  return (
    <div style={{ padding: 16 }}>
      <canvas ref={hiddenCanvasRef} style={{ display: "none" }} />

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <button onClick={() => void runRender()} disabled={!canRender} style={primaryBtn}>
          {rendering ? `渲染中… ${Math.round(progress * 100)}%` : "渲染整源"}
        </button>
        {rendering && (
          <button onClick={() => (cancelRef.current = true)} style={btn}>
            取消
          </button>
        )}
        <button onClick={() => void refresh()} disabled={rendering} style={btn}>
          刷新
        </button>
        {renderStatus === "done" && !rendering && (
          <span style={{ color: "#3ecf8e", fontSize: 12 }}>✓ 完成</span>
        )}
        {error && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {error}</span>}
      </div>

      {previewStatus === "nobind" && (
        <p style={{ color: "#888", fontSize: 12 }}>未绑定素材 — 无法导出</p>
      )}
      {previewStatus === "nosrc" && (
        <p style={{ color: "#888", fontSize: 12 }}>绑定素材尚无源视频</p>
      )}
      {previewStatus === "error" && (
        <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {previewMsg}</p>
      )}

      {plan && plan.mediaRef && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
            渲染计划(整源单输出)
          </div>
          <div style={row}>
            <span style={keyStyle}>时长</span>
            <span style={valStyle}>{fmtDuration(plan.durationSec)}</span>
          </div>
          <div style={row}>
            <span style={keyStyle}>输出文件</span>
            <span style={valStyle}>{plan.outputPath}</span>
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
        已渲染
      </div>
      {rendered.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>尚未渲染</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {rendered.map((r) => (
            <li
              key={r.output_index}
              style={{ ...row, borderBottom: "1px solid #222", alignItems: "center" }}
            >
              <span style={valStyle}>{r.file}</span>
              <span style={{ color: "#777" }}>{fmtDuration(r.duration_sec)}</span>
              <span style={{ color: "#666", marginLeft: "auto" }}>{r.rendered_at}</span>
              <span style={{ display: "flex", gap: 4 }}>
                <button onClick={() => onPlay(r.file)} style={rowBtn} title="播放">▶</button>
                <button onClick={() => onOpenFolder(r.file)} style={rowBtn} title="打开文件夹">📁</button>
                <button onClick={() => void onDelete()} disabled={rendering} style={rowBtn} title="删除">🗑</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
