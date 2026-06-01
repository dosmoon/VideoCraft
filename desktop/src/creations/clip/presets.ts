/**
 * Clip preset store — components-based schema (ADR-0008 TS port of
 * `src/creations/clip/presets.py`).
 *
 * A preset carries `components` (same wire shape as the config's component list),
 * `output` (aspect/short_edge/mode), and `encode_preset`. Built-ins are seeded on
 * first load and re-injected on every load, so hand-deleting one never strands
 * the user. User presets sort alphabetically after the built-in declared order.
 *
 * Persisted via the injected `Fs` to `<presetsDir>/clip_preset.json` (the global,
 * cross-project store). Schema-strict load: entries lacking a list `components`
 * or a dict `output` are dropped (pre-alpha — no migration shim).
 */

import type { Fs } from "../../renderer/ipc/fs";
import { type ComponentDict, defaultInstance } from "./componentDefs";

export const BUILTIN_DEFAULT = "Default 9:16";
const STORE_FILENAME = "clip_preset.json";

export interface PresetOutput {
  aspect: string;
  short_edge: number;
  mode: string;
}
export interface PresetEntry {
  components: ComponentDict[];
  output: PresetOutput;
  encode_preset: string;
}
export interface PresetStore {
  last_used: string;
  presets: Record<string, PresetEntry>;
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** A fresh default instance for `kind` with `overrides` merged on top. */
function comp(kind: string, overrides: ComponentDict = {}): ComponentDict {
  return { ...defaultInstance(kind), ...overrides };
}

/** Built-in presets, constructed lazily (component defaults available). */
function builtinPresets(): Record<string, PresetEntry> {
  const out = (aspect: string): PresetOutput => ({ aspect, short_edge: 1080, mode: "reframe" });
  return {
    [BUILTIN_DEFAULT]: {
      components: [comp("clip_subtitle"), comp("clip_hook_card")],
      output: out("9:16"),
      encode_preset: "veryfast",
    },
    "TikTok / Reels / Shorts (9:16 中文)": {
      components: [
        comp("clip_subtitle", { fontsize_pct: 28 / 1080, color: "#FFFF00", bold: true, is_chinese: true }),
        comp("clip_hook_card", { position: "upper-third" }),
        comp("clip_outro_card", { position: "lower-third" }),
      ],
      output: out("9:16"),
      encode_preset: "veryfast",
    },
    "YouTube 横屏 (16:9 中文)": {
      components: [
        comp("clip_subtitle", { fontsize_pct: 30 / 1080, color: "#FFFF00", bold: true, is_chinese: true }),
        comp("clip_hook_card", { position: "upper-third" }),
        comp("clip_outro_card", { position: "lower-third" }),
      ],
      output: out("16:9"),
      encode_preset: "veryfast",
    },
    "Instagram / 小红书 (1:1 中文)": {
      components: [
        comp("clip_subtitle", { fontsize_pct: 26 / 1080, color: "#FFFF00", bold: true, is_chinese: true }),
        comp("clip_hook_card", { position: "upper-third" }),
      ],
      output: out("1:1"),
      encode_preset: "veryfast",
    },
  };
}

export function builtinNames(): string[] {
  return Object.keys(builtinPresets());
}
export function isBuiltin(name: string): boolean {
  return name in builtinPresets();
}

function validEntry(entry: unknown): entry is PresetEntry {
  if (typeof entry !== "object" || entry === null) return false;
  const e = entry as Record<string, unknown>;
  return Array.isArray(e["components"]) && typeof e["output"] === "object" && e["output"] !== null;
}

function seedStore(): PresetStore {
  return { last_used: BUILTIN_DEFAULT, presets: clone(builtinPresets()) };
}

async function storePath(fs: Fs): Promise<string> {
  const dir = await fs.presetsDir();
  return `${dir}/${STORE_FILENAME}`;
}

/** Read the store, validate, re-inject any missing built-ins. First-run /
 *  corrupt file yields a freshly seeded store. */
export async function loadStore(fs: Fs): Promise<PresetStore> {
  const raw = await fs.readJson<{ last_used?: string; presets?: Record<string, unknown> }>(
    await storePath(fs),
  );
  if (!raw || typeof raw !== "object" || !("presets" in raw)) return seedStore();

  const kept: Record<string, PresetEntry> = {};
  for (const [name, entry] of Object.entries(raw.presets ?? {})) {
    if (validEntry(entry)) kept[name] = entry;
  }
  const builtins = builtinPresets();
  for (const [name, entry] of Object.entries(builtins)) {
    if (!(name in kept)) kept[name] = clone(entry);
  }
  let lastUsed = raw.last_used ?? BUILTIN_DEFAULT;
  if (!(lastUsed in kept)) lastUsed = BUILTIN_DEFAULT;
  return { last_used: lastUsed, presets: kept };
}

export async function saveStore(fs: Fs, store: PresetStore): Promise<void> {
  await fs.writeJson(await storePath(fs), store);
}

/** Built-ins first (declared order), then user presets sorted case-insensitively. */
export function listPresets(store: PresetStore): string[] {
  const builtins = builtinPresets();
  const builtinOrder = Object.keys(builtins).filter((n) => n in store.presets);
  const userNames = Object.keys(store.presets)
    .filter((n) => !(n in builtins))
    .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  return [...builtinOrder, ...userNames];
}

export function getPreset(store: PresetStore, name: string): PresetEntry | null {
  const raw = store.presets[name];
  return raw ? clone(raw) : null;
}

export function upsertPreset(
  store: PresetStore,
  name: string,
  args: { components: ComponentDict[]; outputAspect: string; outputShortEdge: number; outputMode: string; encodePreset: string },
): void {
  store.presets[name] = {
    components: clone(args.components),
    output: { aspect: String(args.outputAspect), short_edge: Math.trunc(args.outputShortEdge), mode: String(args.outputMode) },
    encode_preset: String(args.encodePreset),
  };
}

/** Delete a user preset. Built-ins are protected. Returns whether it deleted. */
export function deletePreset(store: PresetStore, name: string): boolean {
  if (isBuiltin(name)) return false;
  if (!(name in store.presets)) return false;
  delete store.presets[name];
  if (store.last_used === name) store.last_used = BUILTIN_DEFAULT;
  return true;
}

export function getLastUsed(store: PresetStore): string {
  const name = store.last_used ?? BUILTIN_DEFAULT;
  return name in store.presets ? name : BUILTIN_DEFAULT;
}

export function setLastUsed(store: PresetStore, name: string): void {
  if (name in store.presets) store.last_used = name;
}
