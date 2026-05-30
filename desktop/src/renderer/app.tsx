import { useEffect, useRef, useState } from "react";
import { resolveFrameAt } from "@composition/compositor/resolve.js";
import type { Timeline } from "@composition/ir.js";
import { Backend } from "./engine/gpu/Backend";
import { MediaSource } from "./engine/source/MediaSource";
import { ClipReader } from "./engine/source/ClipReader";
import type { VideoSource } from "./engine/types";
import { drawFrameSlice, type DrawDeps } from "./engine/compositor/draw";
import { buildDemoTimeline, buildSubtitleTimeline, DEMO_MEDIA_REF } from "./harness/demoTimeline";
import { buildMultiSegmentTimeline } from "./harness/multiSegment";
import { exportTimelineToMp4 } from "./engine/export/encode";
import { rpc } from "./ipc/client";

const FPS = 30; // synthetic test clip is 30fps; used for the frame-number readout.
const CANVAS_W = 1280;
const CANVAS_H = 720;

type Mode = "demo" | "seek" | "subtitle";

interface Engine {
  backend: Backend;
  reader: ClipReader;
  info: string;
  timelines: Record<Mode, Timeline>;
  drawDeps: DrawDeps;
}

/** Expected source frame for the HUD: the video clip's resolved source time. */
function expectedSourceFrame(timeline: Timeline, t: number): number | null {
  const slice = resolveFrameAt(timeline, t);
  for (const track of slice.tracks) {
    if (track.kind !== "video") continue;
    const ac = track.clips[0];
    if (ac && ac.sourceTimeSec != null) return Math.round(ac.sourceTimeSec * FPS);
  }
  return null;
}

/**
 * Substrate spike harness. Two timelines exercise the GPU draw layer:
 *   - demo: video + hook/outro overlay cards (Phase 2)
 *   - seek: multi-segment, non-monotonic sourceStart (Spike A) — compare the
 *     burned-in frame number against the "expected src frame" HUD.
 */
