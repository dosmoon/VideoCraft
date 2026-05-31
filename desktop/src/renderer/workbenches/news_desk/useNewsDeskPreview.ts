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

import { useEffect, useState } from "react";
import type { SourceCue } from "@composition/components/index.js";
import { rpc, RpcError } from "../../ipc/client";
import { parseSrt } from "../clip/srt";

export type PreviewStatus = "loading" | "ready" | "nobind" | "nosrc" | "error";

export interface NewsDeskPreviewData {
  srcPath: string;
  durationSec: number;
  /** Cues keyed by the subtitle component's srt_path (the assembler's key). */
  cuesBySrtPath: Record<string, readonly SourceCue[]>;
}

/** Shape returned by the news_desk preview_provider (Python preview.py). */
interface RawPreviewData {
  mediaRef: string | null;
  durationSec: number;
  /** Absolute snapshot SRT path per subtitle component, keyed by its srt_path. */
  subtitlePaths: Record<string, string>;
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

  useEffect(() => {
    let disposed = false;
    setStatus("loading");
    setMessage("");
    setData(null);

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

        if (disposed) return;
        setData({ srcPath, durationSec: pd.durationSec || 0, cuesBySrtPath });
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
  }, [type, instance]);

  return { status, message, data };
}
