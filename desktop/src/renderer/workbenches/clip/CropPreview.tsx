/**
 * CropPreview — the faithful reframe CROP EDITOR, not a cropped result.
 *
 * Mirrors the Tk clip preview (src/ui/composition_preview.html): the canvas
 * shows the WHOLE source (never pre-cropped); a draggable output-aspect crop
 * box marks the region the export will keep, everything outside is dimmed, and
 * the overlays (subtitle / watermark / hook / outro) are drawn INSIDE the box.
 * The bright box = the program (export crops the box → target dims), so this
 * stays preview≡render. The box is the editing affordance, not a second render
 * path.
 *
 * Generic across both tabs (foundation doc §3): a pure renderer driven by
 * props. The host (Style tab / Clips-tab detail) owns the data, the candidate
 * window, and where the crop persists:
 *   - Style tab  : fullSource=true → whole source + a staging crop; the host's
 *                  "apply crop to all" bakes the rect into every override.
 *   - Clips detail: fullSource=false → one candidate's window + that
 *                   candidate's own crop, persisted per-candidate.
 *
 * Crop is controlled: the host owns `cropRect` and persists `onCropChange`
 * (fired on drag release). The engine opens the source once per `srcPath` and
 * survives candidate/override/crop changes (only the timeline rebuilds), so
 * switching candidates doesn't re-initialise WebGPU.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { tr } from "../../i18n/tr";
import { resolveFrameAt } from "@composition/compositor/resolve.js";
import { resolveAudioSegments } from "@composition/compositor/resolveAudio.js";
import type { Timeline, Clip } from "@composition/ir.js";
import { isMediaKind } from "@composition/catalog.js";
import { buildClipTimeline } from "@creations/clip/assemble.js";
import type {
  ClipComponentConfig,
  ClipOverride,
  HotclipCandidate,
} from "@creations/clip/types.js";
import type { SourceCue } from "@composition/components/index.js";
import { Backend } from "../../engine/gpu/Backend";
import { MediaSource } from "../../engine/source/MediaSource";
import { ClipReader } from "../../engine/source/ClipReader";
import { AudioReader } from "../../engine/source/AudioReader";
import { AudioPlayback } from "../../engine/playback/AudioPlayback";
import type { DecodedAudio } from "../../engine/source/sample-types";
import { isCanvas2dOverlay, drawOverlayClip, preloadImageOverlay } from "../../engine/overlay/canvas2d";
import type { Component } from "../../ipc/client";
import { centerCropRect, clampCropRect, type CropRect } from "./cropEditor";

const SOURCE_REF = "source";
const FPS = 30;
// Cap the working canvas resolution; the source aspect is preserved.
const MAX_CANVAS = 1280;

// Cards need candidate text — dropped when the host says not to show them.
const CARD_KINDS = new Set(["clip_hook_card", "clip_outro_card"]);

type EngineStatus = "loading" | "ready" | "error";

interface Engine {
  backend: Backend;
  reader: ClipReader;
  /** Reused 2D scratch for the composited editor layer (sized to the canvas). */
  overlayCanvas: OffscreenCanvas;
  overlayCtx: OffscreenCanvasRenderingContext2D;
  canvasW: number;
  canvasH: number;
  srcW: number;
  srcH: number;
  durationSec: number;
  /** Decoded source audio (keyed by mediaRef), or null when the source is silent. */
  audio: ReadonlyMap<string, DecodedAudio> | null;
}

export interface CropPreviewProps {
  /** Absolute source-video path (host-resolved via material.get_artifact). */
  srcPath: string;
  /** Candidate to render. fullSource ignores its window, using only its text. */
  candidate: HotclipCandidate;
  override?: ClipOverride;
  /** Ordered component config (list order = z-order). */
  components: Component[];
  /** Host-parsed SRT cues per language, in source time. */
  srtByLang: Record<string, readonly SourceCue[]>;
  mode: "reframe" | "passthrough";
  aspect: { aw: number; ah: number };
  /** Style tab: render [0, full duration] regardless of the candidate window. */
  fullSource: boolean;
  /** Include hook/outro cards (needs candidate text). */
  showCards: boolean;
  /** Controlled crop window; null → centered default (host computes via onReady). */
  cropRect: CropRect | null;
  /** Fired on drag release with the new crop window (host persists/stages it). */
  onCropChange: (rect: CropRect) => void;
  /** Reports source geometry once the engine opens (host computes the center). */
  onReady?: (info: { durationSec: number; srcW: number; srcH: number }) => void;
}

