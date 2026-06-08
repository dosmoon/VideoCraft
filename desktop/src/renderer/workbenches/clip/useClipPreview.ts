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
import { rpc, RpcError, type RenderedClip } from "../../ipc/client";
import { parseSrt } from "./srt";
import { parseAspect, parseClipMode, type ClipMode } from "@composition/crop.js";

export type PreviewStatus = "loading" | "ready" | "nobind" | "nosrc" | "error";

export interface ClipPreviewData {
  srcPath: string;
  srtByLang: Record<string, readonly SourceCue[]>;
  lang: string;
  candidates: HotclipCandidate[];
  /** preview_data's selected index (selected_clip_indices[0] or 0). */
  selectedIndex: number;
  mode: ClipMode;
  aspect: { aw: number; ah: number };
  shortEdge: number;
  /** Per-candidate overrides keyed by candidate index. */
  overrides: Record<number, ClipOverride>;
  /** Indices checked into the batch (selected_clip_indices). */
  selectedIndices: number[];
  /** Previously rendered outputs (config.rendered[]). */
  rendered: RenderedClip[];
  /** x264 encode preset (config.encode_preset). */
  encodePreset: string;
  /** Applied preset name (config.preset_name), "" if none. */
  presetName: string;
  /** Subtitle (SRT) languages — the subtitle component's language dropdown. */
  subtitleLangs: string[];
}

/** Shape returned by the clip preview_provider (Python). */
interface RawPreviewData {
  lang: string;
  candidates: HotclipCandidate[];
  selectedIndex: number;
  subtitlePath: string | null;
  /** Snapshot SRT path per subtitle language (bilingual: each subtitle picks its own). */
  subtitlePaths?: Record<string, string>;
  override: ClipOverride | null;
  availableLangs?: string[];
  subtitleLangs?: string[];
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

export function useClipPreview(type: string, instance: string, refreshKey = 0) {
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
                mode: parseClipMode(cfg["output_mode"]),
                aspect: parseAspect((cfg["output_aspect"] as string) || "9:16"),
                shortEdge: Number(cfg["output_short_edge"]) || 1080,
                overrides: parseOverrides(cfg["clips_overrides"]),
                selectedIndices: Array.isArray(cfg["selected_clip_indices"])
                  ? (cfg["selected_clip_indices"] as number[])
                  : [],
                rendered: Array.isArray(cfg["rendered"]) ? (cfg["rendered"] as RenderedClip[]) : [],
                encodePreset: String(cfg["encode_preset"] ?? prev.encodePreset),
                presetName: String(cfg["preset_name"] ?? ""),
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

        // Load EVERY available language's snapshot SRT so a bilingual clip's
        // second subtitle component (a different language) resolves its cues.
        // Falls back to the active subtitlePath for older payloads.
        const paths: Record<string, string> =
          pd.subtitlePaths ?? (pd.subtitlePath && pd.lang ? { [pd.lang]: pd.subtitlePath } : {});
        const srtByLang: Record<string, readonly SourceCue[]> = {};
        for (const [lang, path] of Object.entries(paths)) {
          try {
            const txt = await fetch(window.vc.mediaUrl(path)).then((r) => r.text());
            srtByLang[lang] = parseSrt(txt);
          } catch {
            /* skip a lang whose SRT can't be read */
          }
        }

        if (disposed) return;
        setData({
          srcPath,
          srtByLang,
          lang: pd.lang,
          candidates: pd.candidates,
          selectedIndex: pd.selectedIndex,
          mode: parseClipMode(cfg["output_mode"]),
          aspect: parseAspect((cfg["output_aspect"] as string) || "9:16"),
          shortEdge: Number(cfg["output_short_edge"]) || 1080,
          overrides: parseOverrides(cfg["clips_overrides"]),
          selectedIndices: Array.isArray(cfg["selected_clip_indices"])
            ? (cfg["selected_clip_indices"] as number[])
            : [],
          rendered: Array.isArray(cfg["rendered"]) ? (cfg["rendered"] as RenderedClip[]) : [],
          encodePreset: String(cfg["encode_preset"] ?? "medium"),
          presetName: String(cfg["preset_name"] ?? ""),
          subtitleLangs: Array.isArray(pd.subtitleLangs) ? pd.subtitleLangs : [],
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
    // refreshKey forces a full reload (binding a material flips nobind → ready).
  }, [type, instance, refreshKey]);

  return { status, message, data, reload };
}
