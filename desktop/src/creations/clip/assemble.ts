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

import { clip, gap, type CropRect, type Timeline, type Track, type TrackChild } from "../../composition/ir.js";
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
import type { ClipComponentConfig, ClipDubbingConfig, ClipOverride, HotclipCandidate } from "./types.js";

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
  /**
   * Spatial reframe rect (normalized source coords) for the video clip. Omit for
   * passthrough/letterbox (whole source); present = reframe (cover the crop).
   */
  cropRect?: CropRect;
  /**
   * Media id/path for the enabled dubbing component's audio (resolved upstream).
   * The dub file is aligned to the full source timeline, so the dub clip slices
   * the SAME candidate window as the source audio. Omit = no dub.
   */
  dubbingAudioRef?: string;
}

export function buildClipTimeline(input: BuildClipTimelineInput): Timeline {
  const { components, candidate, override, srtByLang, mediaRef, frameAspect, cropRect, dubbingAudioRef } = input;

  const [start, end] = resolveStartEnd(candidate, override);
  const durationSec = Math.max(0, end - start);

  // Video track: a single media clip windowed to the candidate → TimeMap.
  // crop (when set) is the per-clip spatial reframe carried on the IR Clip.
  const videoTrack: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: [
      clip({
        kind: "video",
        durationSec,
        sourceStart: start,
        mediaRef,
        ...(cropRect ? { crop: cropRect } : {}),
        style: {},
        data: {},
      }),
    ],
  };
  // Audio track(s) over the candidate window (synced 1:1 with video). Default =
  // source audio at unity gain. An enabled dubbing component swaps it (replace)
  // or adds a second track under it (mix, original ducked to source_gain_db).
  const sourceAudioTrack = (gainDb = 0): Track => ({
    kind: "audio",
    z: 0,
    enabled: true,
    children: [clip({ kind: "audio", durationSec, sourceStart: start, mediaRef, style: { gainDb }, data: {} })],
  });
  const audioTracks = buildAudioTracks(components, durationSec, start, dubbingAudioRef, sourceAudioTrack);
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

  return { durationSec, tracks: [videoTrack, ...audioTracks, ...overlayTracks] };
}

/**
 * Resolve the candidate's audio tracks from the dubbing component (if any).
 *   - no enabled dub / no resolved audio → [source audio] (unchanged).
 *   - replace → [dub] only (original dropped).
 *   - mix     → [source (ducked to source_gain_db), dub (at gain_db)].
 * The dub file is full-source-aligned, so the dub clip slices the SAME window
 * (sourceStart = the candidate's cut start) as the source audio; `offset_sec`
 * delays it via a leading gap, trimming the tail so the track total stays
 * `durationSec`.
 */
function buildAudioTracks(
  components: readonly ClipComponentConfig[],
  durationSec: number,
  start: number,
  dubbingAudioRef: string | undefined,
  sourceAudioTrack: (gainDb?: number) => Track,
): Track[] {
  const dub = components.find(
    (c): c is ClipDubbingConfig => c.kind === "clip_dubbing" && c.enabled === true,
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
        sourceStart: start,
        mediaRef: dubbingAudioRef,
        style: { gainDb: Number(dub.gain_db) || 0 },
        data: {},
      }),
    );
  }
  const dubTrack: Track = { kind: "audio", z: 0, enabled: true, children };
  return dub.mode === "mix" ? [sourceAudioTrack(Number(dub.source_gain_db) || 0), dubTrack] : [dubTrack];
}
