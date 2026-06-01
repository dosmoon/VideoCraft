/**
 * News-desk publish.md template (ADR-0008 TS port of
 * `src/creations/news_desk/publish.py`).
 *
 * Consumes the bound material's context.json (AI-verified 15-field record) +
 * the snapshotted chapter schedule + adapted SRT references. Empty fields are
 * omitted; with no AI-filled context it degrades to a chapters-only doc. Content
 * localizes to the source video language (langIso), not the UI.
 *
 * The pure renderer takes parsed transcript cues (the orchestrator reads + parses
 * the snapshot SRT) so this stays I/O-free.
 */

import { t } from "../shared/markdownFmt";

export interface PublishChapter {
  start?: string;
  end?: string;
  start_sec?: number;
  end_sec?: number;
  title?: string;
  refined?: string;
  key_points?: unknown[];
}
export interface TranscriptCue {
  startSec: number;
  text: string;
}

const s = (v: unknown): string => (v == null ? "" : String(v)).trim();

export function renderNewsDeskPublish(args: {
  projectTitle: string | null;
  sourceUrl: string | null;
  context: Record<string, unknown>;
  chapters: PublishChapter[];
  adaptedSrts: string[];
  renderedAt: string;
  langIso: string;
  transcriptCues?: TranscriptCue[];
  candidateTitles?: string[];
}): string {
  const { context: ctx, langIso: lang } = args;
  const title = s(ctx["episode_topic"]) || s(args.projectTitle) || t(lang, "（无标题）", "(no title)");

  const lines: string[] = [`# ${title}`, ""];
  if (args.sourceUrl) lines.push(`> Source: ${args.sourceUrl}`);
  lines.push(`> Rendered: ${args.renderedAt}`, "");

  const titles = (args.candidateTitles ?? []).map(s).filter(Boolean);
  if (titles.length) {
    lines.push("## " + t(lang, "候选标题", "Candidate Titles"), "");
    for (const tt of titles) lines.push(`- ${tt}`);
    lines.push("");
  }

  const metaPairs: [string, string][] = [];
  const add = (zh: string, en: string, value: unknown) => {
    const v = s(value);
    if (v) metaPairs.push([t(lang, zh, en), v]);
  };
  add("主讲人", "Host", ctx["host"]);
  add("身份", "Bio", ctx["host_bio"]);
  add("所属机构", "Affiliation", ctx["host_affiliation"]);
  add("嘉宾", "Guests", ctx["guests"]);
  add("事件日期", "Date", ctx["event_date"]);
  add("事件时间", "Time", ctx["event_time"]);
  add("事件地点", "Location", ctx["event_location"]);
  add("节目类型", "Show type", ctx["show_type"]);
  if (metaPairs.length) {
    lines.push("## " + t(lang, "节目概况", "Episode Info"), "");
    for (const [label, value] of metaPairs) lines.push(`- **${label}**: ${value}`);
    lines.push("");
  }

  const summary = s(ctx["event_summary"]);
  const keyPoints = s(ctx["key_points"]);
  const background = s(ctx["background"]);
  if (summary || keyPoints || background) {
    lines.push("## " + t(lang, "YouTube 描述", "YouTube Description"), "", "```");
    if (summary) lines.push(summary, "");
    if (keyPoints) {
      lines.push(t(lang, "核心要点：", "Key points:"));
      for (const kp of keyPoints.split(/\r?\n/)) {
        const k = kp.trim().replace(/^[-•·]+/, "").trim();
        if (k) lines.push(`- ${k}`);
      }
      lines.push("");
    }
    if (background) lines.push(t(lang, "背景：", "Background:"), background, "");
    lines.push("```", "");
  }

  lines.push("## " + t(lang, "章节", "Chapters"), "");
  if (args.chapters.length) {
    lines.push("```");
    for (const ch of args.chapters) {
      const start = s(ch.start);
      if (!start) continue;
      lines.push(`${start} ${s(ch.title)}`.trimEnd());
    }
    lines.push("```");
  } else {
    lines.push(t(lang, "（无章节）", "(no chapters)"));
  }
  lines.push("");

  const notes = s(ctx["notes"]);
  if (notes) lines.push("## " + t(lang, "制作备注", "Production Notes"), "", notes, "");

  if (args.adaptedSrts.length) {
    lines.push("## " + t(lang, "字幕文件", "Adapted SRTs"), "");
    for (const name of args.adaptedSrts) lines.push(`- \`${name}\``);
    lines.push("");
  }

  if (args.chapters.length && args.transcriptCues && args.transcriptCues.length) {
    const detail = buildChapterDetail(args.chapters, args.transcriptCues, lang);
    if (detail.length) {
      lines.push("---", "");
      lines.push(...detail);
    }
  }

  return lines.join("\n").replace(/\s+$/, "") + "\n";
}

function buildChapterDetail(chapters: PublishChapter[], cues: TranscriptCue[], lang: string): string[] {
  // Bucket cues into chapters by start time.
  const buckets: string[][] = chapters.map(() => []);
  for (const cue of cues) {
    const text = cue.text.replace(/\n/g, " ").trim();
    if (!text) continue;
    for (let i = 0; i < chapters.length; i++) {
      const ch = chapters[i]!;
      const start = Number(ch.start_sec ?? 0);
      const end = Number(ch.end_sec ?? 0);
      const inRange = end > start ? cue.startSec >= start && cue.startSec < end : cue.startSec >= start;
      if (inRange) {
        buckets[i]!.push(text);
        break;
      }
    }
  }

  const out: string[] = [`## ${t(lang, "章节详情", "Chapter Details")}`, ""];
  chapters.forEach((ch, i) => {
    const start = s(ch.start);
    const end = s(ch.end);
    const timeline = end ? `${start}–${end}` : start;
    out.push(`### ${timeline}  ${s(ch.title)}`.trimEnd(), "");

    const refined = s(ch.refined);
    if (refined) out.push(`**${t(lang, "摘要", "Summary")}**: ${refined}`, "");
    const kps = (ch.key_points ?? []).map(s).filter(Boolean);
    if (kps.length) {
      out.push(`**${t(lang, "要点", "Key points")}**:`);
      for (const p of kps) out.push(`- ${p}`);
      out.push("");
    }
    out.push(`**${t(lang, "文字稿", "Transcript")}**:`, "");
    out.push(buckets[i]!.length ? buckets[i]!.join(" ") : t(lang, "（此章节内无字幕）", "(no subtitle in this chapter)"));
    out.push("");
    if (i < chapters.length - 1) out.push("---", "");
  });
  return out;
}
