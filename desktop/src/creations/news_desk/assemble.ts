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

import { clip, gap, type CropRect, type Timeline, type Track, type TrackChild } from "../../composition/ir.js";
import { identityTimeMap } from "../../composition/timemap.js";
import type { CompileContext, SourceCue } from "../../composition/components/index.js";
import { chapter, imageWatermark, subtitle, textWatermark } from "../../composition/components/index.js";
import {
  newsDeskChapterToInstance,
  newsDeskImageWatermarkToInstance,
  newsDeskSubtitleToInstance,
  newsDeskTextWatermarkToInstance,
} from "./mapping.js";
import type { NewsDeskComponentConfig, NewsDeskDubbingConfig } from "./types.js";

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
   *  In passthrough this is the source aspect; in reframe/letterbox it's the
   *  chosen output aspect (overlays position relative to the output frame). */
  frameAspect?: number;
  /**
   * Spatial reframe rect (normalized source coords) for the single full-source
   * video clip. Omit for passthrough/letterbox (whole source); present = reframe.
   */
  cropRect?: CropRect;
  /**
   * Media id/path for the enabled dubbing component's audio (resolved upstream,
   * like cuesBySrtPath). When present and a dubbing component is enabled, it
   * drives the audio track (replace original, or mix under it). Omit = no dub.
   */
  dubbingAudioRef?: string;
}

export function buildNewsDeskTimeline(input: BuildNewsDeskTimelineInput): Timeline {
  const { components, durationSec, cuesBySrtPath, mediaRef, frameAspect, cropRect, dubbingAudioRef } = input;

  // Full-video track → identity TimeMap (no cut, source time === output time).
  // crop (when set) is the per-clip spatial reframe carried on the IR Clip; a
  // single instance-level rect since news_desk has one full-source video clip.
  const videoTrack: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: [
      clip({
        kind: "video",
        durationSec,
        sourceStart: 0,
        mediaRef,
        ...(cropRect ? { crop: cropRect } : {}),
        style: {},
        data: {},
      }),
    ],
  };
  // Audio track(s). Default = the full source audio at unity gain. An enabled
  // dubbing component swaps it (replace) or adds a second track under it (mix,
  // with the original ducked to `source_gain_db`).
  const sourceAudioTrack = (gainDb = 0): Track => ({
    kind: "audio",
    z: 0,
    enabled: true,
    children: [clip({ kind: "audio", durationSec, sourceStart: 0, mediaRef, style: { gainDb }, data: {} })],
  });
  const audioTracks = buildAudioTracks(components, durationSec, dubbingAudioRef, sourceAudioTrack);
  const timeMap = identityTimeMap(durationSec, mediaRef);
  const baseCtx: CompileContext = {
    durationSec,
    timeMap,
    ...(frameAspect != null ? { frameAspect } : {}),
  };

  const overlayTracks: Track[] = [];
  for (const c of components) {
    // A single malformed/content-less component (e.g. a preset chapter with no
    // imported schedule) must never take the whole timeline — and the preview —
    // down. Skip it on error; the video/audio tracks and the other overlays
    // still build, so the preview shows video instead of going black.
    try {
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
    } catch (err) {
      console.warn(`[news_desk] skipped component ${(c as { kind?: string }).kind ?? "?"}:`, err);
    }
  }

  // List order is z-order: earlier component = topmost = highest z. Video at 0.
  const n = overlayTracks.length;
  overlayTracks.forEach((track, i) => (track.z = n - i));

  return { durationSec, tracks: [videoTrack, ...audioTracks, ...overlayTracks] };
}

/**
 * Resolve the timeline's audio tracks from the dubbing component (if any).
 *   - no enabled dubbing / no resolved audio → [source audio] (unchanged).
 *   - replace → [dub] only (original audio dropped).
 *   - mix     → [source audio, dub] (both summed by the mixer; dub at gain_db).
 * `offset_sec` delays the dub via a leading gap and trims its tail so the track
 * total stays `durationSec` (the dub audio file is already full-length).
 */
function buildAudioTracks(
  components: readonly NewsDeskComponentConfig[],
  durationSec: number,
  dubbingAudioRef: string | undefined,
  sourceAudioTrack: (gainDb?: number) => Track,
): Track[] {
  const dub = components.find(
    (c): c is NewsDeskDubbingConfig => c.kind === "dubbing" && c.enabled === true,
  );
  if (!dub || !dubbingAudioRef) return [sourceAudioTrack()];

  const offset = Math.max(0, Math.min(Number(dub.offset_sec) || 0, durationSec));
  const dubDur = Math.max(0, durationSec - offset);
  const children: TrackChild[] = [];
  if (offset > 0) children.push(gap(offset));
  if (dubDur > 0) {
    children.push(
      clip({
        kind: "audio",
        durationSec: dubDur,
        sourceStart: 0,
        mediaRef: dubbingAudioRef,
        style: { gainDb: Number(dub.gain_db) || 0 },
        data: {},
      }),
    );
  }
  const dubTrack: Track = { kind: "audio", z: 0, enabled: true, children };
  // mix: keep the original (ducked to source_gain_db) under the dub; replace: drop it.
  return dub.mode === "mix" ? [sourceAudioTrack(Number(dub.source_gain_db) || 0), dubTrack] : [dubTrack];
}
