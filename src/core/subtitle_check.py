"""Subtitle quality checks (P4.4.5).

Pure-logic structural + semantic checks against an SRT file. UI layer
calls check_srt() to surface a count of issues in the sidebar and
optionally a detail dialog for inspection / cleanup.

Three check families:

  Structural — parse / count / timing / empty content / cue-count
               mismatch vs. reference.

  Format-residue — model tokens that leak into translated text
                   (`【N】` markers, `<|im_end|>`, leading "assistant:",
                   etc). These are auto-fixable via clean_residue().

  Semantic-lite — language purity by Unicode block ratio. Cheap (<1ms),
                  flags zh.srt that's actually English or ja.srt that
                  came back English-only. AI-based quality scoring is
                  out of scope here — that's a separate feature.

No network, no AI. Runs in milliseconds even for hour-long SRTs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import srt as _srt


def _read_srt(path: str) -> str:
    """Lazy proxy to core.subtitle_ops.read_srt so this module is importable
    when run directly (python src/core/subtitle_check.py) without sys.path
    setup."""
    from core.subtitle_ops import read_srt
    return read_srt(path)


# ── Issue categories ─────────────────────────────────────────────────────────

# Severities (legacy axis — kept for color/icon in the detail dialog)
SEV_ERROR = "error"      # broken / unusable
SEV_WARNING = "warning"  # suspicious / likely broken
SEV_INFO = "info"        # noteworthy but acceptable

# Severity classes drive sidebar UX:
#   HARD     — blocks burn or makes SRT meaningless. Needs human intervention.
#   FIXABLE  — auto-fixable via apply_auto_fixes (format residue today).
#   ADVISORY — quality hints, doesn't block anything. Hidden in sidebar by
#              default; only shown inside the details dialog.
CLASS_HARD = "hard"
CLASS_FIXABLE = "fixable"
CLASS_ADVISORY = "advisory"

# Categories
CAT_EMPTY = "empty"
CAT_TIMING = "timing"
CAT_OVERLAP = "overlap"
CAT_COUNT_MISMATCH = "count_mismatch"
CAT_LENGTH_RATIO = "length_ratio"
CAT_FORMAT_RESIDUE = "format_residue"
CAT_LANG_PURITY = "lang_purity"
CAT_DUPLICATE = "duplicate"
CAT_PARSE = "parse"


@dataclass
class SubtitleIssue:
    cue_index: int          # 1-based per SRT convention; 0 = file-level issue
    category: str
    severity: str
    message: str
    auto_fixable: bool = False
    severity_class: str = CLASS_ADVISORY  # filled by check_srt()


@dataclass
class CheckResult:
    srt_path: str
    cue_count: int = 0
    issues: list[SubtitleIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == SEV_ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == SEV_WARNING for i in self.issues)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def hard_count(self) -> int:
        return sum(1 for i in self.issues if i.severity_class == CLASS_HARD)

    @property
    def fixable_count(self) -> int:
        return sum(1 for i in self.issues if i.severity_class == CLASS_FIXABLE)

    @property
    def advisory_count(self) -> int:
        return sum(1 for i in self.issues if i.severity_class == CLASS_ADVISORY)

    def by_category(self, category: str) -> list[SubtitleIssue]:
        return [i for i in self.issues if i.category == category]

    def by_class(self, cls: str) -> list[SubtitleIssue]:
        return [i for i in self.issues if i.severity_class == cls]


def _classify(category: str, severity: str, auto_fixable: bool) -> str:
    """Map (category, severity, auto_fixable) → severity_class.

    Rules:
      - auto_fixable wins → FIXABLE (one-click cleanup path)
      - parse / empty / timing / count_mismatch / lang_purity → HARD
        (broken SRT or wrong-language file — blocks any sensible use)
      - everything else → ADVISORY (length_ratio / duplicate / overlap)
    """
    if auto_fixable:
        return CLASS_FIXABLE
    if category in (CAT_PARSE, CAT_EMPTY, CAT_TIMING,
                    CAT_COUNT_MISMATCH, CAT_LANG_PURITY):
        return CLASS_HARD
    return CLASS_ADVISORY


# ── Format-residue patterns ──────────────────────────────────────────────────
# Captures common artifacts from LLM translation that leak into SRT text.
# Each entry: (compiled regex, message_template, auto_fixable)

_FORMAT_RESIDUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Batch markers from translate prompt: 【1】, 【123】 — always leaked when
    # model copies the marker into output.
    (re.compile(r"【\s*\d+\s*】"), "残留批次标记 【N】"),
    # Chat / role tokens from various models.
    (re.compile(r"<\|im_(?:start|end|sep)\|>", re.IGNORECASE), "残留模型 token"),
    (re.compile(r"<\|endoftext\|>", re.IGNORECASE), "残留模型 token"),
    # Raw role labels at line start.
    (re.compile(r"^(?:assistant|user|system)\s*:\s*", re.IGNORECASE),
     "残留角色标签"),
    # JSON wrapper leaks: `{"text": "...", "index": ...}` style.
    (re.compile(r"^\s*\{[^{}]*\bindex\b[^{}]*\btext\b[^{}]*\}\s*$"),
     "残留 JSON 包装"),
    # Triple-backtick code fences.
    (re.compile(r"^\s*```"), "残留代码块标记"),
]


def clean_residue(text: str) -> str:
    """Strip all known format-residue patterns from text. Returns cleaned text.

    Used by both detection (flag matches) and the [清理可修复项] button.
    """
    for pat, _ in _FORMAT_RESIDUE_PATTERNS:
        text = pat.sub("", text)
    # Collapse runs of whitespace introduced by stripping and trim ends.
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text


# ── Language-purity ranges ───────────────────────────────────────────────────
# Per ISO code, the set of Unicode codepoint ranges considered "native".
# We compute (native_count / non_space_letter_count) as a purity ratio.

_RANGE_CJK = [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x20000, 0x2A6DF)]
_RANGE_HIRAGANA_KATAKANA = [(0x3040, 0x309F), (0x30A0, 0x30FF)]
_RANGE_HANGUL = [(0xAC00, 0xD7AF), (0x1100, 0x11FF)]
_RANGE_LATIN = [(0x0041, 0x005A), (0x0061, 0x007A),
                (0x00C0, 0x00FF)]  # Basic Latin letters + Latin-1 letters

_LANG_NATIVE_RANGES: dict[str, list[tuple[int, int]]] = {
    "zh":  _RANGE_CJK,
    "ja":  _RANGE_CJK + _RANGE_HIRAGANA_KATAKANA,
    "ko":  _RANGE_HANGUL + _RANGE_CJK,
    "en":  _RANGE_LATIN,
    "fr":  _RANGE_LATIN,
    "de":  _RANGE_LATIN,
    "es":  _RANGE_LATIN,
    "pt":  _RANGE_LATIN,
    "it":  _RANGE_LATIN,
    "ru":  [(0x0400, 0x04FF)],   # Cyrillic
    "ar":  [(0x0600, 0x06FF), (0x0750, 0x077F)],
    "hi":  [(0x0900, 0x097F)],
    "th":  [(0x0E00, 0x0E7F)],
}

# Purity floors (fraction of letter chars that must be in native ranges).
# Set lenient so loanwords / proper nouns don't trigger false alarms.
_PURITY_FLOOR_DEFAULT = 0.5


def _in_ranges(cp: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def _purity_ratio(text: str, ranges: list[tuple[int, int]]) -> tuple[float, int]:
    """Returns (native_ratio, total_letter_chars). Spaces / punctuation /
    digits don't count toward either side."""
    native = 0
    total = 0
    for ch in text:
        cp = ord(ch)
        if ch.isalpha() or _in_ranges(cp, _RANGE_CJK + _RANGE_HIRAGANA_KATAKANA
                                          + _RANGE_HANGUL):
            total += 1
            if _in_ranges(cp, ranges):
                native += 1
    if total == 0:
        return (1.0, 0)
    return (native / total, total)


