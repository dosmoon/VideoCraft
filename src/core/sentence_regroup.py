"""Sentence-level regrouping of Whisper word-level output.

Whisper (any backend — faster-whisper / lemonfox / aistack / OpenAI API)
splits at trained timestamp-token boundaries that are partly acoustic.
Sentences routinely get bisected mid-clause, with punctuation stranded
on the next cue:

    30  ... is a very interesting
    31  one, very complex
    32  and constantly evolving.

This module re-groups words[] into sentence-level segments using the
pipeline stable-ts uses by default (port of its `isp_cm_sp_sg_sp_sl_cm`
chain — verified against jianfch/stable-ts README "Regrouping Words"
and m-bain/whisperX v3 alignment):

  1. split_by_terminal_punct ([. 。 ? ？ ! ！])
       — skipping "false terminators" (Mr. / U.S. / 3.14 / ...)
  2. split_by_gap (0.5s)
       — long silences are real boundaries even without punctuation
  3. split_by_soft_punct ([, ，]) when chunk has accumulated ≥50 chars
       — recovers clause-level breaks in run-on speech
  4. split_by_length (70 chars hard cap)
       — last-resort to keep sentences readable

Skips silently when words[] is missing or empty (some Whisper backends
without cross-attention exports — keeps the caller's original segments).
"""

from __future__ import annotations

import re


# ── Tunables (mirrors stable-ts defaults) ────────────────────────────────────

_TERMINAL_PUNCT = set(".!?。！？")
_SOFT_PUNCT     = set(",，")
_GAP_THRESHOLD_S = 0.5  # stable-ts default
_COMMA_MIN_CHARS = 50
_MAX_CHARS = 70


# ── False-terminator detection ───────────────────────────────────────────────
# Periods that end a token but are NOT sentence boundaries:
#   - decimals / version numbers:  3.14, v1.2
#   - common abbreviations:        Mr. Mrs. Dr. Prof. Sr. Jr. St. Rev. Hon.
#   - Latin abbreviations:         e.g. i.e. etc. vs. cf.
#   - dotted initialisms:          U.S. U.K. F.B.I.
#   - ellipses:                    ... (treat as soft pause, not full stop)
#   - followed by lowercase next word (heuristic: real sentences start uppercase)

_ABBR_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Rev|Hon|"
    r"e\.g|i\.e|etc|vs|cf|Inc|Ltd|Co|Corp|No|"
    r"U\.S|U\.K|U\.N)\.\s*$",
    re.IGNORECASE,
)
_DECIMAL_RE     = re.compile(r"\d\.\d")
_ELLIPSIS_RE    = re.compile(r"\.\.\.+\s*$")
_INITIALISM_RE  = re.compile(r"^[A-Za-z]\.(?:[A-Za-z]\.)+\s*$")


def _is_false_terminator(word_text: str, next_word_raw: str | None) -> bool:
    """True if a trailing '.' should NOT count as a sentence boundary."""
    stripped = word_text.rstrip()
    if not stripped.endswith("."):
        return False
    if _ELLIPSIS_RE.search(stripped):
        return True
    if _DECIMAL_RE.search(stripped):
        return True
    if _ABBR_RE.search(stripped):
        return True
    if _INITIALISM_RE.match(stripped):
        return True
    # If next word starts lowercase, this period probably wasn't a real stop.
    if next_word_raw:
        nxt = next_word_raw.lstrip()
        if nxt and nxt[0].islower():
            return True
    return False


# ── Pipeline steps ───────────────────────────────────────────────────────────

def _last_nonspace_char(s: str) -> str:
    s = s.rstrip()
    return s[-1] if s else ""


def _word_chars(w: dict) -> int:
    """Visible-char count of a word token (whitespace stripped)."""
    return len((w.get("word") or "").strip())


