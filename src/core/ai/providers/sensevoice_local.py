"""SenseVoice local ASR provider (Alibaba FunASR).

Runs SenseVoiceSmall locally — strong on Chinese (Mandarin + Cantonese),
also handles English / Japanese / Korean. Designed as the Asian-language
counterpart to Parakeet (which is European-only).

Output normalized to the same lemonfox verbose_json shape as Parakeet /
faster-whisper:
    {language, duration, text, segments[], words[]}

Architecture: VAD + SenseVoice run **separately**, NOT via FunASR's
AutoModel-with-vad wrapper. The wrapper merges all VAD chunks into a
single concatenated text result, throwing away per-chunk timestamps —
unusable for SRT generation. Here we run fsmn-vad first to get
[start_ms, end_ms] per chunk, then transcribe each chunk individually
so timestamps survive.

SenseVoice is non-autoregressive and does not produce word-level
timestamps natively. Per-chunk segments are sufficient for SRT;
`words[]` is intentionally returned empty.

Each per-chunk SV output is prefixed with rich tokens:
    <|zh|><|NEUTRAL|><|Speech|><|withitn|>actual text...
Use these tokens — not text length — to filter noise hallucinations:
the model's own `<|nospeech|>` / language-mismatch signals are reliable
"this isn't real speech" indicators.

Models download to MODELSCOPE_CACHE / HF cache (set by core.paths
.apply_cache_env at process start).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

from core.ai.errors import AIError, Kind


EventCallback = Callable[..., None]


SUPPORTED_LANGUAGES = ("zh", "yue", "en", "ja", "ko", "auto")

# Event-only chunks (model says "this segment is just music / laughter /
# applause / cough / breath" with no actual speech text). Drop these.
_EVENT_NOISE_TAGS = ("BGM", "Laughter", "Applause", "Cry",
                     "Sneeze", "Cough", "Breath")

# Threshold for "short text" used in the language-mismatch filter. Not a
# blunt length filter — only triggers when the model also disagrees with
# the user-requested language for this chunk.
_LANG_MISMATCH_TEXT_THRESHOLD = 10


# ── Model cache ──────────────────────────────────────────────────────────────

_VAD_MODEL = None
_VAD_LOCK = threading.Lock()
_SV_CACHE: dict[str, object] = {}
_SV_LOCK = threading.Lock()


def _get_vad_model(emit: Callable):
    global _VAD_MODEL
    with _VAD_LOCK:
        if _VAD_MODEL is not None:
            return _VAD_MODEL
    emit("model_loading", model="fsmn-vad", device="auto", compute_type="auto")
    try:
        from funasr import AutoModel
    except ImportError as e:
        raise AIError(
            Kind.NETWORK, "SenseVoice",
            "FunASR not installed. Run: pip install funasr",
            raw=e,
        ) from e
    model = AutoModel(
        model="fsmn-vad",
        disable_update=True,
        disable_log=True,
        disable_pbar=True,
    )
    with _VAD_LOCK:
        _VAD_MODEL = model
    return model


def _get_sv_model(model_name: str, emit: Callable):
    with _SV_LOCK:
        cached = _SV_CACHE.get(model_name)
        if cached is not None:
            return cached
    emit("model_loading", model=model_name, device="auto", compute_type="auto")
    from funasr import AutoModel
    model = AutoModel(
        model=model_name,
        disable_update=True,
        disable_log=True,
        disable_pbar=True,
    )
    with _SV_LOCK:
        _SV_CACHE[model_name] = model
    emit("model_loaded", model=model_name, device="auto", compute_type="auto")
    return model


# ── Audio preprocessing ──────────────────────────────────────────────────────

def _ensure_16k_mono_wav(src_path: str, tmp_dir: str) -> str:
    if not shutil.which("ffmpeg"):
        raise AIError(
            Kind.MALFORMED, "SenseVoice",
            "ffmpeg not found on PATH — required for audio preprocessing",
        )
    out_path = os.path.join(tmp_dir, "audio_16k.wav")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", src_path,
        "-ac", "1", "-ar", "16000",
        "-f", "wav", out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AIError(
            Kind.MALFORMED, "SenseVoice",
            f"ffmpeg preprocessing failed: {proc.stderr.strip()[:300]}",
        )
    return out_path


def _audio_duration_sec(path: str) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            text=True, timeout=10,
        ).strip()
        return float(out) if out else 0.0
    except (subprocess.SubprocessError, ValueError):
        return 0.0


# ── SenseVoice rich-token parsing ────────────────────────────────────────────

# Matches the leading metadata tokens emitted by SenseVoice for each chunk:
#   <|zh|><|NEUTRAL|><|Speech|><|withitn|>...
_LEADING_TOKEN_RE = re.compile(r"^((?:<\|[^|]+\|>)+)")
_TOKEN_RE = re.compile(r"<\|([^|]+)\|>")
_LANG_TAGS = {"zh", "en", "yue", "ja", "ko", "nospeech"}
_EMO_TAGS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL",
             "DISGUSTED", "SURPRISED", "EMO_UNKNOWN"}


def _parse_sv_chunk(raw: str) -> dict:
    """Split a per-chunk SV output into metadata + clean text.

    Returns {"language": str|None, "emotion": str|None, "event": str|None,
             "text": str (rich tokens stripped)}.
    """
    if not raw:
        return {"language": None, "emotion": None, "event": None, "text": ""}

    leading = _LEADING_TOKEN_RE.match(raw)
    tags_section = leading.group(1) if leading else ""
    rest = raw[len(tags_section):]

    language = emotion = event = None
    for m in _TOKEN_RE.finditer(tags_section):
        tag = m.group(1)
        if tag in _LANG_TAGS and language is None:
            language = tag
        elif tag in _EMO_TAGS and emotion is None:
            emotion = tag
        elif tag in ("withitn", "woitn"):
            continue
        elif event is None:
            event = tag

    # Strip any stray tokens still embedded in the body (rare but defensive).
    text = _TOKEN_RE.sub("", rest).strip()
    return {"language": language, "emotion": emotion, "event": event, "text": text}


def _normalize_language(language: str | None) -> str:
    if not language:
        return "auto"
    s = language.strip().lower()
    if s in ("", "auto", "auto detect"):
        return "auto"
    return s


# ── Public API ───────────────────────────────────────────────────────────────

def transcribe(
    audio_path: str,
    *,
    model_name: str = "iic/SenseVoiceSmall",
    language: str | None = None,
    translate: bool = False,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio locally via FunASR fsmn-vad + SenseVoiceSmall.

    Args:
        audio_path:  Path to audio/video. Transcoded to 16 kHz mono WAV.
        model_name:  FunASR SV model id. Default `iic/SenseVoiceSmall`.
        language:    auto / zh / en / yue / ja / ko. Used both as inference
                     hint and as filter signal — chunks the model classifies
                     as a different language with very short text get
                     dropped (the model's own "this isn't your language"
                     signal is more reliable than text-length heuristics).
        translate:   Not supported. Raises if True.
        on_event:    Optional callback(event_type, **kwargs). Same vocabulary
                     as parakeet_local for UI consistency.
        cancel_token: Cooperative cancel checked between VAD chunks.

    Returns:
        dict normalized to lemonfox verbose_json shape. words[] empty
        because SenseVoice does not produce word-level timestamps.

    Raises:
        AIError: model load / preprocessing / inference failure.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "SenseVoice",
                      f"Audio file not found: {audio_path}")
    if translate:
        raise AIError(Kind.MALFORMED, "SenseVoice",
                      "SenseVoice does not support translation — disable the "
                      "translate flag or route to a Whisper provider")

    sv_lang = _normalize_language(language)

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device="auto",
        compute_type="auto",
        language=sv_lang,
        translate="false",
    )

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "SenseVoice", "Cancelled by user")

    try:
        vad_model = _get_vad_model(emit)
        sv_model = _get_sv_model(model_name, emit)
    except AIError:
        raise
    except Exception as e:
        raise AIError(Kind.NETWORK, "SenseVoice",
                      f"Failed to load model {model_name!r}: {e}", raw=e) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "SenseVoice", "Cancelled by user")

    started = time.time()
    tmp_dir = tempfile.mkdtemp(prefix="sensevoice_")
    try:
        wav_path = _ensure_16k_mono_wav(audio_path, tmp_dir)
        duration = _audio_duration_sec(wav_path)

        try:
            import soundfile as sf
        except ImportError as e:
            raise AIError(Kind.NETWORK, "SenseVoice",
                          "soundfile not installed (transitive funasr dep)",
                          raw=e) from e

        try:
            audio_data, sr = sf.read(wav_path)
        except Exception as e:
            raise AIError(Kind.MALFORMED, "SenseVoice",
                          f"Failed to read WAV: {e}", raw=e) from e

        # Step 1: VAD → list of [start_ms, end_ms]
        try:
            vad_out = vad_model.generate(
                input=wav_path,
                max_single_segment_time=30000,
            )
            vad_chunks = vad_out[0].get("value") or []
        except Exception as e:
            raise AIError(Kind.UNKNOWN, "SenseVoice",
                          f"VAD failed: {e}", raw=e) from e

        if not vad_chunks:
            emit("state_done", segment_count=0,
                 elapsed=int(time.time() - started))
            return {"language": sv_lang, "duration": duration,
                    "text": "", "segments": [], "words": []}

        # Step 2: per-chunk SV inference
        segments_out = []
        text_parts = []
        seg_id = 0

        for chunk_idx, (start_ms, end_ms) in enumerate(vad_chunks):
            if cancel_token is not None and cancel_token.cancelled:
                raise AIError(Kind.CANCELLED, "SenseVoice", "Cancelled by user")

            start_sample = int(start_ms * sr / 1000)
            end_sample = int(end_ms * sr / 1000)
            if end_sample <= start_sample:
                continue
            slice_audio = audio_data[start_sample:end_sample]

            try:
                sv_out = sv_model.generate(
                    input=slice_audio,
                    language=sv_lang,
                    use_itn=True,
                    ban_emo_unk=True,
                )
            except Exception as e:
                raise AIError(Kind.UNKNOWN, "SenseVoice",
                              f"Inference failed on chunk {chunk_idx}: {e}",
                              raw=e) from e

            raw = (sv_out[0].get("text") if sv_out else "") or ""
            parsed = _parse_sv_chunk(raw)

            if not _keep_chunk(parsed, sv_lang):
                continue

            segments_out.append({
                "id":    seg_id,
                "start": start_ms / 1000.0,
                "end":   end_ms / 1000.0,
                "text":  parsed["text"],
            })
            text_parts.append(parsed["text"])
            seg_id += 1

            if (chunk_idx + 1) % 5 == 0:
                emit("state_processing",
                     segment_count=seg_id,
                     elapsed=int(time.time() - started))

        elapsed = int(time.time() - started)
        emit("state_done", segment_count=len(segments_out), elapsed=elapsed)

        return {
            "language": sv_lang,
            "duration": duration,
            "text":     " ".join(text_parts).strip(),
            "segments": segments_out,
            "words":    [],
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _keep_chunk(parsed: dict, requested_lang: str) -> bool:
    """Decide whether a per-VAD-chunk SV result should make it into the
    final SRT. Uses the model's own signals — not blunt text-length
    filtering — to drop noise hallucinations.

    Drop rules:
      1. Model says <|nospeech|>: chunk is silence / pure noise.
      2. Event-only tag (<|BGM|>, <|Laughter|>, <|Applause|>, ...) with
         empty text: a non-speech audio event the model labelled but
         couldn't transcribe.
      3. Empty text after token stripping.
      4. Language mismatch + short text: when user asked for `zh` but
         the model classified this short chunk as `<|en|>` / `<|ko|>`,
         it's almost always a noise/breath misrecognition (e.g. "Yeah."
         or "그." in our reference Trump-clip test). Long text in
         another language is genuine code-switch and kept.
    """
    text = (parsed.get("text") or "").strip()
    lang = parsed.get("language")
    event = parsed.get("event")

    if lang == "nospeech":
        return False
    if event in _EVENT_NOISE_TAGS and not text:
        return False
    if not text:
        return False
    if requested_lang != "auto" and lang and lang != requested_lang:
        if len(text) < _LANG_MISMATCH_TEXT_THRESHOLD:
            return False
    return True