# ── Main entry ───────────────────────────────────────────────────────────────

def check_srt(
    srt_path: str,
    *,
    expected_lang_iso: str | None = None,
    reference_srt_path: str | None = None,
    length_ratio_max: float = 5.0,
    length_ratio_min: float = 0.2,
    duplicate_run_threshold: int = 3,
    overlap_ms_tolerance: int = 200,
) -> CheckResult:
    """Run all checks against an SRT file.

    Args:
        srt_path:            Target SRT to inspect.
        expected_lang_iso:   ISO code; enables language-purity check.
        reference_srt_path:  Optional source SRT for cue-count + length-ratio
                             comparisons (e.g. en.srt as reference for zh.srt).
        length_ratio_max:    Flag cue when translated/source length exceeds this.
        length_ratio_min:    Flag cue when translated/source length below this.
        duplicate_run_threshold: Flag when ≥N consecutive identical-text cues.
        overlap_ms_tolerance: Time overlap ≤ this is treated as info, not warning.

    Returns:
        CheckResult with cue_count + issues list.
    """
    result = CheckResult(srt_path=srt_path)

    # Parse target
    try:
        raw = _read_srt(srt_path)
        cues = list(_srt.parse(raw))
    except FileNotFoundError:
        result.issues.append(SubtitleIssue(
            0, CAT_PARSE, SEV_ERROR, f"文件不存在: {srt_path}"))
        return result
    except Exception as e:
        result.issues.append(SubtitleIssue(
            0, CAT_PARSE, SEV_ERROR, f"SRT 解析失败: {e}"))
        return result

    result.cue_count = len(cues)

    # Parse reference (if any)
    ref_cues: list = []
    if reference_srt_path:
        try:
            ref_cues = list(_srt.parse(_read_srt(reference_srt_path)))
        except (FileNotFoundError, Exception):
            ref_cues = []

    # ── Cue-count mismatch (file-level) ──
    if ref_cues and len(ref_cues) != len(cues):
        result.issues.append(SubtitleIssue(
            0, CAT_COUNT_MISMATCH, SEV_ERROR,
            f"cue 数量不一致: 源 {len(ref_cues)} vs 目标 {len(cues)}",
        ))

    # ── Per-cue scans ──
    prev_end_ms = -1
    last_text = None
    dup_run = 0

    for idx, cue in enumerate(cues, start=1):
        text = (cue.content or "").strip()
        start_ms = int(cue.start.total_seconds() * 1000)
        end_ms = int(cue.end.total_seconds() * 1000)

        # Empty content
        if not text:
            result.issues.append(SubtitleIssue(
                idx, CAT_EMPTY, SEV_ERROR, "内容为空", auto_fixable=False))

        # Timing invalid
        if end_ms <= start_ms:
            result.issues.append(SubtitleIssue(
                idx, CAT_TIMING, SEV_ERROR,
                f"时间无效: {start_ms}ms → {end_ms}ms (结束 ≤ 开始)"))
        if start_ms < 0:
            result.issues.append(SubtitleIssue(
                idx, CAT_TIMING, SEV_ERROR,
                f"开始时间为负: {start_ms}ms"))

        # Overlap with previous
        if prev_end_ms >= 0 and start_ms < prev_end_ms:
            overlap = prev_end_ms - start_ms
            sev = SEV_WARNING if overlap > overlap_ms_tolerance else SEV_INFO
            result.issues.append(SubtitleIssue(
                idx, CAT_OVERLAP, sev,
                f"与上一行重叠 {overlap}ms"))

        # Format residue
        for pat, msg in _FORMAT_RESIDUE_PATTERNS:
            if pat.search(text):
                result.issues.append(SubtitleIssue(
                    idx, CAT_FORMAT_RESIDUE, SEV_WARNING, msg,
                    auto_fixable=True))
                break  # one residue flag per cue is enough

        # Length ratio (vs reference)
        if ref_cues and idx <= len(ref_cues):
            ref_text = (ref_cues[idx - 1].content or "").strip()
            ref_len = max(1, len(ref_text))
            ratio = len(text) / ref_len
            if ratio > length_ratio_max:
                result.issues.append(SubtitleIssue(
                    idx, CAT_LENGTH_RATIO, SEV_WARNING,
                    f"长度异常: 译文 {ratio:.1f}× 原文 ({len(text)}/{ref_len})"))
            elif ratio < length_ratio_min and len(ref_text) > 5:
                # Skip very short source cues — ratios become noisy.
                result.issues.append(SubtitleIssue(
                    idx, CAT_LENGTH_RATIO, SEV_WARNING,
                    f"长度异常: 译文 {ratio:.1f}× 原文 ({len(text)}/{ref_len})"))

        # Duplicate run detection
        if text and text == last_text:
            dup_run += 1
            if dup_run + 1 == duplicate_run_threshold:
                # Flag the start of the run (idx - threshold + 1)
                start_idx = idx - duplicate_run_threshold + 2
                result.issues.append(SubtitleIssue(
                    start_idx, CAT_DUPLICATE, SEV_WARNING,
                    f"连续 {duplicate_run_threshold}+ 行内容重复 (模型可能复读)"))
        else:
            dup_run = 0
        last_text = text

        prev_end_ms = end_ms

    # ── Language purity (file-level) ──
    if expected_lang_iso:
        ranges = _LANG_NATIVE_RANGES.get(expected_lang_iso)
        if ranges:
            all_text = "\n".join((c.content or "") for c in cues)
            ratio, total = _purity_ratio(all_text, ranges)
            if total >= 20 and ratio < _PURITY_FLOOR_DEFAULT:
                result.issues.append(SubtitleIssue(
                    0, CAT_LANG_PURITY, SEV_ERROR,
                    f"目标语言纯度不足: {ratio:.0%} 字符属于 "
                    f"{expected_lang_iso} 字符集 (期望 ≥ {_PURITY_FLOOR_DEFAULT:.0%})"))

    # Classify every issue in one pass.
    for issue in result.issues:
        issue.severity_class = _classify(
            issue.category, issue.severity, issue.auto_fixable)

    return result