function secToTimestamp(sec: number): string {
  const s = Math.max(0, sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = (s % 60).toFixed(3);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${rest.padStart(6, "0")}`;
}

/**
 * Paint the composited editor layer: dim the frame, clear+outline the crop box,
 * then the overlays drawn inside the box (box dims act as the frame for overlay
 * layout — the same drawOverlayClip the export uses, so the box matches render).
 * In passthrough the box is the whole frame and dim/outline are skipped.
 */
function paintEditorLayer(
  ctx: OffscreenCanvasRenderingContext2D,
  canvasW: number,
  canvasH: number,
  rect: CropRect,
  mode: "reframe" | "passthrough",
  overlayClips: Clip[],
): void {
  ctx.clearRect(0, 0, canvasW, canvasH);

  const box =
    mode === "passthrough"
      ? { ox: 0, oy: 0, bw: canvasW, bh: canvasH }
      : {
          ox: rect.x * canvasW,
          oy: rect.y * canvasH,
          bw: rect.w * canvasW,
          bh: rect.h * canvasH,
        };

  if (mode === "reframe") {
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(0, 0, canvasW, canvasH);
    ctx.clearRect(box.ox, box.oy, box.bw, box.bh);
    ctx.strokeStyle = "#00ff88";
    ctx.lineWidth = Math.max(2, canvasW / 480);
    ctx.strokeRect(box.ox, box.oy, box.bw, box.bh);
  }

  for (const clip of overlayClips) {
    ctx.save();
    ctx.translate(box.ox, box.oy);
    ctx.beginPath();
    ctx.rect(0, 0, box.bw, box.bh);
    ctx.clip();
    drawOverlayClip(ctx, clip, box.bw, box.bh);
    ctx.restore();
  }
}

export function CropPreview(props: CropPreviewProps) {
  const {
    srcPath,
    candidate,
    override,
    components,
    srtByLang,
    mode,
    aspect,
    fullSource,
    showCards,
    cropRect,
    onCropChange,
    onReady,
  } = props;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const timelineRef = useRef<Timeline | null>(null);
  const rectRef = useRef<CropRect>({ x: 0, y: 0, w: 1, h: 1 });
  const inFlight = useRef(false);
  const pending = useRef<number | null>(null);
  const tRef = useRef(0);
  const drag = useRef<{ offX: number; offY: number } | null>(null);
  // Audio playback (master clock when the source has audio) + the rAF loop.
  const audioRef = useRef<AudioPlayback | null>(null);
  const rafRef = useRef<number | null>(null);
  const playingRef = useRef(false);

  const [status, setStatus] = useState<EngineStatus>("loading");
  const [message, setMessage] = useState("");
  const [duration, setDuration] = useState(0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  // Whether the source's audio decoded (drives the ♪ / 🔇 transport indicator;
  // also a quick visual bisect of "no sound" = decode-null vs clock-suspended).
  const [audioOn, setAudioOn] = useState(false);

  // Keep latest callbacks in refs so the open-effect only depends on srcPath.
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  // Render the frame at `sec`: GPU draws the full source, the editor layer draws
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
                frame = eng.reader.frameAtExact
                  ? await eng.reader.frameAtExact(us)
                  : await eng.reader.frameAt(us);
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

  // ── transport: play/pause with the audio as master clock ───────────────────
  // The video frame chases the clock (audio is sample-accurate and must not
  // stutter; a dropped video frame is fine — standard NLE arrangement). With no
  // audio track we fall back to a wall-clock so playback still works silently.
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
    const eng = engineRef.current;
    const tl = timelineRef.current;
    if (!eng || !tl || playingRef.current) return;
    const dur = tl.durationSec;
    // Restart from the head when sitting at (or past) the end.
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
        // Reached the end: settle on the last frame and stop.
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

  // Open the source once per srcPath. Engine survives candidate/crop changes.
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
        // React StrictMode double-mounts in dev. The cancelled mount must bail
        // BEFORE creating a Backend — otherwise two backends race to configure
        // and tear down the canvas's single WebGPU context, leaving the live
        // one rendering to a dead context (a black canvas). Only the live mount
        // may touch the GPU canvas.
        if (disposed) {
          reader.dispose();
          return;
        }
        const durationSec = ms.durationUs / 1_000_000;
        const srcW = ms.width || 1280;
        const srcH = ms.height || 720;
        const scale = Math.min(1, MAX_CANVAS / Math.max(srcW, srcH));
        const canvasW = Math.max(2, Math.round(srcW * scale));
        const canvasH = Math.max(2, Math.round(srcH * scale));

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

        // Decode the source audio once (for preview playback). Silent/failed
        // decode → null, and the transport falls back to a wall-clock scrubber.
        // decodeAll() self-detects audio via the browser decoder and returns
        // null for a silent source — do NOT gate on ms.audio (the mp4box audio
        // probe is the fragile path we're routing around).
        let audio: Map<string, DecodedAudio> | null = null;
        const decoded = await new AudioReader(window.vc.mediaUrl(srcPath)).decodeAll();
        if (decoded) audio = new Map([[SOURCE_REF, decoded]]);
        if (!disposed) setAudioOn(decoded != null);
        if (disposed) {
          reader.dispose();
          backend.dispose();
          return;
        }

        engineRef.current = { backend, reader, overlayCanvas, overlayCtx, canvasW, canvasH, srcW, srcH, durationSec, audio };
        setStatus("ready");
        onReadyRef.current?.({ durationSec, srcW, srcH });
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

  // Sync the live crop rect from the controlled prop (default = centered).
  useEffect(() => {
    const eng = engineRef.current;
    if (status !== "ready" || !eng) return;
    if (mode === "passthrough") {
      rectRef.current = { x: 0, y: 0, w: 1, h: 1 };
    } else {
      rectRef.current = cropRect ?? centerCropRect(eng.srcW, eng.srcH, aspect.aw, aspect.ah);
    }
    void renderAt(tRef.current);
  }, [cropRect, status, mode, aspect.aw, aspect.ah, renderAt]);

  // Rebuild the timeline whenever the source, candidate, override, or live-edited
  // components change. Cards/text come from the candidate; the window from
  // fullSource ([0,duration]) or the candidate/override timestamps.
  useEffect(() => {
    const eng = engineRef.current;
    if (status !== "ready" || !eng) return;
    let cancelled = false;
    void (async () => {
      for (const c of components) {
        if (c.kind === "clip_image_watermark") {
          const p = c["image_path"];
          if (typeof p === "string" && p) {
            try {
              await preloadImageOverlay(p, window.vc.mediaUrl(p));
              // DIAGNOSTIC: load succeeded → if still invisible, the bug is in draw.
              console.log("[image-watermark] preload OK", { path: p });
            } catch (e) {
              // DIAGNOSTIC: surface why the watermark image won't load.
              console.error("[image-watermark] preload failed", { path: p, url: window.vc.mediaUrl(p), error: e });
            }
          }
        }
      }
      if (cancelled) return;

      const effectiveCandidate: HotclipCandidate = fullSource
        ? { ...candidate, start: "00:00:00.000", end: secToTimestamp(eng.durationSec) }
        : candidate;
      const previewComps = showCards ? components : components.filter((c) => !CARD_KINDS.has(c.kind));
      // Subtitle fitting uses the OUTPUT aspect so preview ≡ render: reframe →
      // the crop's output aspect; passthrough → the source aspect.
      const frameAspect =
        mode === "passthrough" ? eng.srcW / eng.srcH : aspect.aw / aspect.ah;
      try {
        const tl = buildClipTimeline({
          components: previewComps as unknown as ClipComponentConfig[],
          candidate: effectiveCandidate,
          srtByLang,
          mediaRef: SOURCE_REF,
          frameAspect,
          ...(fullSource ? {} : override ? { override } : {}),
        });
        timelineRef.current = tl;
        setDuration(tl.durationSec);
      } catch (err) {
        setMessage(err instanceof Error ? `compose: ${err.message}` : String(err));
        return;
      }

      // (Re)build audio playback for this timeline's audio segments. Isolated
      // from the compose try/catch: an audio failure (e.g. AudioContext limit)
      // must never blank the video preview. Playing is interrupted by the
      // rebuild, so pause first to avoid the clock running on a stale schedule.
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
          console.warn("[CropPreview] audio build failed:", e);
        }
      }
      void renderAt(tRef.current);
    })();
    return () => {
      cancelled = true;
    };
  }, [status, candidate, override, components, srtByLang, fullSource, showCards, renderAt]);

  // ── crop box drag (move-only; box is the max-fit output-aspect window) ──────
  const pointInBox = (nx: number, ny: number): boolean => {
    const r = rectRef.current;
    return nx >= r.x && nx <= r.x + r.w && ny >= r.y && ny <= r.y + r.h;
  };

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (mode !== "reframe") return;
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    const nx = (e.clientX - r.left) / r.width;
    const ny = (e.clientY - r.top) / r.height;
    if (!pointInBox(nx, ny)) return;
    drag.current = { offX: nx - rectRef.current.x, offY: ny - rectRef.current.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  }, [mode]);

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
      // Commit the final rect to the host (persist / stage). Mirrors the Tk
      // preview's on_crop_changed → host write.
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
          // Constrain by BOTH max-dimensions with auto sizing so the canvas
          // always scales to its intrinsic (source) aspect. A fixed height +
          // maxWidth distorts the frame (and the crop box) whenever the
          // container is narrower than height×aspect — which happens in the
          // Candidates detail pane (flex:1) but not the shrink-to-content
          // Style pane.
          maxWidth: "100%",
          maxHeight: 340,
          background: "#000",
          borderRadius: 6,
          display: status === "error" ? "none" : "block",
          cursor: isReframe ? "grab" : "default",
          touchAction: "none",
        }}
      />
      {status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>{tr("clip.preview.loading_source")}</p>}
      {status === "error" && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {message}</p>}

      {status === "ready" && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, maxWidth: 480, marginTop: 6 }}>
          <button
            onClick={togglePlay}
            title={playing ? tr("clip.preview.pause") : tr("clip.preview.play")}
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
            // Grabbing the bar pauses playback so the rAF loop's per-frame setT
            // stops fighting the drag (otherwise the thumb snaps back each frame).
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
            title={audioOn ? tr("clip.preview.audio_loaded") : tr("clip.preview.audio_none")}
            style={{ fontSize: 13, color: audioOn ? "#7fd17f" : "#888" }}
          >
            {audioOn ? "♪" : "🔇"}
          </span>
        </div>
      )}
    </div>
  );
}
