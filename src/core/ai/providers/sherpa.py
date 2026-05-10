"""sherpa-onnx provider — in-process Whisper ASR.

Part of VideoCraft's "embedded AI" tier (see
docs/draft/tech-selection-embedded-ai.md): runs Whisper-small int8 fully
in-process on CPU. No Docker, no network. Model files live under
`<repo>/user_data/models/sherpa/whisper-small/` via core.paths.

Returns the same verbose_json dict shape as the aistack and lemonfox
providers, so router.py / core.asr / translate_srt can consume it
unchanged:

    {language, duration, text, segments[], words[]}

Chunking: Whisper's encoder consumes a fixed 30 s mel spectrogram, so
long audio MUST be split or only the first 30 s gets transcribed. We
prefer silero-VAD-aligned chunking (cuts at silence, no mid-word
clipping) when `<models>/sherpa/silero-vad/silero_vad.onnx` is on disk;
fall back to fixed 28 s windows otherwise. The VAD model is
downloadable via the Model Manager but never required.

`words[]` is ALWAYS empty for the standard int8 export — the
cross-attention outputs needed for word-level timestamps are not in the
published model. Sentence-level `segments[]` works. See
`feedback_asr_no_client_cue_sizing` memo for why this is acceptable.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Callable

import numpy as np

from core.ai.errors import AIError, Kind
from core import gpu as _gpu
from core.paths import cache_subdir

# Set up NVIDIA DLL search path before sherpa_onnx's C++ side tries to load
# CUDAExecutionProvider. No-op when CUDA wheels aren't installed.
_gpu.ensure_cuda_dlls()


EventCallback = Callable[..., None]

DEFAULT_MODEL_NAME = "whisper-small"
_SAMPLE_RATE = 16000

# Whisper's encoder consumes a fixed 30-second mel spectrogram (3000
# frames). Longer audio MUST be chunked or only the first 30 s gets
# transcribed silently. We prefer silero-VAD-aligned chunking (cuts at
# silence, no mid-word clipping) and fall back to fixed-window chunks
# only when the VAD model isn't installed.
_WHISPER_CHUNK_SEC = 28.0
# silero-vad model lives next to the Whisper bundle in <models>/sherpa/
# (per the model-manager catalog). Capped at 20 s per segment so it
# stays well under Whisper's 30 s ceiling even when speech is dense.
_VAD_MAX_SPEECH_SEC = 20.0
_VAD_WINDOW_SAMPLES = 512  # silero's native window size at 16 kHz

# After VAD finds speech regions, we pack adjacent regions back into
# ≤_WHISPER_CHUNK_SEC slices of the ORIGINAL audio (real silences kept
# in place). Reason: Whisper's encoder always processes a fixed 30 s
# mel spectrogram regardless of input duration, so 67 short chunks pay
# 67 × full-encoder cost. Packing into ~14 super-chunks cuts encoder
# passes proportionally.
#
# Internal-gap cap: don't pack across silences longer than this — long
# silence inside one Whisper input encourages hallucinated timestamps.
_VAD_PACK_MAX_GAP_SEC = 2.5

# Lazy cache keyed by (model_dir, language). Loading int8 takes ~1.2s on
# a 4060 laptop; amortize across calls so the AI Console feels snappy.
_RECOGNIZER_CACHE: dict[tuple[str, str], object] = {}
# Single-slot VAD cache. Path keys it so a model swap (rare) reloads.
_VAD_CACHE: dict[str, object] = {}


def _model_dir(name: str = DEFAULT_MODEL_NAME) -> str:
    return os.path.join(cache_subdir("sherpa"), name)


def _model_files(model_dir: str, *,
                 prefer_fp32: bool = False) -> tuple[str, str, str, str]:
    """Discover (encoder, decoder, tokens, variant) under model_dir.

    Both int8 and fp32 sherpa Whisper exports may sit side-by-side:
      <size>-encoder.int8.onnx   <size>-decoder.int8.onnx   (int8, CPU)
      <size>-encoder.onnx        <size>-decoder.onnx        (fp32, GPU)
      <size>-tokens.txt                                     (shared)

    `prefer_fp32` flips which variant we pick when both are present —
    GPU users want fp32 (CUDA EP has partial int8 op coverage and
    silently falls back to CPU on missing ops). The fourth return
    value is "fp32" or "int8" so callers can log the actual choice.
    """
    import glob
    encs = sorted(glob.glob(os.path.join(model_dir, "*-encoder*.onnx")))
    fp32_encs = [e for e in encs if ".int8." not in os.path.basename(e)]
    int8_encs = [e for e in encs if ".int8." in os.path.basename(e)]

    def _pair_for(enc: str) -> tuple[str, str]:
        base = os.path.basename(enc)
        if ".int8." in base:
            dec_base = base.replace("-encoder.int8.onnx", "-decoder.int8.onnx")
        else:
            dec_base = base.replace("-encoder.onnx", "-decoder.onnx")
        return enc, os.path.join(model_dir, dec_base)

    tok_candidates = sorted(glob.glob(os.path.join(model_dir, "*-tokens.txt")))
    tok = tok_candidates[0] if tok_candidates else os.path.join(model_dir, "tokens.txt")

    if prefer_fp32 and fp32_encs:
        enc, dec = _pair_for(fp32_encs[0])
        return enc, dec, tok, "fp32"
    if int8_encs:
        enc, dec = _pair_for(int8_encs[0])
        return enc, dec, tok, "int8"
    if fp32_encs:
        enc, dec = _pair_for(fp32_encs[0])
        return enc, dec, tok, "fp32"
    # Nothing found — return canonical int8 paths derived from the dir
    # name so the missing-file error message is helpful. Falls into
    # `_load_recognizer`'s missing-files branch below.
    size = os.path.basename(model_dir.rstrip(os.sep)).split("-")[-1] or "small"
    enc = os.path.join(model_dir, f"{size}-encoder.int8.onnx")
    dec = os.path.join(model_dir, f"{size}-decoder.int8.onnx")
    return enc, dec, tok, "int8"


def _load_recognizer(model_dir: str, language: str | None, *,
                     num_threads: int, provider: str = "auto"):
    """Build (or reuse) a sherpa OfflineRecognizer.

    `provider` is one of "auto" | "cpu" | "cuda". "auto" picks "cuda" when
    `core.gpu.cuda_available()` reports a working CUDA wheel + driver,
    otherwise "cpu". Cache is keyed on (model_dir, language, provider) so
    the user can flip GPU on/off without restarting Python.
    """
    import sherpa_onnx as so

    if provider == "auto":
        provider = "cuda" if _gpu.cuda_available() else "cpu"

    # Pick model variant: GPU prefers fp32 (CUDA EP has gaps in int8 op
    # coverage), CPU prefers int8 (smaller + faster on CPU SIMD).
    enc, dec, tok, variant = _model_files(
        model_dir, prefer_fp32=(provider == "cuda"),
    )

    # Cache key includes the variant so flipping CPU/GPU at runtime
    # picks up the right pre-loaded recognizer instead of reusing a
    # mismatched one.
    key = (model_dir, language or "en", provider, variant)
    cached = _RECOGNIZER_CACHE.get(key)
    if cached is not None:
        return cached

    missing = [p for p in (enc, dec, tok) if not os.path.exists(p)]
    if missing:
        raise AIError(
            Kind.MALFORMED, "sherpa",
            "Sherpa Whisper model files missing:\n  "
            + "\n  ".join(missing)
            + f"\nDownload from HuggingFace 'csukuangfj/sherpa-onnx-{DEFAULT_MODEL_NAME}' "
              f"into:\n  {model_dir}"
              "\nIn Model Manager, pick the int8 variant for CPU or fp32 for GPU."
        )

    rec = so.OfflineRecognizer.from_whisper(
        encoder=enc,
        decoder=dec,
        tokens=tok,
        language=language or "en",
        task="transcribe",
        num_threads=num_threads,
        decoding_method="greedy_search",
        provider=provider,
        # Stock int8 export lacks cross-attention; token timestamps cannot
        # be produced. Segment-level timestamps DO work.
        enable_token_timestamps=False,
        enable_segment_timestamps=True,
    )
    # Stash variant so callers can log which one actually loaded.
    rec._vc_variant = variant  # type: ignore[attr-defined]
    _RECOGNIZER_CACHE[key] = rec
    return rec


def _vad_model_path() -> str:
    """Canonical install path for silero-vad (matches catalog target_subdir)."""
    return os.path.join(cache_subdir("sherpa"), "silero-vad", "silero_vad.onnx")


def _try_load_vad():
    """Return a cached VoiceActivityDetector, or None if model missing.

    Returning None signals the caller to fall back to fixed-window chunks.
    Any other load failure (corrupt onnx etc.) is treated the same way —
    we never want VAD problems to block transcription, only to degrade it.
    """
    path = _vad_model_path()
    if not os.path.exists(path):
        return None
    cached = _VAD_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        import sherpa_onnx as so
        cfg = so.VadModelConfig(
            silero_vad=so.SileroVadModelConfig(
                model=path,
                threshold=0.5,
                min_silence_duration=0.5,
                min_speech_duration=0.25,
                max_speech_duration=_VAD_MAX_SPEECH_SEC,
            ),
            sample_rate=_SAMPLE_RATE,
            num_threads=1,
        )
        vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        _VAD_CACHE[path] = vad
        return vad
    except Exception:
        # Corrupt model / API mismatch — silently fall back. The user
        # still gets transcription via fixed-window chunking.
        return None


def _pack_vad_segments(vad_segments, original_samples: np.ndarray,
                       *, max_pack_sec: float = _WHISPER_CHUNK_SEC,
                       max_gap_sec: float = _VAD_PACK_MAX_GAP_SEC):
    """Coalesce adjacent VAD speech regions into ≤max_pack_sec super-chunks.

    Each yielded chunk is a CONTINUOUS slice of `original_samples` (real
    silences preserved between speech regions), so any timestamp Whisper
    emits inside the chunk maps to absolute audio time as
    `chunk_offset_sec + chunk_relative_time` — no gap bookkeeping needed.

    A new bucket starts when:
      - Adding the next speech region would push duration past max_pack_sec.
      - The silence gap to the next region exceeds max_gap_sec
        (long internal silence confuses Whisper's timestamps).

    `vad_segments` is the iterable yielded by `_vad_segment_samples`:
    (offset_sec, samples_for_speech_region) tuples.
    """
    spans: list[tuple[float, float]] = []  # (start_sec, end_sec) in original time
    cur_start: float | None = None
    cur_end: float | None = None

    for offset_sec, region in vad_segments:
        seg_end = offset_sec + len(region) / float(_SAMPLE_RATE)
        if cur_start is None:
            cur_start, cur_end = offset_sec, seg_end
            continue
        gap = offset_sec - cur_end
        prospective_dur = seg_end - cur_start
        if gap > max_gap_sec or prospective_dur > max_pack_sec:
            spans.append((cur_start, cur_end))
            cur_start, cur_end = offset_sec, seg_end
        else:
            cur_end = seg_end
    if cur_start is not None:
        spans.append((cur_start, cur_end))

    for start_sec, end_sec in spans:
        i0 = int(start_sec * _SAMPLE_RATE)
        i1 = int(end_sec * _SAMPLE_RATE)
        yield start_sec, original_samples[i0:i1]


def _vad_segment_samples(vad, samples: np.ndarray):
    """Yield (offset_sec, segment_samples) tuples for each speech region.

    silero VAD operates on fixed 512-sample windows. We feed the entire
    waveform window-by-window, draining detected segments as they finish.
    `flush()` at the end forces any tail-end segment out.
    """
    vad.reset()
    n = len(samples)
    pos = 0
    while pos < n:
        end = min(pos + _VAD_WINDOW_SAMPLES, n)
        vad.accept_waveform(samples[pos:end])
        while not vad.empty():
            seg = vad.front
            yield seg.start / float(_SAMPLE_RATE), np.asarray(seg.samples, dtype=np.float32)
            vad.pop()
        pos = end
    vad.flush()
    while not vad.empty():
        seg = vad.front
        yield seg.start / float(_SAMPLE_RATE), np.asarray(seg.samples, dtype=np.float32)
        vad.pop()


def _fixed_window_chunks(samples: np.ndarray):
    """Fallback chunker for when silero-vad isn't installed.

    Yields the same (offset_sec, chunk_samples) shape as the VAD path so
    the caller doesn't branch on which strategy is in use.
    """
    chunk_len = int(_WHISPER_CHUNK_SEC * _SAMPLE_RATE)
    n = len(samples)
    pos = 0
    while pos < n:
        end = min(pos + chunk_len, n)
        yield pos / float(_SAMPLE_RATE), samples[pos:end]
        pos = end


def _decode_audio_to_pcm16k(audio_path: str) -> np.ndarray:
    """Use ffmpeg to decode any audio/video file to 16kHz mono float32 PCM."""
    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", str(_SAMPLE_RATE),
        "-ac", "1",
        "-loglevel", "error",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
    except FileNotFoundError as e:
        raise AIError(
            Kind.MALFORMED, "sherpa",
            "ffmpeg not found on PATH. Install ffmpeg and ensure it's on PATH.",
            raw=e,
        ) from e
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode("utf-8", errors="replace")[:400] if e.stderr else "unknown"
        raise AIError(
            Kind.MALFORMED, "sherpa",
            f"ffmpeg decode failed for {os.path.basename(audio_path)}: {msg}",
            raw=e,
        ) from e

    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _segments_from_result(r) -> list[dict]:
    """Convert sherpa Result.segment_{texts,timestamps,durations} → segments[]."""
    texts = list(getattr(r, "segment_texts", []) or [])
    starts = list(getattr(r, "segment_timestamps", []) or [])
    durs = list(getattr(r, "segment_durations", []) or [])
    n = max(len(texts), len(starts), len(durs))
    out = []
    for i in range(n):
        text = texts[i] if i < len(texts) else ""
        start = float(starts[i]) if i < len(starts) else 0.0
        dur = float(durs[i]) if i < len(durs) else 0.0
        out.append({
            "id": i,
            "start": start,
            "end": start + dur,
            "text": text,
        })
    # Very short audio sometimes yields .text with empty segment_texts;
    # collapse to a single segment so downstream SRT writer has something.
    if not out and getattr(r, "text", None):
        out.append({"id": 0, "start": 0.0, "end": 0.0, "text": r.text})
    return out


def transcribe(
    audio_path: str,
    *,
    model_dir: str | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    language: str | None = None,
    translate: bool = False,
    num_threads: int = 4,
    provider: str = "auto",
    batch_size: int = 0,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """In-process Whisper transcription via sherpa-onnx.

    Args:
        audio_path:   Local audio/video file. Decoded by ffmpeg to 16k mono.
        model_dir:    Override for model directory. None = default
                      `<models>/sherpa/<model_name>/`.
        model_name:   Subdir name under `<models>/sherpa/`. Default
                      "whisper-small" matches the first-launch tier.
        language:     ISO-639-1 code (e.g. "en", "zh"). None defaults to
                      "en". Sherpa Whisper requires the language at
                      recognizer-load time; auto-detect is not supported
                      by this provider yet — use aistack for that.
        translate:    Not supported here. Raises MALFORMED if True.
        num_threads:  CPU threads for inference. 4 is a sane default.
        on_event:     Status callback. Emits request_summary_local on
                      entry, state_done at end with elapsed + segment count.
        cancel_token: Polled before / after decode. sherpa-onnx C++ runs
                      synchronously and cannot be interrupted mid-call;
                      cancel is coarse-grained.

    Returns:
        verbose_json dict (same shape as aistack/lemonfox):
            {language, duration, text, segments[], words[]}

        - segments[] is sentence-level (drives row-by-row SRT translation)
        - words[] is ALWAYS [] — stock int8 model has no cross-attention
          export. Acceptable per ASR cue-sizing contract.

    Raises:
        AIError(MALFORMED): file missing / ffmpeg failure / model files missing /
                            translate=True (unsupported).
        AIError(CANCELLED): user cancelled before or after decode.
        AIError(UNKNOWN):   sherpa-onnx internal error.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "sherpa", f"Audio file not found: {audio_path}")

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa", "Cancelled by user")

    if translate:
        raise AIError(
            Kind.MALFORMED, "sherpa",
            "translate=True not supported by sherpa-onnx Whisper provider yet. "
            "Use aistack or lemonfox for to-English translation."
        )

    md = model_dir or _model_dir(model_name)
    # Caller contract: `language` is an ISO-639-1 code (e.g. "en", "zh")
    # or None. UI call sites (speech2text.py, project_workbench.py) both
    # convert display names to ISO before reaching this layer.
    iso_lang = language or "en"

    # Resolve "auto" up-front so the device label in the log is accurate.
    resolved_provider = provider
    if resolved_provider == "auto":
        resolved_provider = "cuda" if _gpu.cuda_available() else "cpu"

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device=f"sherpa-{resolved_provider}",
        compute_type="int8",
        language=iso_lang,
        translate="false",
    )

    samples = _decode_audio_to_pcm16k(audio_path)
    duration = len(samples) / float(_SAMPLE_RATE)

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa", "Cancelled by user")

    rec = _load_recognizer(md, iso_lang,
                           num_threads=num_threads, provider=provider)

    # Prefer silero-VAD chunking (cuts at silence, no mid-word loss).
    # Fall back to fixed 28 s windows when the VAD model isn't installed —
    # downloadable from Model Manager but never required.
    vad = _try_load_vad()
    vad_started = time.monotonic()
    if vad is not None:
        raw_segments = list(_vad_segment_samples(vad, samples))
        # Pack adjacent speech regions back into ~28 s slices of the
        # original audio so Whisper's encoder isn't burned on dozens of
        # short chunks (each forward pass costs the same regardless of
        # actual content length).
        chunk_iter = list(_pack_vad_segments(raw_segments, samples))
        chunk_strategy = f"vad+pack({len(raw_segments)}→{len(chunk_iter)})"
    else:
        chunk_iter = list(_fixed_window_chunks(samples))
        chunk_strategy = "fixed"
    vad_elapsed = time.monotonic() - vad_started

    # Edge case: VAD found no speech (silent / pure-noise input). Fall
    # back to fixed-window chunking on the raw waveform so the user gets
    # *something* (Whisper may still hallucinate but at least we tried).
    if chunk_strategy.startswith("vad") and not chunk_iter:
        chunk_iter = list(_fixed_window_chunks(samples))
        chunk_strategy = "fixed"

    total_chunks = max(1, len(chunk_iter))
    emit("state_processing",
         chunk=0, total_chunks=total_chunks,
         segment_count=0, elapsed=int(vad_elapsed),
         strategy=chunk_strategy,
         note=f"chunking done in {vad_elapsed:.1f}s ({total_chunks} chunks)")

    started = time.monotonic()
    all_segments: list[dict] = []
    all_text_parts: list[str] = []
    detected_lang: str | None = None

    # Resolve effective batch size: 0 = auto (4 on CUDA, 1 on CPU).
    # Batched decoding amortizes GPU launch overhead; on CPU the gain is
    # marginal so we stay sequential to keep memory low.
    eff_batch = batch_size if batch_size > 0 else (4 if resolved_provider == "cuda" else 1)

    decode_total = 0.0
    try:
        for batch_start in range(0, total_chunks, eff_batch):
            if cancel_token is not None and cancel_token.cancelled:
                raise AIError(Kind.CANCELLED, "sherpa", "Cancelled by user")

            batch = chunk_iter[batch_start:batch_start + eff_batch]

            # Build streams for this batch
            streams = []
            for _offset_sec, chunk_samples in batch:
                s = rec.create_stream()
                s.accept_waveform(_SAMPLE_RATE, chunk_samples)
                streams.append(s)

            # Single GPU launch for the whole batch — this is the win.
            decode_t0 = time.monotonic()
            rec.decode_streams(streams)
            decode_total += time.monotonic() - decode_t0

            # Walk results, preserving original chunk order so timestamps
            # line up with their offset_sec.
            for s, (offset_sec, chunk_samples) in zip(streams, batch):
                r = s.result

                chunk_text = getattr(r, "text", "") or ""
                if chunk_text:
                    all_text_parts.append(chunk_text)
                if detected_lang is None:
                    detected_lang = getattr(r, "lang", None) or None

                chunk_segs = _segments_from_result(r)
                if chunk_segs:
                    for seg in chunk_segs:
                        seg["start"] += offset_sec
                        seg["end"] += offset_sec
                        all_segments.append(seg)
                elif chunk_text and chunk_strategy.startswith("vad"):
                    # Short VAD chunk: Whisper sometimes returns empty
                    # segment_timestamps for sub-second utterances. Synth
                    # one segment spanning the slice so the cue isn't lost.
                    dur = len(chunk_samples) / float(_SAMPLE_RATE)
                    all_segments.append({
                        "id": -1,
                        "start": offset_sec,
                        "end": offset_sec + dur,
                        "text": chunk_text,
                    })

            emit("state_processing",
                 segment_count=len(all_segments),
                 elapsed=int(time.monotonic() - started),
                 chunk=min(batch_start + eff_batch, total_chunks),
                 total_chunks=total_chunks,
                 strategy=f"{chunk_strategy} batch={eff_batch}")
    except AIError:
        raise
    except Exception as e:
        raise AIError(Kind.UNKNOWN, "sherpa",
                      f"sherpa-onnx decode failed: {e}", raw=e) from e

    # Reindex segment ids after concat so consumers see contiguous IDs.
    for i, seg in enumerate(all_segments):
        seg["id"] = i

    elapsed = time.monotonic() - started
    audio_sec = duration if duration > 0 else 1.0
    rtf_decode = audio_sec / max(decode_total, 1e-3)

    # Perf breakdown emitted as a SEPARATE event so the shared
    # state_done template stays portable across all ASR providers
    # (lemonfox / aistack don't have these fields). UI handler shows
    # both lines back-to-back.
    rec_variant = getattr(rec, "_vc_variant", "?")
    emit("state_perf_breakdown",
         vad_elapsed=round(vad_elapsed, 2),
         decode_elapsed=round(decode_total, 2),
         rtf_decode=round(rtf_decode, 1),
         provider=f"{resolved_provider}/{rec_variant}")
    emit("state_done",
         segment_count=len(all_segments),
         elapsed=int(elapsed))

    return {
        "language": detected_lang or iso_lang,
        "duration": duration,
        "text": " ".join(all_text_parts).strip(),
        "segments": all_segments,
        "words": [],
    }