# ── Auto-fix entry ───────────────────────────────────────────────────────────

def apply_auto_fixes(srt_path: str, *, in_place: bool = True) -> dict:
    """Apply clean_residue to every cue and write back.

    Returns:
        {"cues_fixed": int, "output_path": str}
    """
    raw = _read_srt(srt_path)
    cues = list(_srt.parse(raw))
    fixed = 0
    for cue in cues:
        before = cue.content or ""
        after = clean_residue(before)
        if after != before:
            cue.content = after
            fixed += 1
    out_path = srt_path if in_place else srt_path + ".fixed.srt"
    if fixed:
        composed = _srt.compose(cues)
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(composed)
    return {"cues_fixed": fixed, "output_path": out_path}


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # When run directly, make src/ importable + force UTF-8 stdout on Windows.
    import sys, io, tempfile
    _src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _src not in sys.path:
        sys.path.insert(0, _src)
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")

    bad_srt = (
        "1\n00:00:00,000 --> 00:00:02,000\n【1】Hello world\n\n"
        "2\n00:00:02,000 --> 00:00:01,000\nbroken timing\n\n"
        "3\n00:00:03,000 --> 00:00:05,000\n\n\n"
        "4\n00:00:05,000 --> 00:00:07,000\nduplicate text\n\n"
        "5\n00:00:07,000 --> 00:00:09,000\nduplicate text\n\n"
        "6\n00:00:09,000 --> 00:00:11,000\nduplicate text\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".srt", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(bad_srt)
        tmp_path = tf.name

    try:
        result = check_srt(tmp_path, expected_lang_iso="zh")
        print(f"cue_count: {result.cue_count}")
        print(f"issues: {len(result.issues)}")
        for issue in result.issues:
            print(f"  #{issue.cue_index} [{issue.category}] "
                  f"{issue.severity}: {issue.message}")

        cats = {i.category for i in result.issues}
        assert CAT_FORMAT_RESIDUE in cats
        assert CAT_TIMING in cats
        assert CAT_EMPTY in cats
        assert CAT_DUPLICATE in cats
        assert CAT_LANG_PURITY in cats

        fixed = apply_auto_fixes(tmp_path)
        print(f"\nauto-fixed {fixed['cues_fixed']} cues")
        result2 = check_srt(tmp_path, expected_lang_iso="zh")
        assert not result2.by_category(CAT_FORMAT_RESIDUE)
        print("after fix: format_residue cleared")

        print("\nsubtitle_check smoke OK")
    finally:
        os.remove(tmp_path)
