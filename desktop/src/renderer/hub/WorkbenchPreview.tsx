/**
 * WorkbenchPreview — in-workbench WYSIWYG. It resolves the creation's bound
 * material (creation.load_config → bound_material → material.get_artifact) and
 * renders the clip composition through the real GPU engine (Backend +
 * ClipReader + resolveFrameAt + drawFrameSlice), driven by the SAME pure
 * buildClipTimeline the export path uses — so preview ≡ render structurally.
 *
 * Scope of THIS slice: source + config-driven overlays (subtitle from the
 * material SRT + text/image watermarks), over the WHOLE source via a synthetic
 * full-length candidate. Editing a subtitle/watermark field rebuilds the
 * timeline and re-renders live. NOT yet wired: the real hotclip candidate
 * window + hook/outro text — those live in the creation's snapshot
 * (project_snapshot_principle) and need a creation-snapshot RPC (next slice),
 * so hook/outro cards are omitted from the preview for now.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { resolveFrameAt } from "@composition/compositor/resolve.js";
import type { Timeline } from "@composition/ir.js";
import { buildClipTimeline } from "@creations/clip/assemble.js";
import type { ClipComponentConfig, HotclipCandidate } from "@creations/clip/types.js";
import type { SourceCue } from "@composition/components/index.js";
import { Backend } from "../engine/gpu/Backend";
import { MediaSource } from "../engine/source/MediaSource";
import { ClipReader } from "../engine/source/ClipReader";
import { drawFrameSlice, type DrawDeps } from "../engine/compositor/draw";
import { preloadImageOverlay } from "../engine/overlay/canvas2d";
import type { VideoSource } from "../engine/types";
import { rpc, RpcError, type Component } from "../ipc/client";
import { parseSrt } from "./srt";

const SOURCE_REF = "source";
const CANVAS_W = 1280;
const CANVAS_H = 720;
const FPS = 30;

// Overlays needing real candidate/snapshot data are deferred (see header).
const PREVIEW_SKIP_KINDS = new Set(["clip_hook_card", "clip_outro_card"]);

type Status = "loading" | "ready" | "nobind" | "nosrc" | "error";

interface Engine {
  backend: Backend;
  reader: ClipReader;
  deps: DrawDeps;
}
interface Prep {
  srtByLang: Record<string, readonly SourceCue[]>;
  candidate: HotclipCandidate;
  durationSec: number;
}

function secToTimestamp(sec: number): string {
  const s = Math.max(0, sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = (s % 60).toFixed(3);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${rest.padStart(6, "0")}`;
}

export function WorkbenchPreview(props: { type: string; instance: string; components: Component[] }) {
  const { type, instance, components } = props;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const prepRef = useRef<Prep | null>(null);
  const timelineRef = useRef<Timeline | null>(null);
  const inFlight = useRef(false);
  const pending = useRef<number | null>(null);
  const tRef = useRef(0);
  // Latest components, readable inside the load effect without making it a dep
  // (re-loading the engine on every edit would be wrong).
  const componentsRef = useRef(components);
  componentsRef.current = components;

  const [status, setStatus] = useState<Status>("loading");
  const [message, setMessage] = useState("");
  const [duration, setDuration] = useState(0);
  const [t, setT] = useState(0);

  const renderAt = useCallback(async (sec: number) => {
    const eng = engineRef.current;
    const timeline = timelineRef.current;
    if (!eng || !timeline) return;
    // Coalesce latest-wins (see source-preview commit): never drop the final
    // scrub target to an in-flight guard.
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
        // exact: paused single-frame preview waits for the precise decoded frame.
        await drawFrameSlice(slice, eng.deps, true);
        target = pending.current;
      }
    } finally {
      inFlight.current = false;
    }
  }, []);

  // Load: bound material → source video + SRTs → engine + prep.
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
        const cfg = await rpc.loadConfig(type, instance);
        const bound = cfg["bound_material"] as { type_name?: string; instance_name?: string } | null;
        if (!bound?.type_name || !bound.instance_name) {
          if (!disposed) setStatus("nobind");
          return;
        }
        const { type_name: mt, instance_name: mi } = bound;
        const srcPath = await rpc.getArtifact(mt, mi, "source");
        if (!srcPath) {
          if (!disposed) setStatus("nosrc");
          return;
        }
        const canvas = canvasRef.current;
        if (!canvas || disposed) return;

        // Load every SRT language referenced by a subtitle component (host
        // parses; components stay pure).
        const langs = new Set<string>();
        for (const c of componentsRef.current) {
          if (c.kind === "clip_subtitle" && typeof c["language"] === "string" && c["language"]) {
            langs.add(c["language"] as string);
          }
        }
        const srtByLang: Record<string, readonly SourceCue[]> = {};
        for (const lang of langs) {
          const p = await rpc.getArtifact(mt, mi, `subtitle:${lang}`);
          if (p) {
            const text = await fetch(window.vc.mediaUrl(p)).then((r) => r.text());
            srtByLang[lang] = parseSrt(text);
          }
        }

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
        engineRef.current = { backend, reader, deps };
        // Synthetic full-length candidate — real hotclip window comes later.
        prepRef.current = {
          srtByLang,
          candidate: { start: "00:00:00.000", end: secToTimestamp(durationSec) },
          durationSec,
        };
        setDuration(durationSec);
        setStatus("ready"); // flips the rebuild effect below
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
      prepRef.current = null;
    };
  }, [type, instance]);

  // Rebuild the timeline whenever the (live-edited) components change — this is
  // the WYSIWYG loop: edit a field → new timeline → re-render the current frame.
  useEffect(() => {
    const prep = prepRef.current;
    if (status !== "ready" || !prep) return;
    let cancelled = false;
    void (async () => {
      // Preload image-watermark images so the sync draw path can use them
      // (cached → cheap on repeat). Covers initial render + later edits.
      for (const c of components) {
        if (c.kind === "clip_image_watermark") {
          const p = c["image_path"];
          if (typeof p === "string" && p) {
            try {
              await preloadImageOverlay(p, window.vc.mediaUrl(p));
            } catch {
              /* unloadable image → just renders without it */
            }
          }
        }
      }
      if (cancelled) return;
      const previewComps = components.filter((c) => !PREVIEW_SKIP_KINDS.has(c.kind));
      try {
        timelineRef.current = buildClipTimeline({
          components: previewComps as unknown as ClipComponentConfig[],
          candidate: prep.candidate,
          srtByLang: prep.srtByLang,
          mediaRef: SOURCE_REF,
        });
      } catch (err) {
        setMessage(err instanceof Error ? `compose: ${err.message}` : String(err));
        return;
      }
      void renderAt(tRef.current);
    })();
    return () => {
      cancelled = true;
    };
  }, [components, status, renderAt]);

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase" }}>
          预览
        </span>
        <span style={{ fontSize: 11, color: "#666" }}>完整源 · 字幕/水印实时 · 暂无候选裁剪/hook·outro</span>
        {status === "error" && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {message}</span>}
      </div>

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
      {status === "nobind" && <p style={{ color: "#888", fontSize: 12 }}>未绑定素材 — 无法预览</p>}
      {status === "nosrc" && <p style={{ color: "#888", fontSize: 12 }}>绑定素材尚无源视频</p>}

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
              tRef.current = v;
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
