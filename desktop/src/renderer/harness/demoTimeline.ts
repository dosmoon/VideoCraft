/**
 * Phase 2 demo timeline — built from the REAL shared components + IR, so the
 * draw layer is fed genuine pure-logic output (component.compile → OTIO →
 * resolveFrameAt → drawFrameSlice), proving the substrate consumes what the
 * substrate-free layer produces. Only the source media is synthetic.
 *
 * Video track = the whole test clip; two overlay tracks = a hook card (first
 * seconds) and an outro card (last seconds), exercising z-order + canvas2D text.
 */

import {
  clip,
  computeTimelineDuration,
  type Timeline,
  type Track,
} from "@composition/ir.js";
import { hookCard, outroCard } from "@composition/components/card.js";
import { subtitle } from "@composition/components/subtitle.js";
import { identityTimeMap } from "@composition/timemap.js";

export const DEMO_MEDIA_REF = "test_clip";

function videoTrack(durationSec: number): Track {
  return {
    kind: "video",
    z: 0,
    enabled: true,
    children: [
      clip({ kind: "video", durationSec, sourceStart: 0, mediaRef: DEMO_MEDIA_REF, style: {}, data: {} }),
    ],
  };
}

/**
 * Subtitle timeline (Spike B): video + a real subtitle.compile() overlay track
 * of subtitle_cue clips, rendered via the canvas2D→texture path (Phase's
 * subtitle approach). Sample cues include CJK to exercise that rendering.
 */
export function buildSubtitleTimeline(durationSec: number): Timeline {
  const ctx = {
    durationSec,
    timeMap: identityTimeMap(durationSec),
    cues: [
      { sourceStart: 0.5, sourceEnd: 3.0, text: "Canvas2D subtitle — in the compositor" },
      { sourceStart: 3.5, sourceEnd: 6.0, text: "中文字幕渲染测试 · CJK rendering" },
      { sourceStart: 6.5, sourceEnd: 9.5, text: "描边 + 背景框 · outline + box" },
    ],
  };
  const subTracks = subtitle.compile(
    { ...subtitle.defaultInstance(), fontsizePct: 0.06, bgOpacity: 55, strokePct: 0.004, isChinese: true },
    ctx,
  );
  const tracks: Track[] = [videoTrack(durationSec), ...subTracks];
  tracks.forEach((t, i) => {
    t.z = i;
  });
  return { tracks, durationSec: computeTimelineDuration(tracks) };
}

export function buildDemoTimeline(durationSec: number): Timeline {
  const ctx = { durationSec, timeMap: identityTimeMap(durationSec), cues: [] };
  const cardSec = Math.min(5, durationSec / 2);

  const videoTrack: Track = {
    kind: "video",
    z: 0,
    enabled: true,
    children: [
      clip({
        kind: "video",
        durationSec,
        sourceStart: 0,
        mediaRef: DEMO_MEDIA_REF,
        style: {},
        data: {},
      }),
    ],
  };

  const hook = hookCard.compile(
    { ...hookCard.defaultInstance(), text: "HOOK · first seconds", durationSec: cardSec },
    ctx,
  );
  const outro = outroCard.compile(
    { ...outroCard.defaultInstance(), text: "OUTRO · last seconds", durationSec: cardSec },
    ctx,
  );

  const tracks: Track[] = [videoTrack, ...hook, ...outro];
  // Re-stack z by list order (video lowest), since component-local z is 0-based.
  tracks.forEach((t, i) => {
    t.z = i;
  });

  return { tracks, durationSec: computeTimelineDuration(tracks) };
}