export function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<Engine | null>(null);
  // Backend (WebGPU device) + overlay scratch persist across media loads.
  const backendRef = useRef<Backend | null>(null);
  const overlayRef = useRef<{ canvas: OffscreenCanvas; ctx: OffscreenCanvasRenderingContext2D } | null>(null);

  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [mode, setMode] = useState<Mode>("demo");
  const [durationSec, setDurationSec] = useState(0);
  const [timeSec, setTimeSec] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [expectedFrame, setExpectedFrame] = useState<number | null>(null);
  const [actualFrame, setActualFrame] = useState<number | null>(null);
  const [drawInfo, setDrawInfo] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportMsg, setExportMsg] = useState("");
  // Sidecar (Python RPC) smoke: proves the renderer→main→sidecar→core round
  // trip on launch. This is a spike-harness readout, not product UI.
  const [sidecarStatus, setSidecarStatus] = useState("connecting to sidecar…");

  const mode_ = useRef<Mode>("demo");
  const playing_ = useRef(false);
  const timeSec_ = useRef(0);
  const playBase = useRef(0);
  const playT0 = useRef(0);
  const inFlight = useRef(false);
  const seekSettleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // (Re)build reader + timelines for a media URL, reusing the persistent backend.
  async function loadMedia(mediaUrl: string): Promise<void> {
    const backend = backendRef.current;
    const overlay = overlayRef.current;
    if (!backend || !overlay) return;
    stopPlayback();
    setStatus("loading");
    try {
      const ms = await MediaSource.open(mediaUrl);
      const reader = new ClipReader(ms);
      engineRef.current?.reader.dispose();

      const fullDur = ms.durationUs / 1_000_000;
      const sources = new Map<string, VideoSource>([[DEMO_MEDIA_REF, reader]]);
      const infoStr = `${ms.codec} ${ms.width}×${ms.height} · ${fullDur.toFixed(2)}s · ${ms.samples.length} samples · ${ms.index.keyframeCount} keyframes`;
      engineRef.current = {
        backend,
        reader,
        info: infoStr,
        timelines: {
          demo: buildDemoTimeline(fullDur),
          seek: buildMultiSegmentTimeline(),
          subtitle: buildSubtitleTimeline(fullDur),
        },
        drawDeps: { backend, sources, fit: "contain", overlayCanvas: overlay.canvas, overlayCtx: overlay.ctx },
      };
      setInfo(infoStr);
      timeSec_.current = 0;
      setTimeSec(0);
      setDurationSec(engineRef.current.timelines[mode_.current].durationSec);
      setStatus("ready");
      await renderAt(0);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? `${err.name}: ${err.message}` : String(err));
    }
  }

  async function onOpenVideo(): Promise<void> {
    const path = await window.vc.pickVideo();
    if (path) await loadMedia(window.vc.mediaUrl(path));
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    void (async () => {
      try {
        const backend = new Backend();
        await backend.init(canvas);
        backend.resize(CANVAS_W, CANVAS_H);
        const overlayCanvas = new OffscreenCanvas(CANVAS_W, CANVAS_H);
        const overlayCtx = overlayCanvas.getContext("2d");
        if (!overlayCtx) throw new Error("failed to get 2d context for overlays");
        if (disposed) {
          backend.dispose();
          return;
        }
        backendRef.current = backend;
        overlayRef.current = { canvas: overlayCanvas, ctx: overlayCtx };
        await loadMedia(window.vc.spikeMediaUrl("test_clip.mp4"));
      } catch (err) {
        if (!disposed) {
          setStatus("error");
          setError(err instanceof Error ? `${err.name}: ${err.message}` : String(err));
        }
      }
    })();

    return () => {
      disposed = true;
      engineRef.current?.reader.dispose();
      backendRef.current?.dispose();
      engineRef.current = null;
      backendRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // One-shot sidecar handshake on mount: ping (protocol/handshake) + a real
  // core call (recent_list) → renderer→IPC→main→python→core all the way down.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const pong = await rpc.ping();
        const recents = await rpc.recentList();
        if (alive) {
          setSidecarStatus(
            `✓ sidecar protocol ${pong.protocol} · ${recents.length} recent project(s)`,
          );
        }
      } catch (err) {
        if (alive) {
          setSidecarStatus(`✗ sidecar: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  async function renderAt(sec: number, exact = false): Promise<void> {
    const eng = engineRef.current;
    if (!eng || inFlight.current) return;
    inFlight.current = true;
    try {
      const timeline = eng.timelines[mode_.current];
      // Clamp to just inside the timeline: at exactly durationSec the half-open
      // [start, end) clip windows cover nothing → a black frame. Show the last
      // frame instead (end-of-track / slider-at-max).
      const lastT = Math.max(0, timeline.durationSec - 1 / FPS);
      const t = Math.min(Math.max(0, sec), lastT);
      const slice = resolveFrameAt(timeline, t);
      const stats = await drawFrameSlice(slice, eng.drawDeps, exact);
      setDrawInfo(`v:${stats.video} ov:${stats.overlay} skip:${stats.skipped}`);
      setExpectedFrame(expectedSourceFrame(timeline, t));
      setActualFrame(
        stats.videoTimestampUs != null
          ? Math.round((stats.videoTimestampUs / 1_000_000) * FPS)
          : null,
      );
    } finally {
      inFlight.current = false;
    }
  }

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const eng = engineRef.current;
      if (!eng) return;
      if (playing_.current) {
        const dur = eng.timelines[mode_.current].durationSec;
        const elapsed = (performance.now() - playT0.current) / 1000;
        let t = playBase.current + elapsed;
        if (t >= dur) {
          t = dur;
          stopPlayback();
        }
        timeSec_.current = t;
        setTimeSec(t);
        void renderAt(timeSec_.current);
      }
      // When paused we do NOT render every frame — that 60fps re-render storm
      // fought the controlled slider during drag (jitter) and flashed frames as
      // a seek settled. Paused renders happen on seek (below) instead.
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startPlayback(): void {
    const eng = engineRef.current;
    if (!eng) return;
    const dur = eng.timelines[mode_.current].durationSec;
    if (timeSec_.current >= dur) timeSec_.current = 0;
    playBase.current = timeSec_.current;
    playT0.current = performance.now();
    playing_.current = true;
    setPlaying(true);
  }

  function stopPlayback(): void {
    playing_.current = false;
    setPlaying(false);
  }

  function onSeek(sec: number): void {
    stopPlayback();
    timeSec_.current = sec;
    setTimeSec(sec);
    // Fast best-available frame while dragging; then once, ~120ms after the
    // drag stops, a single exact-frame render settles the paused frame (no
    // per-frame re-render storm, so the slider doesn't jitter).
    void renderAt(sec);
    if (seekSettleTimer.current !== null) clearTimeout(seekSettleTimer.current);
    seekSettleTimer.current = setTimeout(() => {
      seekSettleTimer.current = null;
      void renderAt(timeSec_.current, /* exact */ true);
    }, 120);
  }

  async function onExport(): Promise<void> {
    const eng = engineRef.current;
    if (!eng || exporting) return;
    stopPlayback();
    setExporting(true);
    setExportMsg("starting…");
    try {
      const tl = eng.timelines[mode_.current];
      const bytes = await exportTimelineToMp4({
        timeline: tl,
        drawDeps: eng.drawDeps,
        backend: eng.backend,
        width: CANVAS_W,
        height: CANVAS_H,
        fps: FPS,
        durationSec: tl.durationSec,
        onProgress: (d, t) => setExportMsg(`encoding ${d}/${t}`),
      });
      const path = await window.vc.writeExport(`export_${mode_.current}.mp4`, bytes);
      setExportMsg(`✓ ${(bytes.length / 1_000_000).toFixed(2)} MB → ${path}`);
    } catch (err) {
      setExportMsg(`✗ ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setExporting(false);
    }
  }

  function switchMode(next: Mode): void {
    const eng = engineRef.current;
    stopPlayback();
    mode_.current = next;
    setMode(next);
    timeSec_.current = 0;
    setTimeSec(0);
    if (eng) setDurationSec(eng.timelines[next].durationSec);
    void renderAt(0);
  }

  const frameNo = Math.round(timeSec * FPS);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 16 }}>
      <h2 style={{ fontWeight: 600, margin: "0 0 4px" }}>VideoCraft — substrate spike harness</h2>
      <p
        style={{
          margin: "0 0 10px",
          fontSize: 13,
          color: sidecarStatus.startsWith("✗") ? "#ff6b6b" : "#7fd17f",
        }}
      >
        {sidecarStatus}
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        {(["demo", "seek", "subtitle"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => switchMode(m)}
            disabled={status !== "ready"}
            style={{
              padding: "4px 12px",
              fontWeight: mode === m ? 700 : 400,
              background: mode === m ? "#2d6cdf" : "#2a2a2e",
              color: "#fff",
              border: "none",
              borderRadius: 4,
            }}
          >
            {m === "demo"
              ? "Demo (video + overlays)"
              : m === "seek"
                ? "Seek (multi-segment)"
                : "Subtitle (canvas2D)"}
          </button>
        ))}
        <button
          onClick={() => void onOpenVideo()}
          disabled={exporting}
          style={{ padding: "4px 12px", marginLeft: "auto", background: "#3a3a40", color: "#fff", border: "none", borderRadius: 4 }}
        >
          Open video…
        </button>
      </div>

      {status === "error" && <p style={{ color: "#ff6b6b" }}>Error — {error}</p>}
      {status === "loading" && <p style={{ color: "#aaa" }}>loading test clip…</p>}

      <canvas
        ref={canvasRef}
        style={{
          width: "100%",
          maxWidth: 960,
          aspectRatio: "16 / 9",
          background: "#000",
          borderRadius: 6,
          display: "block",
        }}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12, maxWidth: 960 }}>
        <button
          onClick={() => (playing ? stopPlayback() : startPlayback())}
          disabled={status !== "ready"}
          style={{ padding: "6px 14px", minWidth: 80 }}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <input
          type="range"
          min={0}
          max={durationSec || 0}
          step={1 / FPS}
          value={timeSec}
          disabled={status !== "ready"}
          onChange={(e) => onSeek(Number(e.target.value))}
          style={{ flex: 1 }}
        />
      </div>

      {/* Readout on its own line — keeping it out of the slider's flex row so
          its varying width can't resize the slider (caused jitter on seek). */}
      <div style={{ fontVariantNumeric: "tabular-nums", color: "#ddd", marginTop: 8, maxWidth: 960 }}>
        {timeSec.toFixed(2)}s · out {frameNo}
        {expectedFrame != null && (
          <>
            {" · "}
            <strong style={{ color: "#7fd17f" }}>exp src {expectedFrame}</strong>
          </>
        )}
        {actualFrame != null && (
          <>
            {" · "}
            <strong style={{ color: "#d1a17f" }}>decoded {actualFrame}</strong>
          </>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12, maxWidth: 960 }}>
        <button
          onClick={() => void onExport()}
          disabled={status !== "ready" || exporting}
          style={{ padding: "6px 14px" }}
        >
          {exporting ? "Exporting…" : "Export current → mp4"}
        </button>
        <span style={{ color: "#ddd", fontSize: 13 }}>{exportMsg}</span>
      </div>

      <p style={{ color: "#888", marginTop: 8 }}>
        {info} · <span style={{ color: "#7fd17f" }}>{drawInfo}</span>
        {mode === "seek" && " · compare the burned-in frame number to “expected src”"}
      </p>
    </main>
  );
}
