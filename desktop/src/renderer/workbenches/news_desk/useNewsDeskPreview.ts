/**
 * useNewsDeskPreview — load what the news_desk preview needs, once, from the
 * sidecar: the bound source video path, the source duration, and the snapshot
 * SRT cues keyed by each subtitle component's srt_path.
 *
 * Counterpart to clip's useClipPreview, but for the full-source model: no
 * candidates, no crop, no per-candidate overrides. The data path mirrors the
 * news_desk preview_provider (preview.py): source via material.get_artifact
 * ("source"); duration + per-srt_path snapshot SRTs via creation.preview_data
 * (snapshot principle — the SRTs already live in the instance dir).
 */

import { useCallback, useEffect, useState } from "react";
import type { SourceCue } from "@composition/components/index.js";
import { parseClipMode, parseCropRect, type ClipMode, type CropRect } from "@composition/crop.js";
import { rpc, RpcError } from "../../ipc/client";
import { parseSrt } from "../clip/srt";

export type PreviewStatus = "loading" | "ready" | "nobind" | "nosrc" | "error";

/** Output framing (spatial reframe) read from config.json. */
export interface NewsDeskFraming {
  mode: ClipMode;
  aspect: string;
  shortEdge: number;
  cropRect: CropRect | null;
}

export interface NewsDeskPreviewData {
  srcPath: string;
  durationSec: number;
  /** Cues keyed by the subtitle component's srt_path (the assembler's key). */
  cuesBySrtPath: Record<string, readonly SourceCue[]>;
  /** Output framing — passthrough (whole source) unless the user set a reframe. */
  framing: NewsDeskFraming;
  /** Absolute path of the enabled dubbing track's audio (null when none). */
  dubbingAudioPath: string | null;
}

/** Shape returned by the news_desk preview_provider (TS clientBackend preview). */
interface RawPreviewData {
  mediaRef: string | null;
  durationSec: number;
  /** Absolute snapshot SRT path per subtitle component, keyed by its srt_path. */
  subtitlePaths: Record<string, string>;
  /** Absolute snapshot path of the enabled dubbing track's audio (or null). */
  dubbingAudioPath: string | null;
}

function fmtErr(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  if (err instanceof Error) return `${err.name}: ${err.message}`;
  return String(err);
}

export function useNewsDeskPreview(type: string, instance: string) {
  const [status, setStatus] = useState<PreviewStatus>("loading");
  const [message, setMessage] = useState("");
  const [data, setData] = useState<NewsDeskPreviewData | null>(null);
  // Bumped by reload() to re-run the full fetch (source + snapshot SRTs) after a
  // Style-tab import / preset apply changes which SRTs a component points at.
  const [token, setToken] = useState(0);
  const reload = useCallback(() => setToken((n) => n + 1), []);

  // Blank to "loading" ONLY when the target (type/instance) changes. A reload()
  // refreshes data in place (below) without blanking — blanking would drop the
  // preview out of "ready" and unmount NewsDeskPreview, tearing down and
  // re-initing the WebGPU backend on the same canvas (which black-screens it).
  useEffect(() => {
    setStatus("loading");
    setMessage("");
    setData(null);
  }, [type, instance]);

  useEffect(() => {
    let disposed = false;

    void (async () => {
      try {
        const cfg = await rpc.loadConfig(type, instance);
        const bound = cfg["bound_material"] as
          | { type_name?: string; instance_name?: string }
          | null;
        if (!bound?.type_name || !bound.instance_name) {
          if (!disposed) setStatus("nobind");
          return;
        }
        const srcPath = await rpc.getArtifact(bound.type_name, bound.instance_name, "source");
        if (!srcPath) {
          if (!disposed) setStatus("nosrc");
          return;
        }

        const pd = (await rpc.previewData(type, instance)) as RawPreviewData;
        const cuesBySrtPath: Record<string, readonly SourceCue[]> = {};
        for (const [srtPath, absPath] of Object.entries(pd.subtitlePaths ?? {})) {
          try {
            const txt = await fetch(window.vc.mediaUrl(absPath)).then((r) => r.text());
            cuesBySrtPath[srtPath] = parseSrt(txt);
          } catch {
            /* skip a subtitle whose snapshot can't be read */
          }
        }

        const shortEdge = Number(cfg["output_short_edge"]);
        const framing: NewsDeskFraming = {
          mode: parseClipMode(cfg["output_mode"]),
          aspect: String(cfg["output_aspect"] ?? "16:9"),
          shortEdge: Number.isFinite(shortEdge) ? Math.trunc(shortEdge) : 1080,
          cropRect: parseCropRect(cfg["crop_rect"]),
        };

        if (disposed) return;
        setData({
          srcPath,
          durationSec: pd.durationSec || 0,
          cuesBySrtPath,
          framing,
          dubbingAudioPath: pd.dubbingAudioPath ?? null,
        });
        setStatus("ready");
      } catch (err) {
        if (!disposed) {
          setStatus("error");
          setMessage(fmtErr(err));
        }
      }
    })();

    return () => {
      disposed = true;
    };
  }, [type, instance, token]);

  return { status, message, data, reload };
}
