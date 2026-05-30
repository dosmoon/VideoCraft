/**
 * useClipPreview — load everything the clip workbench's preview surfaces need,
 * once, from the sidecar: the bound source video path, the snapshot SRT (per
 * language), the hotclip candidates, and the per-candidate config state
 * (overrides + selection + output geometry).
 *
 * Both tabs share this: the Style tab renders the whole source with a staging
 * crop; the Clips tab renders one candidate's window with that candidate's own
 * crop and also lists its SRT cues. Loading here (not inside CropPreview) keeps
 * the heavy GPU preview a pure renderer and lets the detail panel reuse the
 * parsed cues for its read-only cue list.
 *
 * Data path mirrors the original Tk workbench: source via
 * material.get_artifact("source"); candidates + snapshot SRT via
 * creation.preview_data (snapshot principle); overrides/selection/geometry via
 * creation.load_config.
 */

import { useCallback, useEffect, useState } from "react";
import type { SourceCue } from "@composition/components/index.js";
import type { ClipOverride, HotclipCandidate } from "@creations/clip/types.js";
import { rpc, RpcError } from "../../ipc/client";
import { parseSrt } from "./srt";
import { parseAspect } from "./cropEditor";

export type PreviewStatus = "loading" | "ready" | "nobind" | "nosrc" | "error";

export interface ClipPreviewData {
  srcPath: string;
  srtByLang: Record<string, readonly SourceCue[]>;
  lang: string;
  candidates: HotclipCandidate[];
  /** preview_data's selected index (selected_clip_indices[0] or 0). */
  selectedIndex: number;
  mode: "reframe" | "passthrough";
  aspect: { aw: number; ah: number };
  shortEdge: number;
  /** Per-candidate overrides keyed by candidate index. */
  overrides: Record<number, ClipOverride>;
  /** Indices checked into the batch (selected_clip_indices). */
  selectedIndices: number[];
}

/** Shape returned by the clip preview_provider (Python). */
interface RawPreviewData {
  lang: string;
  candidates: HotclipCandidate[];
  selectedIndex: number;
  subtitlePath: string | null;
  override: ClipOverride | null;
}

function fmtErr(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  if (err instanceof Error) return `${err.name}: ${err.message}`;
  return String(err);
}

/** Parse config.clips_overrides (JSON object with string int keys) → {idx: override}. */
function parseOverrides(raw: unknown): Record<number, ClipOverride> {
  const out: Record<number, ClipOverride> = {};
  if (raw && typeof raw === "object") {
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const idx = Number(k);
      if (Number.isInteger(idx) && v && typeof v === "object") {
        out[idx] = v as ClipOverride;
      }
    }
  }
  return out;
}

export function useClipPreview(type: string, instance: string) {
  const [status, setStatus] = useState<PreviewStatus>("loading");
  const [message, setMessage] = useState("");
  const [data, setData] = useState<ClipPreviewData | null>(null);

  // Lightweight refresh after a write: re-read config only and patch the
  // override/selection/geometry fields in place. Source + SRT + candidates are
  // stable, so this never blanks the preview or re-opens the GPU engine.
  const reload = useCallback(() => {
    void (async () => {
      try {
        const cfg = await rpc.loadConfig(type, instance);
        setData((prev) =>
          prev
            ? {
                ...prev,
                mode:
                  (cfg["output_mode"] as string) === "passthrough" ? "passthrough" : "reframe",
                aspect: parseAspect((cfg["output_aspect"] as string) || "9:16"),
                shortEdge: Number(cfg["output_short_edge"]) || 1080,
                overrides: parseOverrides(cfg["clips_overrides"]),
                selectedIndices: Array.isArray(cfg["selected_clip_indices"])
                  ? (cfg["selected_clip_indices"] as number[])
                  : [],
              }
            : prev,
        );
      } catch {
        /* keep the last good data on a refresh error */
      }
    })();
  }, [type, instance]);

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
        const { type_name: mt, instance_name: mi } = bound;

        const srcPath = await rpc.getArtifact(mt, mi, "source");
        if (!srcPath) {
          if (!disposed) setStatus("nosrc");
          return;
        }

        const pd = (await rpc.previewData(type, instance)) as RawPreviewData;

        // Snapshot SRT (preview_data) → else the live material SRT for the lang.
        let srtText = "";
        if (pd.subtitlePath) {
          srtText = await fetch(window.vc.mediaUrl(pd.subtitlePath)).then((r) => r.text());
        } else if (pd.lang) {
          const p = await rpc.getArtifact(mt, mi, `subtitle:${pd.lang}`);
          if (p) srtText = await fetch(window.vc.mediaUrl(p)).then((r) => r.text());
        }
        const srtByLang: Record<string, readonly SourceCue[]> = {};
        if (pd.lang && srtText) srtByLang[pd.lang] = parseSrt(srtText);

        if (disposed) return;
        setData({
          srcPath,
          srtByLang,
          lang: pd.lang,
          candidates: pd.candidates,
          selectedIndex: pd.selectedIndex,
          mode: (cfg["output_mode"] as string) === "passthrough" ? "passthrough" : "reframe",
          aspect: parseAspect((cfg["output_aspect"] as string) || "9:16"),
          shortEdge: Number(cfg["output_short_edge"]) || 1080,
          overrides: parseOverrides(cfg["clips_overrides"]),
          selectedIndices: Array.isArray(cfg["selected_clip_indices"])
            ? (cfg["selected_clip_indices"] as number[])
            : [],
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
  }, [type, instance]);

  return { status, message, data, reload };
}
