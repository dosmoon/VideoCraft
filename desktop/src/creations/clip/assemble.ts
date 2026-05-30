/**
 * Clip assembler — turn one hotclip candidate + the creation's component config
 * into a validated OTIO Timeline (foundation doc §3: analysis + creation config
 * → OTIO via the shared components).
 *
 * This is the clip-specific orchestration: cut the source to the candidate's
 * window (one media clip → a TimeMap), then drive each configured component
 * through the shared library, preserving list order as z-order. Ports the role
 * of composer.py::compile_for_candidate, but the output is the new multi-track
 * OTIO Timeline instead of the old overlay-only CompositionTimeline.
 */

import { clip, type Timeline, type Track } from "../../composition/ir.js";
import { buildTimeMap } from "../../composition/timemap.js";
import type { CompileContext, SourceCue, SubtitleInstance } from "../../composition/components/index.js";
import {
  hookCard,
  imageWatermark,
  outroCard,
  subtitle,
  textWatermark,
} from "../../composition/components/index.js";
import {
  clipCardToInstance,
  clipImageWatermarkToInstance,
  clipSubtitleToInstance,
  clipTextWatermarkToInstance,
  resolveHookText,
  resolveOutroText,
  resolveStartEnd,
  stackSubtitleMargins,
} from "./mapping.js";
import type { ClipComponentConfig, ClipOverride, HotclipCandidate } from "./types.js";

export interface BuildClipTimelineInput {
  /** Ordered component config (list order = z-order, top = topmost layer). */
  components: readonly ClipComponentConfig[];
  candidate: HotclipCandidate;
  override?: ClipOverride;
  /** Host-parsed SRT cues per language, in source time. */
  srtByLang: Readonly<Record<string, readonly SourceCue[]>>;
  /** Source media id/path for the video track. */
  mediaRef: string;
  /** Output frame aspect (W/H); enables subtitle one-line fitting when set. */
  frameAspect?: number;
}

export function buildClipTimeline(input: BuildClipTimelineInput): Timeline {
  const { components, candidate, override, srtByLang, mediaRef, frameAspect } = input;

  const [start, end] = resolveStartEnd(candidate, override);
  const durationSec = Math.max(0, end - start);

  // Video track: a single media clip windowed to the candidate → TimeMap.
  const videoTrack: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: [clip({ kind: "video", durationSec, sourceStart: start, mediaRef, style: {}, data: {} })],
  };
  // Audio track: the source audio over the same window (synced 1:1 with video).
  // gainDb 0 = unity; preview/export read this via resolveAudioSegments.
  const audioTrack: Track = {
    kind: "audio",
    z: 0,
    enabled: true,
    children: [
      clip({ kind: "audio", durationSec, sourceStart: start, mediaRef, style: { gainDb: 0 }, data: {} }),
    ],
  };
  const timeMap = buildTimeMap(videoTrack);
  const baseCtx: CompileContext = {
    durationSec,
    timeMap,
    ...(frameAspect != null ? { frameAspect } : {}),
  };

  const hookText = resolveHookText(candidate, override);
  const outroText = resolveOutroText(candidate, override);

  // Pre-map subtitle instances and stack shared-edge margins before compile.
  const subtitleInstances: SubtitleInstance[] = [];
  const stackInput: { instance: SubtitleInstance; hasCues: boolean }[] = [];
  for (const c of components) {
    if (c.kind === "clip_subtitle") {
      const instance = clipSubtitleToInstance(c);
      subtitleInstances.push(instance);
      stackInput.push({ instance, hasCues: (srtByLang[c.language] ?? []).length > 0 });
    }
  }
  stackSubtitleMargins(stackInput);

  const overlayTracks: Track[] = [];
  let subIdx = 0;
  for (const c of components) {
    switch (c.kind) {
      case "clip_subtitle": {
        const instance = subtitleInstances[subIdx++]!;
        const cues = srtByLang[c.language] ?? [];
        overlayTracks.push(...subtitle.compile(instance, { ...baseCtx, cues }));
        break;
      }
      case "clip_text_watermark":
        overlayTracks.push(...textWatermark.compile(clipTextWatermarkToInstance(c), baseCtx));
        break;
      case "clip_image_watermark":
        overlayTracks.push(...imageWatermark.compile(clipImageWatermarkToInstance(c), baseCtx));
        break;
      case "clip_hook_card":
        overlayTracks.push(...hookCard.compile(clipCardToInstance(c, hookText), baseCtx));
        break;
      case "clip_outro_card":
        overlayTracks.push(...outroCard.compile(clipCardToInstance(c, outroText), baseCtx));
        break;
    }
  }

  // List order is z-order: earlier component = topmost = highest z. Video at 0.
  const n = overlayTracks.length;
  overlayTracks.forEach((track, i) => (track.z = n - i));

  return { durationSec, tracks: [videoTrack, audioTrack, ...overlayTracks] };
}
