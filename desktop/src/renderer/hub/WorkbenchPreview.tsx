/**
 * WorkbenchPreview — the first step of in-workbench WYSIWYG. It resolves the
 * creation's bound material's source video via RPC (creation.load_config →
 * bound_material → material.get_artifact "source") and renders it through the
 * real GPU engine (Backend + ClipReader + resolveFrameAt + drawFrameSlice),
 * scrubbable.
 *
 * Scope of THIS slice: the raw source only — no overlay composition yet, so
 * component edits don't show here. The next slice feeds buildClipTimeline
 * (candidate + cues + config) so the preview reflects the edited components.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { resolveFrameAt } from "@composition/compositor/resolve.js";
import { clip, computeTimelineDuration, type Timeline, type Track } from "@composition/ir.js";
import { Backend } from "../engine/gpu/Backend";
import { MediaSource } from "../engine/source/MediaSource";
import { ClipReader } from "../engine/source/ClipReader";
import { drawFrameSlice, type DrawDeps } from "../engine/compositor/draw";
import type { VideoSource } from "../engine/types";
import { rpc, RpcError } from "../ipc/client";

const SOURCE_REF = "source";
const CANVAS_W = 1280;
const CANVAS_H = 720;
const FPS = 30;

type Status = "loading" | "ready" | "nobind" | "nosrc" | "error";

interface Engine {
  backend: Backend;
  reader: ClipReader;
  timeline: Timeline;
  deps: DrawDeps;
}

/** A one-video-clip timeline covering the whole source (no overlays yet). */
function sourceTimeline(durationSec: number): Timeline {
  const track: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: [
      clip({ kind: "video", durationSec, sourceStart: 0, mediaRef: SOURCE_REF, style: {}, data: {} }),
    ],
  };
  return { tracks: [track], durationSec: computeTimelineDuration([track]) };
}

export function WorkbenchPreview(props: { type: string; instance: string }) {
  const { type, instance } = props;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const inFlight = useRef(false);
  const pending = useRef<number | null>(null);

  const [status, setStatus] = useState<Status>("loading");
  const [message, setMessage] = useState("");
  const [duration, setDuration] = useState(0);
  const [t, setT] = useState(0);

  const renderAt = useCallback(async (sec: number) => {
    const eng = engineRef.current;
    if (!eng) return;
    // Coalesce "latest wins": if a render is in flight, stash the newest target
    // and let the running loop pick it up. A plain in-flight drop would discard
    // the final scrub position; this guarantees it renders.
    if (inFlight.current) {
      pending.current = sec;
      return;
    }
    inFlight.current = true;
    try {
      let target: number | null = sec;
      while (target !== null) {
        pending.current = null;
        const lastT = Math.max(0, eng.timeline.durationSec - 1 / FPS);
        const t = Math.min(Math.max(0, target), lastT);
        const slice = resolveFrameAt(eng.timeline, t);
        // exact = true: a paused single-frame preview must wait for the precise
        // decoded frame. Non-exact frameAt() returns null on a fresh seek (decode
        // not ready) → black, and a stale buffered frame on the next → the
        // regular black/image alternation. frameAtExact blocks for the real frame.
        await drawFrameSlice(slice, eng.deps, true);
        target = pending.current;
      }
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    setStatus("loading");
    setMessage("");
    setDuration(0);
    setT(0);

    void (async () => {
      try {
        const cfg = await rpc.loadConfig(type, instance);
        const bound = cfg["bound_material"] as { type_name?: string; instance_name?: string } | null;
        if (!bound || !bound.type_name || !bound.instance_name) {
          if (!disposed) setStatus("nobind");
          return;
        }
        const srcPath = await rpc.getArtifact(bound.type_name, bound.instance_name, "source");
        if (!srcPath) {
          if (!disposed) setStatus("nosrc");
          return;
        }
        const canvas = canvasRef.current;
        if (!canvas || disposed) return;

        const backend = new Backend();
        await backend.init(canvas);
        backend.resize(CANVAS_W, CANVAS_H);
        const overlayCanvas = new OffscreenCanvas(CANVAS_W, CANVAS_H);
        const overlayCtx = overlayCanvas.getContext("2d");
        if (!overlayCtx) throw new Error("failed to get 2d context");

        const ms = await MediaSource.open(window.vc.mediaUrl(srcPath));
        const reader = new ClipReader(ms);
        const durationSec = ms.durationUs / 1_000_000;
        const sources = new Map<string, VideoSource>([[SOURCE_REF, reader]]);
        const deps: DrawDeps = { backend, sources, fit: "contain", overlayCanvas, overlayCtx };

        if (disposed) {
          reader.dispose();
          backend.dispose();
          return;
        }
        engineRef.current = { backend, reader, timeline: sourceTimeline(durationSec), deps };
        setDuration(durationSec);
        setStatus("ready");
        await renderAt(0);
      } catch (err) {
        if (!disposed) {
          setStatus("error");
          setMessage(
            err instanceof RpcError
              ? `[${err.code}] ${err.message}`
              : err instanceof Error
                ? `${err.name}: ${err.message}`
                : String(err),
          );
        }
      }
    })();

    return () => {
      disposed = true;
      engineRef.current?.reader.dispose();
      engineRef.current?.backend.dispose();
      engineRef.current = null;
    };
  }, [type, instance, renderAt]);

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase" }}>
          源预览
        </span>
        <span style={{ fontSize: 11, color: "#666" }}>暂不含叠加层</span>
        {status === "error" && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {message}</span>}
      </div>

      {/* Canvas is always mounted while loading/ready so the engine can attach. */}
      <canvas
        ref={canvasRef}
        style={{
          width: "100%",
          maxWidth: 480,
          aspectRatio: "16 / 9",
          background: "#000",
          borderRadius: 6,
          display: status === "ready" || status === "loading" ? "block" : "none",
        }}
      />

      {status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>加载源…</p>}
      {status === "nobind" && (
        <p style={{ color: "#888", fontSize: 12 }}>未绑定素材 — 无法预览源</p>
      )}
      {status === "nosrc" && (
        <p style={{ color: "#888", fontSize: 12 }}>绑定素材尚无源视频</p>
      )}

      {status === "ready" && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, maxWidth: 480, marginTop: 6 }}>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={1 / FPS}
            value={t}
            onChange={(e) => {
              const v = Number(e.target.value);
              setT(v);
              void renderAt(v);
            }}
            style={{ flex: 1 }}
          />
          <span style={{ fontVariantNumeric: "tabular-nums", color: "#bbb", fontSize: 12 }}>
            {t.toFixed(2)}s
          </span>
        </div>
      )}
    </div>
  );
}
