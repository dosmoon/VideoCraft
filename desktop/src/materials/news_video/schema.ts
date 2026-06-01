/**
 * Source content context — two on-disk files with strict roles (ADR-0008 TS port
 * of `src/materials/news_video/schema.py`). Phase B foundation: the pure data
 * layer of the news_video material, persisted via the injected Fs.
 *
 *   source/basic_info.json — SourceBasicInfo (5 fields): user HINTS, INPUT-ONLY
 *     for AI Fill. Downstream renderers MUST NOT read this.
 *   source/context.json    — SourceContext (15 fields): AI-generated canonical
 *     archive, the SINGLE downstream source of truth.
 *
 * All fields are strings. from-dict keeps only known string fields (defaults "");
 * write is atomic + matches Python *.save() byte format (indent 2, no trailing
 * newline) so on-disk JSON is unchanged. `context_prompt_block` (AI-prompt
 * injection) is intentionally NOT ported here — it belongs with the capability
 * gateway (B2), not the data layer.
 */

import type { Fs } from "../../renderer/ipc/fs";

export const BASIC_INFO_FILENAME = "basic_info.json";
export const CONTEXT_FILENAME = "context.json";

/** 5 anchor fields a human fills in 30s (authoritative seed for AI extraction). */
export const BASIC_INFO_FIELDS = [
  "host",
  "host_bio",
  "event_date",
  "event_location",
  "episode_topic",
] as const;

/** 15 fields owned by AI extraction (5 AI-verified anchors + 10 AI-derived). */
export const CONTEXT_FIELDS = [
  "host",
  "host_bio",
  "event_date",
  "event_location",
  "episode_topic",
  "host_affiliation",
  "guests",
  "event_time",
  "show_type",
  "event_summary",
  "key_points",
  "background",
  "audience",
  "platform_tone",
  "notes",
] as const;

export type SourceBasicInfo = Record<(typeof BASIC_INFO_FIELDS)[number], string>;
export type SourceContext = Record<(typeof CONTEXT_FIELDS)[number], string>;

function fromDict(fields: readonly string[], d: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  const raw = (d && typeof d === "object" ? d : {}) as Record<string, unknown>;
  for (const f of fields) out[f] = typeof raw[f] === "string" ? (raw[f] as string) : "";
  return out;
}

export function basicInfoFromDict(d: unknown): SourceBasicInfo {
  return fromDict(BASIC_INFO_FIELDS, d) as SourceBasicInfo;
}
export function contextFromDict(d: unknown): SourceContext {
  return fromDict(CONTEXT_FIELDS, d) as SourceContext;
}
export function isEmpty(obj: Record<string, string>): boolean {
  return !Object.values(obj).some((v) => v.trim());
}

// ── Paths + Fs-backed IO ──────────────────────────────────────────────────────

export const basicInfoPath = (sourceDir: string): string => `${sourceDir}/${BASIC_INFO_FILENAME}`;
export const contextPath = (sourceDir: string): string => `${sourceDir}/${CONTEXT_FILENAME}`;

export async function readBasicInfo(fs: Fs, sourceDir: string): Promise<SourceBasicInfo> {
  return basicInfoFromDict(await fs.readJson(basicInfoPath(sourceDir)));
}
export async function writeBasicInfo(fs: Fs, sourceDir: string, info: SourceBasicInfo): Promise<void> {
  await fs.writeJson(basicInfoPath(sourceDir), info);
}
export async function readContext(fs: Fs, sourceDir: string): Promise<SourceContext> {
  return contextFromDict(await fs.readJson(contextPath(sourceDir)));
}
export async function writeContext(fs: Fs, sourceDir: string, ctx: SourceContext): Promise<void> {
  await fs.writeJson(contextPath(sourceDir), ctx);
}
export async function readPlatformMetadata(fs: Fs, sourceDir: string): Promise<Record<string, unknown>> {
  const d = await fs.readJson<Record<string, unknown>>(`${sourceDir}/meta.json`);
  return d && typeof d === "object" ? d : {};
}
