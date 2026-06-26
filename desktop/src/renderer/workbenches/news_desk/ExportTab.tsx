/**
 * Export tab (导出) — news_desk composes the FULL source into ONE output
 * (news_desk_tool.py::_do_export), unlike clip's per-candidate batch.
 *
 * The render runs here (the renderer owns the GPU); the sidecar owns
 * paths/naming/sidecar-JSON/rendered[] (creation.plan_render → encode →
 * vc:writeFile → creation.commit_render). Mirrors clip's ExportTab render loop
 * but for a single full-source output: no candidate iteration, out_idx pinned to
 * 1 (src_idx unused). Output framing is a single instance-level reframe: default
 * passthrough = source dims (whole frame); reframe/letterbox target a chosen
 * aspect (the crop rides on the timeline clip via Clip.crop).
 *
 * One compositor feeds preview and export via buildNewsDeskTimeline →
 * resolveFrameAt → encode, so the exported mp4 ≡ what the Style-tab preview
 * shows.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { tr } from "../../i18n/tr";
import { confirmDialog } from "../../ui/confirm";
import { rpc, RpcError, type Component } from "../../ipc/client";
import { buildNewsDeskTimeline } from "@creations/news_desk/assemble.js";
import { chapterSegments } from "@creations/news_desk/render.js";
import type { NewsDeskComponentConfig } from "@creations/news_desk/types.js";
import { centerCropRect, parseAspect, targetDimsForAspect, type CropRect } from "@composition/crop.js";
import { Backend } from "../../engine/gpu/Backend";
import { MediaSource } from "../../engine/source/MediaSource";
import { ClipReader } from "../../engine/source/ClipReader";
import { AudioReader } from "../../engine/source/AudioReader";
import type { DecodedAudio } from "../../engine/source/sample-types";
import { preloadImageOverlay } from "../../engine/overlay/canvas2d";
import { exportTimelineToMp4, exportTimelineViaFfmpeg, ExportCancelled } from "../../engine/export/encode";
import { resolveBitrate } from "../../engine/export/types";
import { ExportSettingsBar } from "../common/ExportSettingsBar";
import {
  DEFAULT_EXPORT_SETTINGS,
  FULL_RESOLUTIONS,
  downscaleToShortEdge,
  effectiveEngine,
  exportSettingsFromConfig,
  normalizeResolution,
  type ExportSettings,
  type FfmpegProbe,
} from "@creations/exportSettings";
import { useNewsDeskPreview } from "./useNewsDeskPreview";

const SOURCE_REF = "source";

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
  const [framesDone, setFramesDone] = useState(0);
  const [framesTotal, setFramesTotal] = useState(0);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<ExportSettings>(DEFAULT_EXPORT_SETTINGS);
  const [probe, setProbe] = useState<FfmpegProbe | null>(null);
  // Off-by-default publish-side opt-in: after the main render, stream-copy the
  // output into chapters/*.mp4 (legacy news_desk_tool's "chapter_videos").
  const [splitByChapter, setSplitByChapter] = useState(false);
  const [splitNote, setSplitNote] = useState("");
  const splitByChapterRef = useRef(splitByChapter);
  splitByChapterRef.current = splitByChapter;
  const cancelRef = useRef(false);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const probeRef = useRef(probe);
  probeRef.current = probe;
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);

  // Probe ffmpeg/NVENC availability once (cached main-side) to enable the engine
  // option and resolve the auto-default engine.
  useEffect(() => {
    void window.vc.ffmpegEncode
      .probe()
      .then(setProbe)
      .catch(() => setProbe({ ffmpeg: false, nvenc: false }));
  }, []);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [p, cfg] = await Promise.all([
        // TS-routed render plan (newsDeskBackend.planRender); the old raw
        // creation.plan_render RPC was deleted with the plugin Python in A6.
        rpc.planRender(type, instance) as unknown as Promise<NewsDeskRenderPlan>,
        rpc.loadConfig(type, instance),
      ]);
      setPlan(p);
      const r = cfg["rendered"];
      setRendered(Array.isArray(r) ? (r as RenderedEntry[]) : []);
      setSettings({
        ...exportSettingsFromConfig(cfg),
        resolution: normalizeResolution(cfg["export_resolution"]),
      });
    } catch (err) {
      setError(fmtErr(err));
    }
  }, [type, instance]);

  // Persist a settings change (engine/resolution/fps/bitrate) to config.json.
  const onSettingsChange = useCallback(
    (patch: Partial<ExportSettings>) => {
      setSettings((prev) => ({ ...prev, ...patch }));
      const wire: Record<string, unknown> = {};
      if (patch.engine !== undefined) wire["export_engine"] = patch.engine;
      if (patch.resolution !== undefined) wire["export_resolution"] = patch.resolution;
      if (patch.fps !== undefined) wire["export_fps"] = patch.fps;
      if (patch.bitrateMode !== undefined) wire["export_bitrate_mode"] = patch.bitrateMode;
      if (patch.bitrateMbps !== undefined) wire["export_bitrate_mbps"] = patch.bitrateMbps;
      void rpc.updateConfig(type, instance, wire).catch((e) => setError(fmtErr(e)));
    },
    [type, instance],
  );

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
      setError(tr("news_desk.export.source_not_ready"));
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
      const p = (await rpc.planRender(type, instance)) as unknown as NewsDeskRenderPlan;
      setPlan(p);
      if (!p.mediaRef) throw new Error(tr("news_desk.export.no_material_error"));

      const canvas = hiddenCanvasRef.current;
      if (!canvas) throw new Error("no render canvas");
      const ms = await MediaSource.open(window.vc.mediaUrl(data.srcPath));
      reader = new ClipReader(ms);
      backend = new Backend();
      await backend.init(canvas);

      // Output dims + reframe rect by framing mode (default passthrough = today):
      //   passthrough — source dims, optionally downscaled by the resolution
      //                 preset (preserving aspect, never upscaling); whole frame.
      //   reframe     — target aspect @ short-edge; crop the persisted (or
      //                 centered) box and scale it to fill.
      //   letterbox   — target aspect @ short-edge; whole source contained (bars).
      const cfg = settingsRef.current;
      const framing = data.framing;
      const srcW0 = even(ms.width || 1280);
      const srcH0 = even(ms.height || 720);
      let outW: number;
      let outH: number;
      let cropRect: CropRect | undefined;
      if (framing.mode === "passthrough") {
        ({ width: outW, height: outH } = downscaleToShortEdge(srcW0, srcH0, cfg.resolution));
      } else {
        const a = parseAspect(framing.aspect);
        ({ width: outW, height: outH } = targetDimsForAspect(framing.aspect, framing.shortEdge));
        if (framing.mode === "reframe") {
          cropRect = framing.cropRect ?? centerCropRect(srcW0, srcH0, a.aw, a.ah);
        }
      }
      const durationSec = ms.durationUs / 1_000_000 || data.durationSec;
      backend.resize(outW, outH);
      const overlayCanvas = new OffscreenCanvas(outW, outH);
      const overlayCtx = overlayCanvas.getContext("2d");
      if (!overlayCtx) throw new Error("failed to get 2d context");
      const drawDeps = {
        backend,
        sources: new Map([[SOURCE_REF, reader]]),
        fit: "contain" as const,
        overlayCanvas,
        overlayCtx,
      };

      const engine = effectiveEngine(cfg.engine, probeRef.current);

      // The enabled dubbing track (if any) — drives both the WebCodecs audio map
      // and the ffmpeg audio source below.
      const dubComp = ((components ?? []) as unknown as NewsDeskComponentConfig[]).find(
        (c): c is Extract<NewsDeskComponentConfig, { kind: "dubbing" }> =>
          c.kind === "dubbing" && c.enabled === true,
      );
      const dubRef = dubComp && data.dubbingAudioPath ? data.dubbingAudioPath : undefined;

      // WebCodecs mixes audio in the renderer; ffmpeg pulls it from a single
      // source file (handled below). For WebCodecs, decode the source audio plus
      // the dub track so replace/mix resolve from the timeline.
      let audioSources: Map<string, DecodedAudio> | undefined;
      if (engine === "chromium") {
        audioSources = new Map();
        const srcAudio = await new AudioReader(window.vc.mediaUrl(data.srcPath)).decodeAll();
        if (srcAudio) audioSources.set(SOURCE_REF, srcAudio);
        if (dubRef) {
          try {
            const dubAudio = await new AudioReader(window.vc.mediaUrl(dubRef)).decodeAll();
            if (dubAudio) audioSources.set(dubRef, dubAudio);
          } catch (e) {
            console.warn("[news_desk export] dub audio decode failed:", e);
          }
        }
        if (audioSources.size === 0) audioSources = undefined;
      }

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
        frameAspect: outW / outH,
        ...(cropRect ? { cropRect } : {}),
        ...(dubRef ? { dubbingAudioRef: dubRef } : {}),
      });

      const base = {
        timeline: tl,
        drawDeps,
        backend,
        width: outW,
        height: outH,
        fps: cfg.fps,
        bitrate: resolveBitrate(cfg.bitrateMode, cfg.bitrateMbps, outW, outH, cfg.fps),
        durationSec: tl.durationSec,
        onProgress: (d: number, t: number) => {
          setFramesDone(d);
          setFramesTotal(t);
          setProgress(d / t);
        },
        cancelCheck: () => cancelRef.current,
      };

      if (engine === "ffmpeg") {
        // ffmpeg writes the mp4 directly and muxes audio from a single source
        // file. With a dub, mux the dub (full-length, aligned) instead of the
        // original — that realizes "replace". The ffmpeg engine can't mix two
        // tracks, so "mix" degrades to the dub-only result here (use WebCodecs to
        // hear the dub UNDER the original).
        if (dubRef && dubComp?.mode === "mix") {
          console.warn(
            "[news_desk export] ffmpeg engine can't mix the dub under the original; muxing the dub track only. Use the WebCodecs engine for mixing.",
          );
        }
        await exportTimelineViaFfmpeg(base, {
          outputPath: p.outputPath,
          sourcePath: dubRef ?? data.srcPath,
        });
      } else {
        // WebCodecs → stream the muxed mp4 to disk (too large to buffer/IPC whole).
        const streamId = await window.vc.openWriteStream(p.outputPath);
        let writeChain: Promise<void> = Promise.resolve();
        const onData = (chunkData: Uint8Array, position: number) => {
          const chunk = chunkData.slice(); // muxer owns the buffer; IPC is async
          writeChain = writeChain.then(() => window.vc.writeStreamChunk(streamId, position, chunk));
        };
        try {
          await exportTimelineToMp4({
            ...base,
            output: { onData, drain: () => writeChain },
            ...(audioSources ? { audioSources } : {}),
          });
          await writeChain;
          await window.vc.closeWriteStream(streamId);
        } catch (e) {
          await writeChain.catch(() => {});
          await window.vc.abortWriteStream(streamId);
          throw e;
        }
      }
      // src_idx unused for news_desk; out_idx pinned to 1.
      const list = await rpc.commitRender(type, instance, 0, p.outIdx, tl.durationSec);
      setRendered(list as RenderedEntry[]);
      setRenderStatus("done");
      setProgress(1);

      // Optional publish-side per-chapter split (off by default). Best-effort:
      // a failure here never fails the (already committed) main export.
      setSplitNote("");
      if (splitByChapterRef.current) {
        const chapterComp = (components ?? []).find((c) => c.kind === "chapter");
        const segments = chapterComp ? chapterSegments(chapterComp["schedule"]) : [];
        if (segments.length > 0) {
          try {
            const res = await window.vc.splitChapters({
              inputPath: p.outputPath,
              outDir: `${p.instanceDir}/chapters`,
              segments,
            });
            setSplitNote(
              res.failed.length
                ? tr("news_desk.export.split_partial", { ok: res.written.length, fail: res.failed.length })
                : tr("news_desk.export.split_done", { n: res.written.length }),
            );
          } catch (e) {
            setSplitNote(tr("news_desk.export.split_failed", { err: fmtErr(e) }));
          }
        }
      }
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
    if (!(await confirmDialog(tr("news_desk.export.delete_confirm")))) return;
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
  const chapterComp = (components ?? []).find((c) => c.kind === "chapter");
  const canSplit = chapterComp ? chapterSegments(chapterComp["schedule"]).length > 0 : false;

  return (
    <div style={{ padding: 16 }}>
      <canvas ref={hiddenCanvasRef} style={{ display: "none" }} />

      <ExportSettingsBar
        settings={settings}
        probe={probe}
        resolutionOptions={FULL_RESOLUTIONS}
        disabled={rendering}
        onChange={onSettingsChange}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <button onClick={() => void runRender()} disabled={!canRender} style={primaryBtn}>
          {rendering ? tr("news_desk.export.rendering_progress", { pct: (progress * 100).toFixed(1) }) : tr("news_desk.export.render_btn")}
        </button>
        {rendering && (
          <>
            <span style={{ fontSize: 12, color: "#aaa", fontVariantNumeric: "tabular-nums" }}>
              {framesDone} / {framesTotal}
            </span>
            <button onClick={() => (cancelRef.current = true)} style={btn}>
              {tr("common.cancel")}
            </button>
          </>
        )}
        <button onClick={() => void refresh()} disabled={rendering} style={btn}>
          {tr("news_desk.export.refresh_btn")}
        </button>
        <label
          title={canSplit ? undefined : tr("news_desk.export.split_chapters_hint")}
          style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: canSplit ? "#bbb" : "#666" }}
        >
          <input
            type="checkbox"
            checked={splitByChapter}
            disabled={!canSplit || rendering}
            onChange={(e) => setSplitByChapter(e.target.checked)}
          />
          {tr("news_desk.export.split_chapters")}
        </label>
        {renderStatus === "done" && !rendering && (
          <span style={{ color: "#3ecf8e", fontSize: 12 }}>✓ {tr("news_desk.export.done")}</span>
        )}
        {splitNote && <span style={{ color: "#aaa", fontSize: 12 }}>{splitNote}</span>}
        {error && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {error}</span>}
      </div>

      {previewStatus === "nobind" && (
        <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.export.nobind")}</p>
      )}
      {previewStatus === "nosrc" && (
        <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.export.nosrc")}</p>
      )}
      {previewStatus === "error" && (
        <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {previewMsg}</p>
      )}

      {plan && plan.mediaRef && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
            {tr("news_desk.export.plan_heading")}
          </div>
          <div style={row}>
            <span style={keyStyle}>{tr("news_desk.export.plan_duration")}</span>
            <span style={valStyle}>{fmtDuration(plan.durationSec)}</span>
          </div>
          <div style={row}>
            <span style={keyStyle}>{tr("news_desk.export.plan_output_file")}</span>
            <span style={valStyle}>{plan.outputPath}</span>
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
        {tr("news_desk.export.rendered_heading")}
      </div>
      {rendered.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.export.not_yet_rendered")}</p>
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
                <button onClick={() => onPlay(r.file)} style={rowBtn} title={tr("news_desk.export.play")}>▶</button>
                <button onClick={() => onOpenFolder(r.file)} style={rowBtn} title={tr("news_desk.export.open_folder")}>📁</button>
                <button onClick={() => void onDelete()} disabled={rendering} style={rowBtn} title={tr("common.delete")}>🗑</button>
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
