/**
 * Clip-kind catalog — the registry of render primitives a `Clip.kind` may name.
 *
 * This is the second of the two dispatch axes (see ir.ts): `Clip.kind` selects
 * *what to draw*, while a child's structural `type` (clip | gap | transition)
 * selects *how the timeline is shaped*. Render-time dispatch happens on the
 * kind string alone — no isinstance, no per-kind branches (carried over from the
 * Python `Element.kind` registry contract in core/composition/timeline.py).
 *
 * The overlay/generator vocabulary is ported 1:1 from the existing Python
 * primitives (src/core/composition/primitives/) so the legacy vocabulary is
 * reused, not reinvented — only its mount point changes (overlay-track Clips
 * instead of standalone Elements). Foundation doc §2.4 / §2.5.
 */

/** Media-bearing kinds: real source media on video/audio tracks. */
export const MEDIA_CLIP_KINDS = ["video", "audio"] as const;

/**
 * Generator/overlay kinds: synthesised visual layers with no source media.
 * Ported from src/core/composition/primitives/*.py.
 */
export const OVERLAY_CLIP_KINDS = [
  "subtitle_cue",
  "hook_text",
  "outro_text",
  "chapter_hero_card",
  "topic_strip",
  "text_watermark",
  "image_watermark",
] as const;

export type MediaClipKind = (typeof MEDIA_CLIP_KINDS)[number];
export type OverlayClipKind = (typeof OVERLAY_CLIP_KINDS)[number];

/** Every registered clip kind. Membership is invariant #5 (see ir.ts). */
export const CLIP_KIND_CATALOG: ReadonlySet<string> = new Set<string>([
  ...MEDIA_CLIP_KINDS,
  ...OVERLAY_CLIP_KINDS,
]);

const MEDIA_KIND_SET: ReadonlySet<string> = new Set(MEDIA_CLIP_KINDS);

export function isKnownClipKind(kind: string): boolean {
  return CLIP_KIND_CATALOG.has(kind);
}

/**
 * Whether a kind carries source media (and therefore expects
 * `sourceStart`/`mediaRef` and is bounded by source duration — invariant #2).
 */
export function isMediaKind(kind: string): boolean {
  return MEDIA_KIND_SET.has(kind);
}
