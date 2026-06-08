/**
 * NewsDeskPreview — full-source composition preview + reframe crop EDITOR for the
 * news_desk workbench.
 *
 * Sibling of clip's CropPreview: same engine orchestration (Backend +
 * MediaSource/ClipReader + AudioReader/AudioPlayback + canvas2D overlays +
 * resolveFrameAt) and the same draggable output-aspect crop box (shared
 * cropEditorLayer). The only structural difference is the timeline source:
 * buildNewsDeskTimeline composes the WHOLE source (no candidate cut), with a
 * single instance-level crop. The box is the editing affordance — the export
 * crops it via Clip.crop, so preview ≡ render. passthrough/letterbox show the
 * whole frame (no box); only reframe shows the draggable box.
 *
 * The source opens once per srcPath; the timeline rebuilds when the live-edited
 * components OR the framing (mode/aspect/crop) change (no GPU re-init).
 */

import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { resolveFrameAt } from "@composition/compositor/resolve.js";
import { resolveAudioSegments } from "@composition/compositor/resolveAudio.js";
import type { Timeline, Clip } from "@composition/ir.js";
import { isMediaKind } from "@composition/catalog.js";
import { centerCropRect, clampCropRect, type ClipMode, type CropRect } from "@composition/crop.js";
import { buildNewsDeskTimeline } from "@creations/news_desk/assemble.js";
import type { NewsDeskComponentConfig } from "@creations/news_desk/types.js";
import type { SourceCue } from "@composition/components/index.js";
import { Backend } from "../../engine/gpu/Backend";
import { MediaSource } from "../../engine/source/MediaSource";
import { ClipReader } from "../../engine/source/ClipReader";
import { AudioReader } from "../../engine/source/AudioReader";
import { AudioPlayback } from "../../engine/playback/AudioPlayback";
import type { DecodedAudio } from "../../engine/source/sample-types";
import { isCanvas2dOverlay, preloadImageOverlay } from "../../engine/overlay/canvas2d";
import { canvasDimsFor, paintEditorLayer } from "../shared/cropEditorLayer";
import type { Component } from "../../ipc/client";
import { tr } from "../../i18n/tr";

const SOURCE_REF = "source";
const FPS = 30;

type EngineStatus = "loading" | "ready" | "error";

interface Engine {
  backend: Backend;
  reader: ClipReader;
  overlayCanvas: OffscreenCanvas;
  overlayCtx: OffscreenCanvasRenderingContext2D;
  canvasW: number;
  canvasH: number;
  srcW: number;
  srcH: number;
  durationSec: number;
  audio: ReadonlyMap<string, DecodedAudio> | null;
}

export interface NewsDeskPreviewProps {
  /** Absolute source-video path (host-resolved via material.get_artifact). */
  srcPath: string;
  /** Full source duration (seconds), from preview_data. */
  durationSec: number;
  /** Ordered component config (list order = z-order). */
  components: Component[];
  /** Snapshot SRT cues keyed by each subtitle's srt_path. */
  cuesBySrtPath: Record<string, readonly SourceCue[]>;
  /** Output framing mode (default passthrough = whole source). */
  mode: ClipMode;
  /** Output aspect; only used in reframe/letterbox. */
  aspect: { aw: number; ah: number };
  /** Controlled crop window (reframe); null → centered default. */
  cropRect: CropRect | null;
  /** Fired on drag release with the new crop window (host persists it). */
  onCropChange: (rect: CropRect) => void;
  /** Optional handle the parent fills to drive the playhead (detail-list seek). */
  controlRef?: React.Ref<NewsDeskPreviewHandle>;
}

/** Imperative handle so the detail lists can drive the preview's playhead. */
export interface NewsDeskPreviewHandle {
  /** Pause and jump the playhead to `sec` (clamped to the timeline). */
  seek(sec: number): void;
}

