/**
 * Subtitle cue fitting — one-line invariant ([[project_subtitle_oneline_invariant]]).
 *
 * Faithful port of the Python burn path: compute_subtitle_max_chars
 * (core/composition/style.py) + split_subtitle (core/subtitle_ops.py). A cue
 * that would overflow the frame width is split into time-sequential sub-cues,
 * each ≤ max-chars — never visual wrap.
 *
 * max-chars is resolution-independent: available_px / glyph_px
 *   = (W·0.92) / (fontsizePct·H·ratio)
 *   = (W/H)·0.92 / (fontsizePct·ratio)
 * so it depends only on the output ASPECT (W/H), the font fraction (of frame
 * height — matching the canvas2d draw), and whether the text is CJK. Script is
 * auto-detected from the cue CONTENT, not a user flag
 * ([[feedback_wrap_from_content_not_flag]]).
 */

import type { SourceCue } from "./components/contract.js";

const SAFE_MARGIN = 0.92;
// Empirical glyph-width / fontsize ratios — the Python fallback when PIL can't
// measure (style.py::compute_subtitle_max_chars). CJK glyphs are ~square.
const RATIO_CJK = 1.0;
const RATIO_LATIN = 0.55;

// CJK ideographs + CJK/fullwidth punctuation.
const CJK_RE = /[　-〿㐀-䶿一-鿿豈-﫿＀-￯]/;
const CJK_BREAKS = /[，。？！；：、]/g;
const LATIN_BREAKS = /[.?!,;:]/g;

export function hasCJK(text: string): boolean {
  return CJK_RE.test(text);
}

/**
 * Max chars per line before a subtitle overflows, given the output aspect
 * (W/H), the font fraction (of frame height), and the script. Floor of 2.
 */
export function computeMaxChars(frameAspect: number, fontsizePct: number, isChinese: boolean): number {
  const ratio = isChinese ? RATIO_CJK : RATIO_LATIN;
  const glyph = Math.max(1e-6, fontsizePct * ratio);
  return Math.max(2, Math.floor((frameAspect * SAFE_MARGIN) / glyph));
}

/**
 * Split one cue to ≤ maxChars per piece, breaking at punctuation (and, for
 * latin, spaces), distributing the cue's time proportionally by char count.
 * Faithful to subtitle_ops.split_subtitle (time computed from the start to kill
 * float drift; last piece snapped to the original end).
 */
export function splitCue(cue: SourceCue, maxChars: number, isChinese: boolean): SourceCue[] {
  const content = cue.text.trim();
  if (content.length <= maxChars) return content ? [{ ...cue, text: content }] : [];
  const dur = cue.sourceEnd - cue.sourceStart;
  if (dur <= 0) return [{ ...cue, text: content }];

  const breakRe = isChinese ? CJK_BREAKS : LATIN_BREAKS;
  const breaks = [...content.matchAll(breakRe)].map((m) => m.index ?? 0);

  const out: SourceCue[] = [];
  const n = content.length;
  let charsSoFar = 0;
  let pos = 0;
  while (pos < n) {
    let split = pos + maxChars;
    if (split >= n) {
      split = n;
    } else {
      const cands = breaks.filter((b) => pos < b + 1 && b + 1 <= split).map((b) => b + 1);
      if (cands.length) {
        split = Math.max(...cands);
      } else if (!isChinese) {
        const lastSpace = content.lastIndexOf(" ", split - 1);
        if (lastSpace > pos) split = lastSpace + 1;
      }
    }
    const part = content.slice(pos, split).trim();
    const tStart = cue.sourceStart + (charsSoFar / n) * dur;
    charsSoFar += split - pos;
    const tEnd = cue.sourceStart + (charsSoFar / n) * dur;
    if (part) out.push({ sourceStart: tStart, sourceEnd: tEnd, text: part });
    pos = split;
  }
  if (out.length) out[out.length - 1]!.sourceEnd = cue.sourceEnd;
  return out.length ? out : [{ ...cue, text: content }];
}

/**
 * Fit a cue list to the frame: per cue, auto-detect script, compute its
 * max-chars, and split. The single entry point the subtitle component uses.
 */
export function fitCues(
  cues: readonly SourceCue[],
  fontsizePct: number,
  frameAspect: number,
): SourceCue[] {
  const out: SourceCue[] = [];
  for (const cue of cues) {
    const cjk = hasCJK(cue.text);
    out.push(...splitCue(cue, computeMaxChars(frameAspect, fontsizePct, cjk), cjk));
  }
  return out;
}
