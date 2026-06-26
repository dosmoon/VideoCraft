/**
 * Component edit-UI metadata — the engine-owned realisation of contract.ts ①
 * ("its edit UI (property panel); lands later"). Pure data, NO React, so this
 * stays in the substrate-agnostic `composition/` layer and is unit-testable.
 * The renderer's <ComponentEditor> interprets these specs to draw the panel.
 *
 * KEY UNIT NOTE: a FieldSpec.key (and the leaves in `path`) is the PERSISTED
 * snake_case WIRE key — the key the editor reads from and patches back onto the
 * component dict via creation.update_component. This is a deliberate exception
 * to "everything in composition/ is camelCase canonical": the camelCase
 * *Instance is an internal compile-time shape produced by each plugin's
 * mapping.ts; the editor never touches it. After the news_desk wire
 * normalisation the two plugins share one wire shape per component, so one
 * FieldSpec list serves both.
 *
 * `min`/`max` are UX hints for the stepper only — they are NOT the authoritative
 * clamp. Clamping lives solely in the per-plugin mapping.ts (ADR-0006: one
 * normalisation site, since presets / AI imports bypass the editor).
 */

export type FieldControl = "number" | "text" | "color" | "checkbox" | "select" | "image";

export interface FieldSpec {
  /** Persisted snake_case wire key (top-level). */
  key: string;
  /**
   * Nested leaf path for components whose wire shape nests (chapter:
   * style.top_strip.bg_color). When set, `key` is the addressing label and the
   * editor reads/writes component[path[0]][path[1]]…; the patch re-sends the
   * whole top-level sub-object (path[0]) to survive update_component's shallow
   * merge. Omitted → a flat top-level field at `key`.
   */
  path?: readonly string[];
  control: FieldControl;
  /** i18n key — NEVER a literal internal name (project rule). */
  labelKey: string;
  /** Optional i18n key for a section header shown above this field (and its run). */
  section?: string;
  /** number: stepper increment + hint bounds (NOT the authoritative clamp). */
  step?: number;
  min?: number;
  max?: number;
  /**
   * Optional UI-unit conversion for a number field. The editor SHOWS
   * `stored * factor` (rounded to `decimals`) with `suffix`, steps by `step` in
   * those display units, and stores back `displayValue / factor`. Lets a
   * canonical fraction read as px@1080 or % — restoring the Tk panels' intuitive
   * units while storage stays canonical (and unifies display across components,
   * e.g. subtitle fraction-fontsize and chapter px-fontsize both shown as px).
   * When set, `display.step` supersedes the top-level `step`.
   */
  display?: { factor: number; step: number; decimals?: number; suffix?: string };
  /** select: option values (raw, e.g. "top-right"). */
  options?: readonly string[];
  /** select: per-option i18n keys, parallel to `options`; missing → raw value. */
  optionLabelKeys?: Readonly<Record<string, string>>;
  /** Show this field only when the predicate passes (e.g. chapter mode gating). */
  visibleWhen?: (component: Record<string, unknown>) => boolean;
}

import { imageWatermarkFields, textWatermarkFields } from "./watermark.js";
import { subtitleFields } from "./subtitle.js";
import { cardFields } from "./card.js";
import { chapterFields } from "./chapter.js";
import { dubbingFields } from "./dubbing.js";

/**
 * canonical-kind → FieldSpec[]. Keyed by the bare engine kind; both plugin
 * kinds (clip_image_watermark and image_watermark) resolve here via
 * canonicalKind(). A kind with no entry → the editor renders a "no fields"
 * notice (every shipped component is registered below).
 */
const FIELD_REGISTRY: Record<string, readonly FieldSpec[]> = {
  image_watermark: imageWatermarkFields,
  text_watermark: textWatermarkFields,
  subtitle: subtitleFields,
  hook_card: cardFields,
  outro_card: cardFields,
  chapter: chapterFields,
  dubbing: dubbingFields,
};

/** Strip a creation's kind prefix to the bare engine kind. */
export function canonicalKind(kind: string): string {
  return kind.startsWith("clip_") ? kind.slice("clip_".length) : kind;
}

/** The edit-UI field metadata for a component kind, or undefined if unmigrated. */
export function fieldsForKind(kind: string): readonly FieldSpec[] | undefined {
  return FIELD_REGISTRY[canonicalKind(kind)];
}
