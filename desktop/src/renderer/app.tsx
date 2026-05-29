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

  const mode_ = useRef<Mode>("demo");
  const playing_ = useRef(false);
  const timeSec_ = useRef(0);
  const playBase = useRef(0);
  const playT0 = useRef(0);
  const inFlight = useRef(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;

    void (async () => {
      try {
        const backend = new Backend();
        await backend.init(canvas);
        backend.resize(CANVAS_W, CANVAS_H);

        const ms = await MediaSource.open(window.vc.spikeMediaUrl("test_clip.mp4"));
        const reader = new ClipReader(ms);
        if (disposed) {
          reader.dispose();
          backend.dispose();
          return;
        }

        const overlayCanvas = new OffscreenCanvas(CANVAS_W, CANVAS_H);
        const overlayCtx = overlayCanvas.getContext("2d");
        if (!overlayCtx) throw new Error("failed to get 2d context for overlays");

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
          drawDeps: { backend, sources, fit: "contain", overlayCanvas, overlayCtx },
        };
        setInfo(infoStr);
        setDurationSec(engineRef.current.timelines.demo.durationSec);
        setStatus("ready");
        await renderAt(0);
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
      engineRef.current?.backend.dispose();
      engineRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function renderAt(sec: number): Promise<void> {
    const eng = engineRef.current;
    if (!eng || inFlight.current) return;
    inFlight.current = true;
    try {
      const timeline = eng.timelines[mode_.current];
      const t = Math.max(0, sec);
      const slice = resolveFrameAt(timeline, t);
      const stats = await drawFrameSlice(slice, eng.drawDeps);
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
      }
      void renderAt(timeSec_.current);
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
    void renderAt(sec);
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
      <h2 style={{ fontWeight: 600, margin: "0 0 8px" }}>VideoCraft — substrate spike harness</h2>

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
        <span style={{ fontVariantNumeric: "tabular-nums", minWidth: 320, color: "#ddd", flexShrink: 0 }}>
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
        </span>
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
