/**
 * News-desk assembler — turn the creation's component config into a validated
 * OTIO Timeline over the *full* source video (no cutting).
 *
 * Contrast with the clip assembler: news_desk performs no source cut, so the
 * video track is the whole source and the TimeMap is the identity map —
 * source-anchored content (subtitle cues, chapter schedule) rides through
 * unchanged. Subtitles do NOT stack here (that's clip-specific orchestration);
 * each subtitle keeps its own margin. Chapter can emit two overlay tracks
 * (strip + hero card), exercising the multi-track-per-component path.
 */

import { clip, type Timeline, type Track } from "../../composition/ir.js";
import { identityTimeMap } from "../../composition/timemap.js";
import type { CompileContext, SourceCue } from "../../composition/components/index.js";
import { chapter, imageWatermark, subtitle, textWatermark } from "../../composition/components/index.js";
import {
  newsDeskChapterToInstance,
  newsDeskImageWatermarkToInstance,
  newsDeskSubtitleToInstance,
  newsDeskTextWatermarkToInstance,
} from "./mapping.js";
import type { NewsDeskComponentConfig } from "./types.js";

export interface BuildNewsDeskTimelineInput {
  /** Ordered component config (list order = z-order, top = topmost layer). */
  components: readonly NewsDeskComponentConfig[];
  /** Full source video duration (seconds). */
  durationSec: number;
  /** Host-parsed SRT cues keyed by each subtitle's srt_path (source time). */
  cuesBySrtPath: Readonly<Record<string, readonly SourceCue[]>>;
  /** Source media id/path for the video track. */
  mediaRef: string;
  /** Output frame aspect (W/H); enables subtitle one-line fitting when set.
   *  news_desk renders the full source, so this is the source aspect. */
  frameAspect?: number;
}

export function buildNewsDeskTimeline(input: BuildNewsDeskTimelineInput): Timeline {
  const { components, durationSec, cuesBySrtPath, mediaRef, frameAspect } = input;

  // Full-video track → identity TimeMap (no cut, source time === output time).
  const videoTrack: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: [clip({ kind: "video", durationSec, sourceStart: 0, mediaRef, style: {}, data: {} })],
  };
  // Audio track: the full source audio (no cut), unity gain.
  const audioTrack: Track = {
    kind: "audio",
    z: 0,
    enabled: true,
    children: [
      clip({ kind: "audio", durationSec, sourceStart: 0, mediaRef, style: { gainDb: 0 }, data: {} }),
    ],
  };
  const timeMap = identityTimeMap(durationSec, mediaRef);
  const baseCtx: CompileContext = {
    durationSec,
    timeMap,
    ...(frameAspect != null ? { frameAspect } : {}),
  };

  const overlayTracks: Track[] = [];
  for (const c of components) {
    switch (c.kind) {
      case "subtitle": {
        const cues = cuesBySrtPath[c.srt_path] ?? [];
        overlayTracks.push(...subtitle.compile(newsDeskSubtitleToInstance(c), { ...baseCtx, cues }));
        break;
      }
      case "text_watermark":
        overlayTracks.push(...textWatermark.compile(newsDeskTextWatermarkToInstance(c), baseCtx));
        break;
      case "image_watermark":
        overlayTracks.push(...imageWatermark.compile(newsDeskImageWatermarkToInstance(c), baseCtx));
        break;
      case "chapter":
        overlayTracks.push(...chapter.compile(newsDeskChapterToInstance(c), baseCtx));
        break;
    }
  }

  // List order is z-order: earlier component = topmost = highest z. Video at 0.
  const n = overlayTracks.length;
  overlayTracks.forEach((track, i) => (track.z = n - i));

  return { durationSec, tracks: [videoTrack, audioTrack, ...overlayTracks] };
}
