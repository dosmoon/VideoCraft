/**
 * Minimal SRT parser — the host parses subtitles and feeds cues to the pure
 * composition layer (components stay I/O-free). Returns source-time cues
 * ({sourceStart, sourceEnd, text}) ready for CompileContext.cues.
 */

import type { SourceCue } from "@composition/components/index.js";

const TS = /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/;

function parseTimestamp(s: string): number {
  const m = s.match(TS);
  if (!m) return 0;
  return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4]) / 1000;
}

export function parseSrt(content: string): SourceCue[] {
  const cues: SourceCue[] = [];
  // Blocks are separated by a blank line; tolerate CRLF + stray whitespace.
  const blocks = content.replace(/\r\n/g, "\n").split(/\n\s*\n/);
  for (const block of blocks) {
    const lines = block.split("\n");
    const tIdx = lines.findIndex((l) => l.includes("-->"));
    if (tIdx === -1) continue;
    const m = lines[tIdx]!.match(
      /(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})/,
    );
    if (!m) continue;
    const text = lines
      .slice(tIdx + 1)
      .join("\n")
      .trim();
    if (!text) continue;
    cues.push({
      sourceStart: parseTimestamp(m[1]!),
      sourceEnd: parseTimestamp(m[2]!),
      text,
    });
  }
  return cues;
}
