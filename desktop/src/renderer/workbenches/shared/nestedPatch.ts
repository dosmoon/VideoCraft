/**
 * Pure read/patch helpers for the metadata-driven ComponentEditor — no React,
 * so they're unit-testable on their own. A FieldSpec addresses either a flat
 * top-level key or a nested leaf via `path`. Patching a nested leaf must re-send
 * the WHOLE top-level sub-object (cloned along the path) because
 * creation.update_component shallow-merges — otherwise siblings are dropped.
 * (This generalises the old news_desk chapterPatch.ts builders.)
 */

import type { FieldSpec } from "@composition/components/fieldSpec.js";

/** Read the value a FieldSpec addresses (flat key or nested path). */
export function readValue(component: Record<string, unknown>, spec: FieldSpec): unknown {
  if (!spec.path) return component[spec.key];
  let cur: unknown = component;
  for (const seg of spec.path) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[seg];
  }
  return cur;
}

/** Whether the value a FieldSpec addresses exists on this instance. */
export function fieldPresent(component: Record<string, unknown>, spec: FieldSpec): boolean {
  if (!spec.path) return spec.key in component;
  let cur: unknown = component;
  for (const seg of spec.path) {
    if (cur == null || typeof cur !== "object" || !(seg in (cur as object))) return false;
    cur = (cur as Record<string, unknown>)[seg];
  }
  return true;
}

/**
 * Build the patch for a field. Flat fields patch their key; nested fields
 * re-send the whole top-level sub-object (path[0]) with the leaf replaced,
 * cloning each level so siblings survive the shallow merge.
 */
export function buildPatch(
  component: Record<string, unknown>,
  spec: FieldSpec,
  value: unknown,
): Record<string, unknown> {
  if (!spec.path) return { [spec.key]: value };
  const [head, ...rest] = spec.path;
  const root = { ...((component[head!] as Record<string, unknown> | undefined) ?? {}) };
  let cursor = root;
  for (let i = 0; i < rest.length - 1; i++) {
    const seg = rest[i]!;
    cursor[seg] = { ...((cursor[seg] as Record<string, unknown> | undefined) ?? {}) };
    cursor = cursor[seg] as Record<string, unknown>;
  }
  cursor[rest[rest.length - 1]!] = value;
  return { [head!]: root };
}
