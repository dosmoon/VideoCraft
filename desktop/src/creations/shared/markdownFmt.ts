/**
 * Tier-1 markdown / language helpers shared across derivative publish docs
 * (ADR-0008 TS port of `src/core/markdown_fmt.py`).
 *
 * Pure functions, no derivative-type knowledge. Per-derivative publish templates
 * (clip/publish.ts, news_desk/publish.ts) import these. Headings/labels localize
 * to the *source video's* language (lang_iso), not the UI language.
 */

/** True if `langIso` is a Chinese tag (zh, zh-CN, zh-TW …). */
export function isZh(langIso: string): boolean {
  return (langIso || "").toLowerCase().split("-")[0]!.startsWith("zh");
}

/** Pick zh or en based on `langIso`. */
export function t(langIso: string, zh: string, en: string): string {
  return isZh(langIso) ? zh : en;
}

/** Seconds → `H:MM:SS` (when ≥1h) or `M:SS`. */
export function fmtDur(seconds: number): string {
  const total = Math.max(0, Math.trunc(seconds));
  const h = Math.trunc(total / 3600);
  const m = Math.trunc((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** List of tag strings → single space-joined `#a #b #c`. Each tag gets a `#`
 *  if not already present. Non-array / empty → "". */
export function fmtHashtags(tags: unknown): string {
  if (!Array.isArray(tags)) return "";
  const parts: string[] = [];
  for (const tag of tags) {
    const s = String(tag).trim().replace(/^#+/, "");
    if (s) parts.push("#" + s);
  }
  return parts.join(" ");
}
