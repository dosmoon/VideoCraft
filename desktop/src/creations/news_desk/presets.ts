/**
 * News-desk preset storage (ADR-0008 TS port of `src/creations/news_desk/
 * presets.py`).
 *
 * A preset is an ordered component list + name/description; applying replaces the
 * instance's components wholesale. Builtins are constructed from componentDefs +
 * style overrides (single canonical-shape source). User presets persist via the
 * injected Fs to `<presetsDir>/news_desk.json` under `user_presets`. Per-project
 * content (subtitle srt_path, chapter schedule/titles, image_watermark
 * image_path) is dropped on save — a preset captures visual decisions only.
 *
 * Note: the RPC apply path (configOwner.applyPreset) just deepcopies + re-uniques
 * ids; the audit/scrub helpers used elsewhere in the Tk era are not part of it.
 */

import type { Fs } from "../../renderer/ipc/fs";
import { type ComponentDict, defaultInstance } from "./componentDefs";

const STORE_FILENAME = "news_desk.json";
export const DEFAULT_PRESET_NAME = "新闻发布会";

export interface NewsDeskPreset {
  name: string;
  description: string;
  components: ComponentDict[];
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

// ── builtin component builders ───────────────────────────────────────────────

function chapterComp(topStrip: boolean, startCard: boolean, name = "章节"): ComponentDict {
  const c = defaultInstance("chapter");
  c["name"] = name;
  c["modes"] = { top_strip: topStrip, start_card: startCard };
  return c;
}
function subtitleComp(isChinese: boolean, color: string, name: string, fontsizePct?: number): ComponentDict {
  const c = defaultInstance("subtitle");
  c["name"] = name;
  c["color"] = color;
  c["is_chinese"] = isChinese;
  if (fontsizePct !== undefined) c["fontsize_pct"] = fontsizePct;
  return c;
}
function textWmComp(text: string, name: string, position = "bottom-left", fontsizePct?: number): ComponentDict {
  const c = defaultInstance("text_watermark");
  c["name"] = name;
  c["text"] = text;
  c["position"] = position;
  if (fontsizePct !== undefined) c["text_fontsize_pct"] = fontsizePct;
  return c;
}
function imageWmComp(name = "台标", position = "top-right"): ComponentDict {
  const c = defaultInstance("image_watermark");
  c["name"] = name;
  c["position"] = position;
  return c;
}

function builtins(): Record<string, NewsDeskPreset> {
  return {
    新闻发布会: {
      name: "新闻发布会",
      description: "顶部章节条 + 起始大卡 + 双字幕 + 台标 + 日期戳",
      components: [
        chapterComp(true, true),
        subtitleComp(true, "#FFFF00", "中文字幕"),
        subtitleComp(false, "#FFFFFF", "英文字幕", 0.0222), // 24px @ 1080
        imageWmComp(),
        textWmComp("", "日期戳", "bottom-left", 0.024), // 26px @ 1080
      ],
    },
    演讲: {
      name: "演讲",
      description: "顶部章节条 + 单字幕 + 主讲人名牌",
      components: [
        chapterComp(true, false),
        subtitleComp(true, "#FFFF00", "字幕", 0.0296), // 32px @ 1080
        textWmComp("", "主讲人", "top-left"),
      ],
    },
    极简: {
      name: "极简",
      description: "纯字幕，无章节卡 / 无水印",
      components: [subtitleComp(true, "#FFFFFF", "字幕")],
    },
  };
}

const BUILTIN_NAMES = (): string[] => Object.keys(builtins());

export function isBuiltin(name: string): boolean {
  return name in builtins();
}

// ── project-content stripping (a preset never carries project data) ──────────

const PROJECT_CONTENT_KEYS: Record<string, string[]> = {
  subtitle: ["srt_path"],
  chapter: ["schedule", "titles"],
  image_watermark: ["image_path"],
  // text_watermark intentionally absent — text + style are preset-worthy
};

function serializeComponentsForPreset(components: ComponentDict[]): ComponentDict[] {
  const out = clone(components);
  for (const c of out) {
    for (const k of PROJECT_CONTENT_KEYS[String(c["kind"])] ?? []) delete c[k];
  }
  return out;
}

// ── store IO (Fs-backed) ──────────────────────────────────────────────────────

async function storePath(fs: Fs): Promise<string> {
  return `${await fs.presetsDir()}/${STORE_FILENAME}`;
}

async function readStore(fs: Fs): Promise<Record<string, unknown>> {
  const raw = await fs.readJson<Record<string, unknown>>(await storePath(fs));
  return raw && typeof raw === "object" ? raw : {};
}

/** Merged preset set: builtins (always present) + user presets; a user preset
 *  with a builtin's name overrides it. */
export async function loadPresets(fs: Fs): Promise<Record<string, NewsDeskPreset>> {
  const out: Record<string, NewsDeskPreset> = {};
  for (const [name, p] of Object.entries(builtins())) {
    out[name] = { name: p.name, description: p.description, components: clone(p.components) };
  }
  const userDict = (await readStore(fs))["user_presets"];
  if (userDict && typeof userDict === "object") {
    for (const [name, entry] of Object.entries(userDict as Record<string, unknown>)) {
      if (!entry || typeof entry !== "object") continue;
      const e = entry as Record<string, unknown>;
      const nm = String(name).trim();
      if (!nm) continue;
      out[nm] = {
        name: nm,
        description: String(e["description"] ?? ""),
        components: Array.isArray(e["components"])
          ? (e["components"] as unknown[]).filter((c): c is ComponentDict => typeof c === "object" && c !== null)
          : [],
      };
    }
  }
  return out;
}

export async function listPresetNames(fs: Fs): Promise<string[]> {
  const presets = await loadPresets(fs);
  const builtinOrder = BUILTIN_NAMES().filter((n) => n in presets);
  const userAlpha = Object.keys(presets)
    .filter((n) => !isBuiltin(n))
    .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  return [...builtinOrder, ...userAlpha];
}

export async function getPreset(fs: Fs, name: string): Promise<NewsDeskPreset | null> {
  return (await loadPresets(fs))[name] ?? null;
}

export async function saveUserPreset(fs: Fs, preset: NewsDeskPreset): Promise<void> {
  if (isBuiltin(preset.name)) throw new Error(`cannot overwrite builtin preset '${preset.name}'`);
  const clean: NewsDeskPreset = {
    name: preset.name,
    description: preset.description,
    components: serializeComponentsForPreset(preset.components),
  };
  const raw = await readStore(fs);
  const userDict = (raw["user_presets"] && typeof raw["user_presets"] === "object" ? raw["user_presets"] : {}) as Record<
    string,
    unknown
  >;
  userDict[clean.name] = clean;
  raw["user_presets"] = userDict;
  await fs.writeJson(await storePath(fs), raw);
}

export async function deleteUserPreset(fs: Fs, name: string): Promise<boolean> {
  if (isBuiltin(name)) return false;
  const raw = await readStore(fs);
  const userDict = raw["user_presets"];
  if (!userDict || typeof userDict !== "object" || !(name in (userDict as Record<string, unknown>))) return false;
  delete (userDict as Record<string, unknown>)[name];
  raw["user_presets"] = userDict;
  await fs.writeJson(await storePath(fs), raw);
  return true;
}

export function builtinNames(): string[] {
  return BUILTIN_NAMES();
}
