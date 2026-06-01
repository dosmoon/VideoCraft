/**
 * Clip derivative publish.md + index.md templates (ADR-0008 TS port of
 * `src/creations/clip/publish.py`).
 *
 *   - renderClipPublish(): per-clip clip_NNN.md — the Caption block (title +
 *     transcript + hashtags) sized for X / TikTok.
 *   - renderClipIndex(): per-instance index.md — table mapping clip_001..N to
 *     titles + scores + per-clip publish.md.
 *   - collectClipSidecars(): scan an instance dir for clip_*.json (via Fs).
 *
 * Content localizes to the source video language (langIso), not the UI.
 */

import type { Fs } from "../../renderer/ipc/fs";
import { fmtDur, fmtHashtags, t } from "../shared/markdownFmt";

type Sidecar = Record<string, unknown>;

const str = (v: unknown): string => (v == null ? "" : String(v)).trim();

export function renderClipPublish(args: {
  projectTitle: string | null;
  sidecar: Sidecar;
  langIso: string;
}): string {
  const { sidecar: s, langIso: lang } = args;
  const title = str(s["title"]) || t(lang, "（无标题）", "(no title)");
  const hook = str(s["hook"]);
  const outro = str(s["outro"]);
  const transcript = str(s["transcript"]);
  const why = str(s["why_viral"]);
  const dur = Number(s["duration_sec"]) || 0;
  const score = s["score"];
  const startSec = s["start_sec"];
  const endSec = s["end_sec"];
  const outIdx = s["output_index"];
  const hashtagsLine = fmtHashtags(s["hashtags"]);

  const metaBits: string[] = [t(lang, `时长 ${fmtDur(dur)}`, `Duration ${fmtDur(dur)}`)];
  if (score != null) metaBits.push(t(lang, `评分 ${score}/10`, `Score ${score}/10`));

  const lines: string[] = [`# ${title}`, "", "**" + metaBits.join(" · ") + "**", ""];

  if (hook) {
    lines.push("## " + t(lang, "钩子文案", "Hook"), "", hook, "");
  }

  lines.push("## " + t(lang, "发布稿（一键复制到 X / TikTok）", "Caption (copy to X / TikTok)"), "");
  lines.push("```", title);
  if (transcript) lines.push("", transcript);
  if (hashtagsLine) lines.push("", hashtagsLine);
  lines.push("```", "");

  if (outro) lines.push("## " + t(lang, "结尾 CTA", "Outro"), "", outro, "");
  if (why) lines.push("## " + t(lang, "为什么这段会火", "Why this clip"), "", why, "");

  // Footer with provenance.
  lines.push("---", "");
  const srcBits: string[] = [];
  if (outIdx != null) srcBits.push(`clip_${String(Math.trunc(Number(outIdx))).padStart(3, "0")}.mp4`);
  if (startSec != null && endSec != null) {
    srcBits.push(`${fmtDur(Number(startSec))} – ${fmtDur(Number(endSec))}`);
  }
  if (args.projectTitle) srcBits.push(args.projectTitle);
  if (srcBits.length) lines.push(t(lang, "来源", "Source") + ": " + srcBits.join(" · "));

  return lines.join("\n").replace(/\s+$/, "") + "\n";
}

export function renderClipIndex(args: {
  projectTitle: string | null;
  instanceName: string;
  sidecars: Sidecar[];
  renderedAt: string | null;
  langIso: string;
}): string {
  const lang = args.langIso;
  const title = (args.projectTitle || "").trim() || t(lang, "（无标题）", "(no title)");

  const lines: string[] = [`# ${title} — Clips (${args.instanceName})`, ""];
  let countLine = t(lang, `共 ${args.sidecars.length} 个切片`, `${args.sidecars.length} clips`);
  if (args.renderedAt) {
    countLine += " · " + t(lang, `渲染于 ${args.renderedAt}`, `rendered ${args.renderedAt}`);
  }
  lines.push(`> ${countLine}`, "");

  if (args.sidecars.length === 0) {
    lines.push(t(lang, "（暂无切片）", "(no clips yet)"));
    return lines.join("\n").replace(/\s+$/, "") + "\n";
  }

  const sidecars = [...args.sidecars].sort(
    (a, b) => (Number(a["output_index"]) || 0) - (Number(b["output_index"]) || 0),
  );

  lines.push(
    t(
      lang,
      "| #   | 标题                            | 时长   | 评分 | 文件 | 发布稿 |\n" +
        "|-----|--------------------------------|--------|------|------|--------|",
      "| #   | Title                          | Dur    | Score| File | Publish |\n" +
        "|-----|--------------------------------|--------|------|------|---------|",
    ),
  );

  for (const sc of sidecars) {
    const idx = Math.trunc(Number(sc["output_index"]) || 0);
    const ttl = str(sc["title"]).replace(/\|/g, "\\|") || "—";
    const dur = fmtDur(Number(sc["duration_sec"]) || 0);
    const score = sc["score"];
    const scoreS = score == null ? "—" : String(score);
    // `filename` records the hook-bearing name picked at render time. Without it
    // the sidecar is broken (pre-current render code) — show a dash.
    const fname = str(sc["filename"]);
    let fileCell = "—";
    let mdCell = "—";
    if (fname) {
      const md = fname.replace(/\.[^.]*$/, "") + ".md";
      fileCell = `[${fname}](${fname})`;
      mdCell = `[${md}](${md})`;
    }
    lines.push(`| ${String(idx).padStart(3, "0")} | ${ttl} | ${dur} | ${scoreS} | ${fileCell} | ${mdCell} |`);
  }

  return lines.join("\n").replace(/\s+$/, "") + "\n";
}

/** Read every clip_*.json in an instance dir (via Fs), sorted by output_index.
 *  Errors on individual files are swallowed (best-effort over what loaded). */
export async function collectClipSidecars(fs: Fs, instanceDir: string): Promise<Sidecar[]> {
  let entries: { name: string; isDir: boolean }[];
  try {
    entries = await fs.list(instanceDir);
  } catch {
    return [];
  }
  const out: Sidecar[] = [];
  for (const e of entries) {
    if (!e.name.startsWith("clip_") || !e.name.endsWith(".json")) continue;
    try {
      const data = await fs.readJson<Sidecar>(`${instanceDir}/${e.name}`);
      if (data && typeof data === "object") out.push(data);
    } catch {
      // skip malformed
    }
  }
  out.sort((a, b) => (Number(a["output_index"]) || 0) - (Number(b["output_index"]) || 0));
  return out;
}