export function NewsDeskPreview(props: NewsDeskPreviewProps) {
  const { srcPath, durationSec: srcDuration, components, cuesBySrtPath, mode, aspect, cropRect, onCropChange, controlRef } =
    props;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const timelineRef = useRef<Timeline | null>(null);
  const rectRef = useRef<CropRect>({ x: 0, y: 0, w: 1, h: 1 });
  const inFlight = useRef(false);
  const pending = useRef<number | null>(null);
  const tRef = useRef(0);
  const drag = useRef<{ offX: number; offY: number } | null>(null);
  const audioRef = useRef<AudioPlayback | null>(null);
  const rafRef = useRef<number | null>(null);
  const playingRef = useRef(false);

  const [status, setStatus] = useState<EngineStatus>("loading");
  const [message, setMessage] = useState("");
  const [duration, setDuration] = useState(0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [audioOn, setAudioOn] = useState(false);

  // Render the frame at `sec`: GPU draws the source, the editor layer draws the
  // dim + crop box + overlays-in-box on top. latest-wins so scrub/drag stay live.
  const renderAt = useCallback(async (sec: number) => {
    const eng = engineRef.current;
    if (!eng || !timelineRef.current) return;
    if (inFlight.current) {
      pending.current = sec;
      return;
    }
    inFlight.current = true;
    try {
      let target: number | null = sec;
      while (target !== null) {
        pending.current = null;
        const tl = timelineRef.current;
        if (!tl) break;
        const lastT = Math.max(0, tl.durationSec - 1 / FPS);
        const slice = resolveFrameAt(tl, Math.min(Math.max(0, target), lastT));

        let frame: VideoFrame | null = null;
        const overlayClips: Clip[] = [];
        for (const track of slice.tracks) {
          for (const ac of track.clips) {
            const c = ac.clip;
            if (isMediaKind(c.kind)) {
              if (!frame && ac.sourceTimeSec != null) {
                const us = ac.sourceTimeSec * 1_000_000;
                // Preview is real-time playback/scrub → the NON-blocking reader.
                // frameAtExact is EXPORT-only: it blocks up to 3 s waiting for the
                // exact frame, which at 60 fps stalls the rAF loop to ~1 frame/10 s.
                frame = await eng.reader.frameAt(us);
              }
            } else if (isCanvas2dOverlay(c.kind)) {
              overlayClips.push(c);
            }
          }
        }

        paintEditorLayer(eng.overlayCtx, eng.canvasW, eng.canvasH, rectRef.current, mode, overlayClips);

        const rp = eng.backend.beginPass();
        if (rp) {
          if (frame) eng.backend.drawVideoFrame(rp, frame, "contain");
          const tex = eng.backend.createOverlayTexture();
          if (tex) {
            eng.backend.uploadOverlay(tex, eng.overlayCanvas);
            eng.backend.drawOverlayTexture(rp, tex);
            eng.backend.endPass(rp);
            tex.destroy();
          } else {
            eng.backend.endPass(rp);
          }
        }
        frame?.close();
        target = pending.current;
      }
    } finally {
      inFlight.current = false;
    }
  }, [mode]);

  // ── transport: play/pause with audio as master clock (wall-clock fallback) ──
  const stopLoop = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const pausePlayback = useCallback(() => {
    if (!playingRef.current) return;
    playingRef.current = false;
    setPlaying(false);
    audioRef.current?.pause();
    stopLoop();
  }, [stopLoop]);

  const startPlayback = useCallback(() => {
    const tl = timelineRef.current;
    if (!engineRef.current || !tl || playingRef.current) return;
    const dur = tl.durationSec;
    let from = tRef.current;
    if (from >= dur - 1 / FPS) from = 0;

    const audio = audioRef.current;
    const wallStart = performance.now();
    const wallFrom = from;
    if (audio?.hasAudio) void audio.play(from);

    playingRef.current = true;
    setPlaying(true);

    const tick = () => {
      if (!playingRef.current) return;
      const pos = audio?.hasAudio
        ? audio.currentTime
        : wallFrom + (performance.now() - wallStart) / 1000;
      if (pos >= dur - 1 / FPS) {
        tRef.current = dur;
        setT(dur);
        void renderAt(dur);
        pausePlayback();
        return;
      }
      tRef.current = pos;
      setT(pos);
      void renderAt(pos);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [renderAt, pausePlayback]);

  const togglePlay = useCallback(() => {
    if (playingRef.current) pausePlayback();
    else startPlayback();
  }, [pausePlayback, startPlayback]);

  // Expose seek to the detail lists (subtitle cue / chapter row → jump playhead).
  useImperativeHandle(
    controlRef,
    () => ({
      seek(sec: number) {
        const tl = timelineRef.current;
        if (!tl) return;
        pausePlayback();
        const clamped = Math.max(0, Math.min(tl.durationSec, sec));
        setT(clamped);
        tRef.current = clamped;
        audioRef.current?.seek(clamped);
        void renderAt(clamped);
      },
    }),
    [pausePlayback, renderAt],
  );

  // Open the source once per srcPath. Engine survives component/framing edits.
  useEffect(() => {
    let disposed = false;
    setStatus("loading");
    setMessage("");
    setDuration(0);
    setT(0);
    tRef.current = 0;
    timelineRef.current = null;

    void (async () => {
      try {
        const canvas = canvasRef.current;
        if (!canvas || disposed) return;
        const ms = await MediaSource.open(window.vc.mediaUrl(srcPath));
        const reader = new ClipReader(ms);
        // StrictMode double-mount: the cancelled mount must bail before creating
        // a Backend, or two backends race the canvas's single WebGPU context.
        if (disposed) {
          reader.dispose();
          return;
        }
        const durationSec = ms.durationUs / 1_000_000 || srcDuration;
        const srcW = ms.width || 1280;
        const srcH = ms.height || 720;
        // letterbox sizes the canvas to the OUTPUT aspect; a later mode/aspect
        // change re-sizes via the dedicated effect below.
        const { w: canvasW, h: canvasH } = canvasDimsFor(mode, srcW, srcH, aspect.aw, aspect.ah);

        const backend = new Backend();
        await backend.init(canvas);
        if (disposed) {
          reader.dispose();
          backend.dispose();
          return;
        }
        backend.resize(canvasW, canvasH);
        const overlayCanvas = new OffscreenCanvas(canvasW, canvasH);
        const overlayCtx = overlayCanvas.getContext("2d");
        if (!overlayCtx) throw new Error("failed to get 2d context");

        let audio: Map<string, DecodedAudio> | null = null;
        const decoded = await new AudioReader(window.vc.mediaUrl(srcPath)).decodeAll();
        if (decoded) audio = new Map([[SOURCE_REF, decoded]]);
        if (!disposed) setAudioOn(decoded != null);
        if (disposed) {
          reader.dispose();
          backend.dispose();
          return;
        }

        engineRef.current = {
          backend,
          reader,
          overlayCanvas,
          overlayCtx,
          canvasW,
          canvasH,
          srcW,
          srcH,
          durationSec,
          audio,
        };
        setStatus("ready");
      } catch (err) {
        if (!disposed) {
          setStatus("error");
          setMessage(err instanceof Error ? `${err.name}: ${err.message}` : String(err));
        }
      }
    })();

    return () => {
      disposed = true;
      stopLoop();
      audioRef.current?.dispose();
      audioRef.current = null;
      engineRef.current?.reader.dispose();
      engineRef.current?.backend.dispose();
      engineRef.current = null;
      timelineRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srcPath]);

  // Sync the live crop rect from the controlled prop (reframe = centered default;
  // letterbox/passthrough use the whole frame).
  useEffect(() => {
    const eng = engineRef.current;
    if (status !== "ready" || !eng) return;
    rectRef.current =
      mode === "reframe"
        ? (cropRect ?? centerCropRect(eng.srcW, eng.srcH, aspect.aw, aspect.ah))
        : { x: 0, y: 0, w: 1, h: 1 };
    void renderAt(tRef.current);
  }, [cropRect, status, mode, aspect.aw, aspect.ah, renderAt]);

  // letterbox previews the OUTPUT frame, so the canvas must resize when the mode
  // or aspect changes (reframe/passthrough keep the source aspect).
  useEffect(() => {
    const eng = engineRef.current;
    if (status !== "ready" || !eng) return;
    const { w, h } = canvasDimsFor(mode, eng.srcW, eng.srcH, aspect.aw, aspect.ah);
    if (w === eng.canvasW && h === eng.canvasH) return;
    eng.backend.resize(w, h);
    eng.overlayCanvas.width = w;
    eng.overlayCanvas.height = h;
    eng.canvasW = w;
    eng.canvasH = h;
    void renderAt(tRef.current);
  }, [mode, aspect.aw, aspect.ah, status, renderAt]);

  // Rebuild the timeline whenever the live-edited components OR the framing
  // change. Preload image-watermark assets first so they render on frame one.
  useEffect(() => {
    const eng = engineRef.current;
    if (status !== "ready" || !eng) return;
    let cancelled = false;
    void (async () => {
      for (const c of components) {
        if (c.kind === "image_watermark") {
          const p = c["image_path"];
          if (typeof p === "string" && p) {
            try {
              await preloadImageOverlay(p, window.vc.mediaUrl(p));
            } catch {
              /* unloadable image → renders without it */
            }
          }
        }
      }
      if (cancelled) return;

      // Subtitle/overlay fitting uses the OUTPUT aspect so preview ≡ render:
      // reframe/letterbox → the chosen aspect; passthrough → the source aspect.
      // The preview video is drawn whole ("contain") with the crop box on top —
      // the box marks the export region — so the preview timeline carries no
      // crop (the export applies it via Clip.crop). Mirrors clip's CropPreview.
      const frameAspect = mode === "passthrough" ? eng.srcW / eng.srcH : aspect.aw / aspect.ah;
      const reframe = mode === "reframe";
      try {
        const tl = buildNewsDeskTimeline({
          components: components as unknown as NewsDeskComponentConfig[],
          durationSec: eng.durationSec,
          cuesBySrtPath,
          mediaRef: SOURCE_REF,
          frameAspect,
        });
        timelineRef.current = tl;
        setDuration(tl.durationSec);
      } catch (err) {
        setMessage(err instanceof Error ? `compose: ${err.message}` : String(err));
        return;
      }

      // (Re)build audio playback for this timeline. Isolated from compose: an
      // audio failure must never blank the video preview.
      pausePlayback();
      audioRef.current?.dispose();
      audioRef.current = null;
      if (eng.audio && timelineRef.current) {
        try {
          const pb = new AudioPlayback(timelineRef.current.durationSec);
          pb.build(resolveAudioSegments(timelineRef.current), eng.audio);
          if (pb.hasAudio) audioRef.current = pb;
          else pb.dispose();
        } catch (e) {
          console.warn("[NewsDeskPreview] audio build failed:", e);
        }
      }
      // Sync the crop box to the authoritative rect before this paint (the
      // standalone crop effect may have no-op'd while the timeline was null).
      rectRef.current = reframe
        ? (cropRect ?? centerCropRect(eng.srcW, eng.srcH, aspect.aw, aspect.ah))
        : { x: 0, y: 0, w: 1, h: 1 };
      void renderAt(tRef.current);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, components, cuesBySrtPath, mode, aspect.aw, aspect.ah, renderAt]);

  // ── crop box drag (move-only; box is the max-fit output-aspect window) ──────
  const pointInBox = (nx: number, ny: number): boolean => {
    const r = rectRef.current;
    return nx >= r.x && nx <= r.x + r.w && ny >= r.y && ny <= r.y + r.h;
  };

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (mode !== "reframe") return;
      const r = e.currentTarget.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      const nx = (e.clientX - r.left) / r.width;
      const ny = (e.clientY - r.top) / r.height;
      if (!pointInBox(nx, ny)) return;
      drag.current = { offX: nx - rectRef.current.x, offY: ny - rectRef.current.y };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [mode],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const d = drag.current;
      const eng = engineRef.current;
      if (!d || !eng) return;
      const r = e.currentTarget.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      const nx = (e.clientX - r.left) / r.width;
      const ny = (e.clientY - r.top) / r.height;
      const moved = { ...rectRef.current, x: nx - d.offX, y: ny - d.offY };
      rectRef.current = clampCropRect(moved, eng.canvasW, eng.canvasH, aspect.aw, aspect.ah);
      void renderAt(tRef.current);
    },
    [aspect.aw, aspect.ah, renderAt],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drag.current) return;
      drag.current = null;
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* capture may already be gone */
      }
      onCropChange(rectRef.current);
    },
    [onCropChange],
  );

  const isReframe = mode === "reframe";

  return (
    <div>
      <canvas
        ref={canvasRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        style={{
          maxWidth: "100%",
          maxHeight: 340,
          background: "#000",
          borderRadius: 6,
          display: status === "error" ? "none" : "block",
          cursor: isReframe ? "grab" : "default",
          touchAction: "none",
        }}
      />
      {status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.preview.loading_source")}</p>}
      {status === "error" && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {message}</p>}

      {status === "ready" && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, maxWidth: 480, marginTop: 6 }}>
          <button
            onClick={togglePlay}
            title={playing ? tr("news_desk.preview.pause") : tr("news_desk.preview.play")}
            style={{
              width: 30,
              height: 30,
              flex: "0 0 auto",
              border: "1px solid #444",
              borderRadius: 4,
              background: "#2a2a2a",
              color: "#ddd",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            {playing ? "⏸" : "▶"}
          </button>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={1 / FPS}
            value={t}
            onPointerDown={pausePlayback}
            onChange={(e) => {
              const v = Number(e.target.value);
              setT(v);
              tRef.current = v;
              audioRef.current?.seek(v);
              void renderAt(v);
            }}
            style={{ flex: 1 }}
          />
          <span style={{ fontVariantNumeric: "tabular-nums", color: "#bbb", fontSize: 12 }}>
            {t.toFixed(2)}s
          </span>
          <span
            title={audioOn ? tr("news_desk.preview.audio_loaded") : tr("news_desk.preview.audio_none")}
            style={{ fontSize: 13, color: audioOn ? "#7fd17f" : "#888" }}
          >
            {audioOn ? "♪" : "🔇"}
          </span>
        </div>
      )}
    </div>
  );
}