def _split_by_terminal_punct(words: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    buf: list[dict] = []
    for i, w in enumerate(words):
        buf.append(w)
        wt = w.get("word") or ""
        last = _last_nonspace_char(wt)
        if last not in _TERMINAL_PUNCT:
            continue
        # For '.', verify it isn't a false terminator.
        if last == ".":
            nxt = words[i + 1].get("word") if i + 1 < len(words) else None
            if _is_false_terminator(wt, nxt):
                continue
        out.append(buf)
        buf = []
    if buf:
        out.append(buf)
    return out


def _split_by_gap(chunk: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    buf: list[dict] = []
    for w in chunk:
        if buf:
            try:
                gap = float(w["start"]) - float(buf[-1]["end"])
            except (TypeError, KeyError, ValueError):
                gap = 0.0
            if gap > _GAP_THRESHOLD_S:
                out.append(buf)
                buf = []
        buf.append(w)
    if buf:
        out.append(buf)
    return out


def _split_by_soft_punct(chunk: list[dict]) -> list[list[dict]]:
    """Split at , / ， but only once the buffer has accumulated enough chars
    that a clause break is more useful than just hanging mid-air."""
    out: list[list[dict]] = []
    buf: list[dict] = []
    char_count = 0
    for w in chunk:
        buf.append(w)
        char_count += _word_chars(w)
        wt = w.get("word") or ""
        last = _last_nonspace_char(wt)
        if last in _SOFT_PUNCT and char_count >= _COMMA_MIN_CHARS:
            out.append(buf)
            buf = []
            char_count = 0
    if buf:
        out.append(buf)
    return out


def _split_by_length(chunk: list[dict]) -> list[list[dict]]:
    """Last-resort cap: never let a single segment exceed _MAX_CHARS visible
    characters. Splits between words, never inside a token."""
    out: list[list[dict]] = []
    buf: list[dict] = []
    char_count = 0
    for w in chunk:
        wc = _word_chars(w)
        if buf and char_count + wc > _MAX_CHARS:
            out.append(buf)
            buf = [w]
            char_count = wc
        else:
            buf.append(w)
            char_count += wc
    if buf:
        out.append(buf)
    return out


def _chain(chunks: list[list[dict]], step) -> list[list[dict]]:
    out: list[list[dict]] = []
    for c in chunks:
        out.extend(step(c))
    return out


def _chunk_to_segment(words: list[dict], seg_id: int) -> dict:
    text = "".join(w.get("word") or "" for w in words).strip()
    return {
        "id":    seg_id,
        "start": float(words[0]["start"]),
        "end":   float(words[-1]["end"]),
        "text":  text,
    }


# ── Segment-level fallback ───────────────────────────────────────────────────

# Used when words[] is empty (some Whisper backends — including OpenAI's
# segments-only mode, lemonfox in certain plans, aistack with backends
# that lack cross-attention exports). Works on whatever the provider
# already chose as segment boundaries, merging adjacent segments when
# the split looks like an acoustic mid-sentence break.

# segments[] honors the "sentence-level" contract — length-based line
# wrapping lives in the burn layer (post-translation), so the only job
# of this cap is to break runaway chains when a speaker rambles with
# no terminal punctuation for many cues. Natural English sentences in
# news/interview transcripts often hit 200-250 chars; 300 leaves room
# for those without catching pathological cases.
_SEG_MAX_CHARS = 300
_SEG_GAP_MERGE_S = 0.5  # merge when seg→seg gap is at most this


def _seg_should_merge(prev: dict, nxt: dict) -> bool:
    """True iff prev should absorb nxt because the boundary looks like a
    mid-sentence acoustic split rather than a real sentence break."""
    prev_text = (prev.get("text") or "").rstrip()
    if not prev_text:
        return False
    last = prev_text[-1]
    # Real terminator on the previous segment → keep separate.
    if last in _TERMINAL_PUNCT:
        nxt_first = (nxt.get("text") or "").lstrip()
        if last == "." and _is_false_terminator(
                prev_text.rsplit(None, 1)[-1] if prev_text.split() else prev_text,
                nxt_first):
            pass  # false terminator → fall through to merge
        else:
            return False
    # Tight time gap = same utterance.
    try:
        gap = float(nxt["start"]) - float(prev["end"])
    except (TypeError, KeyError, ValueError):
        gap = 0.0
    if gap > _SEG_GAP_MERGE_S:
        return False
    # Don't grow forever.
    combined = len(prev_text) + 1 + len((nxt.get("text") or "").strip())
    if combined > _SEG_MAX_CHARS:
        return False
    return True


def regroup_segments(segments: list[dict]) -> list[dict]:
    """Greedy segment-level merge for when word-level timing is missing.

    Walks segments in order, absorbing each next segment into the
    current one until the current's text ends in real terminal
    punctuation OR a gap appears OR the length cap is hit.
    """
    if not segments:
        return []
    out: list[dict] = []
    i = 0
    while i < len(segments):
        cur = dict(segments[i])  # shallow copy — we mutate text/end
        cur["text"] = (cur.get("text") or "").strip()
        j = i + 1
        while j < len(segments):
            nxt = segments[j]
            if not _seg_should_merge(cur, nxt):
                break
            nxt_text = (nxt.get("text") or "").strip()
            # Insert a space (Latin) or nothing (CJK) — easy heuristic:
            # if either side ends/starts in CJK range, no space needed.
            joiner = "" if _is_cjk_boundary(cur["text"], nxt_text) else " "
            cur["text"] = cur["text"] + joiner + nxt_text
            cur["end"] = nxt.get("end", cur["end"])
            j += 1
        cur["id"] = len(out) + 1
        out.append(cur)
        i = j
    return out


def _is_cjk_boundary(left: str, right: str) -> bool:
    """True when a CJK char sits on either side of the join — no space."""
    if not left or not right:
        return False
    def _cjk(ch: str) -> bool:
        cp = ord(ch)
        return (0x3040 <= cp <= 0x30FF        # kana
                or 0x3400 <= cp <= 0x9FFF     # CJK unified
                or 0xAC00 <= cp <= 0xD7AF)    # hangul
    return _cjk(left[-1]) or _cjk(right[0])


# ── Public entry ─────────────────────────────────────────────────────────────

def regroup_words(words: list[dict]) -> list[dict]:
    """Words[] → sentence-level segments[].

    Each input word is {start: float, end: float, word: str}; the `word`
    value typically includes Whisper's leading space (e.g. " interesting").
    Output segments preserve that spacing when concatenated.

    Returns [] when words is empty/None; caller should fall back to the
    provider's original segments[] in that case.
    """
    if not words:
        return []
    valid = [w for w in words
             if w.get("word") is not None
             and w.get("start") is not None
             and w.get("end") is not None]
    if not valid:
        return []

    chunks = _split_by_terminal_punct(valid)
    chunks = _chain(chunks, _split_by_gap)
    chunks = _chain(chunks, _split_by_soft_punct)
    chunks = _chain(chunks, _split_by_length)

    segments: list[dict] = []
    for i, c in enumerate(chunks, start=1):
        if not c:
            continue
        seg = _chunk_to_segment(c, i)
        if seg["text"]:
            segments.append(seg)
    return segments


# ── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                       errors="replace")

    # User's real example, simulated as word-level input.
    words = [
        # "By offering coverage for care at every step, the fertility journey is a very interesting"
        # then bisected, "one, very complex" "and constantly evolving."
        {"word": "By",         "start": 102.290, "end": 102.500},
        {"word": " offering",  "start": 102.500, "end": 103.000},
        {"word": " coverage",  "start": 103.000, "end": 103.600},
        {"word": " for",       "start": 103.600, "end": 103.800},
        {"word": " care",      "start": 103.800, "end": 104.100},
        {"word": " at",        "start": 104.100, "end": 104.250},
        {"word": " every",     "start": 104.250, "end": 104.600},
        {"word": " step,",     "start": 104.600, "end": 105.100},
        {"word": " the",       "start": 105.100, "end": 105.250},
        {"word": " fertility", "start": 105.250, "end": 105.900},
        {"word": " journey",   "start": 105.900, "end": 106.400},
        {"word": " is",        "start": 106.400, "end": 106.600},
        {"word": " a",         "start": 106.600, "end": 106.700},
        {"word": " very",      "start": 106.700, "end": 107.000},
        {"word": " interesting","start": 107.000, "end": 108.370},
        # Whisper bisected here. No gap (108.370 → 108.370).
        {"word": " one,",      "start": 108.370, "end": 108.900},
        {"word": " very",      "start": 108.900, "end": 109.250},
        {"word": " complex",   "start": 109.250, "end": 110.210},
        # Bisected again, also no gap.
        {"word": " and",       "start": 110.210, "end": 110.450},
        {"word": " constantly","start": 110.450, "end": 111.100},
        {"word": " evolving.", "start": 111.100, "end": 112.800},
    ]

    segs = regroup_words(words)
    print(f"[word-level] input words: {len(words)}")
    print(f"[word-level] output segments: {len(segs)}")
    for s in segs:
        print(f"  {s['start']:.3f} → {s['end']:.3f}  {s['text']!r}")
    assert len(segs) >= 1
    print("\nsmoke (word-level) OK")

    # ── Segment-level fallback test (no words[] available) ──
    # User's real case: cue 648 "You and China are the only two countries"
    #                   cue 649 "in the world that could take it out."
    # No terminal punct on prev, gap = 0 → should merge.
    src_segs = [
        {"id": 1, "start": 2293.01, "end": 2296.01,
         "text": "You and China are the only two countries"},
        {"id": 2, "start": 2296.01, "end": 2298.01,
         "text": "in the world that could take it out."},
        {"id": 3, "start": 2299.50, "end": 2302.00,
         "text": "Next sentence after a real gap."},
    ]
    merged = regroup_segments(src_segs)
    print(f"\n[segment-level] input: {len(src_segs)}, output: {len(merged)}")
    for s in merged:
        print(f"  {s['start']:.3f} → {s['end']:.3f}  {s['text']!r}")
    assert len(merged) == 2  # first two merged, third kept (1.5s gap > 0.5)
    assert "countries in the world" in merged[0]["text"]
    print("smoke (segment-level) OK")

    # False-terminator test (only words that *end* with '.' enter the check):
    assert _is_false_terminator("Mr.", "Smith") is True
    assert _is_false_terminator("U.S.", "policy") is True
    assert _is_false_terminator("e.g.", "this") is True
    assert _is_false_terminator("...", "next") is True   # ellipsis
    assert _is_false_terminator("end.", "Next") is False  # real terminator
    assert _is_false_terminator("end.", "next") is True   # lowercase follower
    assert _is_false_terminator("hello", "world") is False  # not '.'-ending
    print("false-terminator OK")
