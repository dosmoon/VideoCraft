"""faster-whisper provider — CTranslate2-backed Whisper ASR.

The embedded ASR provider. CTranslate2 has properly batched encoder/decoder
kernels; real 4060 throughput is 30-40× RTF on small fp16.

Returns the same verbose_json dict shape as aistack / lemonfox:
    {language, duration, text, segments[], words[]}

Notes:
  - Built-in silero VAD via vad_filter=True — no separate chunker needed.
  - words[] populated when `word_timestamps=True`.
  - Model files live under `<models>/faster-whisper/<model_name>/` as a
    directory of (config.json, model.bin, tokenizer.json, vocabulary.*).

Background on the earlier sherpa-onnx attempt:
  see docs/research-notes/sherpa-detour.md.
"""

from __future__ import annotations

import os
import time
from typing import Callable

from core.ai.errors import AIError, Kind
from core import gpu as _gpu
from core.paths import cache_subdir

# Make sure NVIDIA DLLs are on PATH before CTranslate2's CUDA backend is
# touched. ensure_cuda_dlls() is idempotent and a no-op for CPU-only setups.
_gpu.ensure_cuda_dlls()


EventCallback = Callable[..., None]

DEFAULT_MODEL_NAME = "faster-whisper-small"

# Lazy cache: loading a 1 GB model takes several seconds. Key by
# (model_dir, device, compute_type) so flipping settings at runtime
# rebuilds without restart.
_MODEL_CACHE: dict[tuple[str, str, str], object] = {}


def _model_dir(name: str = DEFAULT_MODEL_NAME) -> str:
    return os.path.join(cache_subdir("faster-whisper"), name)


def list_models() -> list[str]:
    """Return subdir names under <models>/faster-whisper/ that look like
    a CT2 model (have model.bin + config.json), sorted.

    Empty list when no models are installed — UI surfaces this as a hint
    to download via the Local Model Manager.
    """
    root = cache_subdir("faster-whisper")
    if not os.path.isdir(root):
        return []
    out: list[str] = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if (os.path.isdir(path)
                and os.path.exists(os.path.join(path, "model.bin"))
                and os.path.exists(os.path.join(path, "config.json"))):
            out.append(name)
    return out


def _resolve_device_and_compute(provider: str, compute_type: str
                                 ) -> tuple[str, str]:
    """Translate (provider, compute_type) into CTranslate2's (device, compute_type).

    provider:
        "auto" → "cuda" when CUDA wheels detected, else "cpu"
        "cpu" / "cuda" → as-is
    compute_type:
        "auto" → "float16" on cuda, "int8" on cpu (best perf/mem each)
        explicit value → passed through; CT2 validates and errors out if
        unsupported on the chosen device.
    """
    device = provider
    if device == "auto":
        device = "cuda" if _gpu.cuda_available() else "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def _load_model(model_dir: str, *, device: str, compute_type: str,
                num_threads: int):
    from faster_whisper import WhisperModel

    key = (model_dir, device, compute_type)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    if not os.path.isdir(model_dir):
        raise AIError(
            Kind.MALFORMED, "faster_whisper",
            f"faster-whisper model directory missing:\n  {model_dir}\n"
            "Download via Model Manager (entries prefixed 'faster-whisper-...'). "
            "Each model is a directory of config.json + model.bin + tokenizer.json + vocabulary.*"
        )
    # Sanity-check the canonical files; missing model.bin is the most common
    # half-finished download.
    must_have = ("config.json", "model.bin", "tokenizer.json")
    missing = [f for f in must_have
               if not os.path.exists(os.path.join(model_dir, f))]
    if missing:
        raise AIError(
            Kind.MALFORMED, "faster_whisper",
            f"faster-whisper model is missing files in {model_dir}:\n  "
            + ", ".join(missing)
            + "\nRe-download via Model Manager."
        )

    try:
        model = WhisperModel(
            model_dir,
            device=device,
            compute_type=compute_type,
            cpu_threads=num_threads,
            # download_root is irrelevant since we pass an absolute path,
            # but set local_files_only to be explicit we never reach the net.
            local_files_only=True,
        )
    except Exception as e:
        raise AIError(
            Kind.UNKNOWN, "faster_whisper",
            f"faster-whisper failed to load model: {e}", raw=e,
        ) from e

    _MODEL_CACHE[key] = model
    return model


def transcribe(
    audio_path: str,
    *,
    model_dir: str | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    language: str | None = None,
    translate: bool = False,
    num_threads: int = 4,
    provider: str = "auto",
    compute_type: str = "auto",
    word_timestamps: bool = False,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """faster-whisper transcription. Standard verbose_json dict shape.

    Args:
        audio_path:      Local audio/video. faster-whisper decodes via
                         its own ffmpeg call (no need for us to pre-decode).
        model_dir:       Override; None = `<models>/faster-whisper/<model_name>/`.
        model_name:      Subdir under `<models>/faster-whisper/`. Default
                         "faster-whisper-small".
        language:        ISO-639-1 (e.g. "en", "uk"). None = auto-detect.
        translate:       True → output translated to English (Whisper task='translate').
        num_threads:     CPU threads (only matters when device=cpu).
        provider:        "auto" | "cpu" | "cuda".
        compute_type:    "auto" → float16 on cuda, int8 on cpu. Or any of
                         CT2's supported types ('float32','int8_float16',etc).
        word_timestamps: True → populate words[]. Adds ~10-20 % overhead.
        on_event:        Lifecycle callback. Emits
                         request_summary_local, state_processing per VAD
                         segment, state_perf_breakdown, state_done.
        cancel_token:    Cooperative; checked between segments. CTranslate2
                         can't be interrupted mid-decode.

    Returns:
        verbose_json dict (language, duration, text, segments[], words[]).

    Raises:
        AIError(MALFORMED): file missing / model dir broken / translate
                            requested with model that doesn't support it.
        AIError(CANCELLED): user cancelled.
        AIError(UNKNOWN):   CTranslate2 internal error.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "faster_whisper",
                      f"Audio file not found: {audio_path}")

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "faster_whisper", "Cancelled by user")

    md = model_dir or _model_dir(model_name)
    device, compute = _resolve_device_and_compute(provider, compute_type)

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device=f"faster-whisper-{device}",
        compute_type=compute,
        language=language or "auto",
        translate="true" if translate else "false",
    )

    model = _load_model(md, device=device, compute_type=compute,
                        num_threads=num_threads)

    started = time.monotonic()
    decode_started = time.monotonic()

    try:
        # vad_filter=True uses faster-whisper's bundled silero-VAD to skip
        # silence; no need for our manual chunking logic. The library
        # internally batches the speech regions.
        segments_iter, info = model.transcribe(
            audio_path,
            language=language,
            task="translate" if translate else "transcribe",
            word_timestamps=word_timestamps,
            vad_filter=True,
            # Greedy is faster and quality-equivalent for most cases;
            # bumping beam_size adds ~30% time for marginal gains.
            beam_size=1,
        )
    except Exception as e:
        raise AIError(Kind.UNKNOWN, "faster_whisper",
                      f"faster-whisper transcribe call failed: {e}",
                      raw=e) from e

    all_segments: list[dict] = []
    all_words: list[dict] = []
    text_parts: list[str] = []

    try:
        # Iteration is what actually drives the decode (segments_iter is a
        # generator). Emit progress per segment so long files don't stall.
        for seg in segments_iter:
            if cancel_token is not None and cancel_token.cancelled:
                raise AIError(Kind.CANCELLED, "faster_whisper",
                              "Cancelled by user")

            seg_dict = {
                "id": getattr(seg, "id", len(all_segments)),
                "start": float(seg.start),
                "end": float(seg.end),
                "text": (seg.text or "").strip(),
            }
            all_segments.append(seg_dict)
            if seg_dict["text"]:
                text_parts.append(seg_dict["text"])

            if word_timestamps and getattr(seg, "words", None):
                for w in seg.words:
                    all_words.append({
                        "start": float(w.start),
                        "end":   float(w.end),
                        "word":  (w.word or "").strip(),
                    })

            emit("state_processing",
                 segment_count=len(all_segments),
                 elapsed=int(time.monotonic() - started))
    except AIError:
        raise
    except Exception as e:
        raise AIError(Kind.UNKNOWN, "faster_whisper",
                      f"faster-whisper iteration failed: {e}",
                      raw=e) from e

    decode_total = time.monotonic() - decode_started
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    audio_sec = duration if duration > 0 else 1.0
    rtf = audio_sec / max(decode_total, 1e-3)

    emit("state_perf_breakdown",
         vad_elapsed=0.0,                      # bundled VAD time isn't
                                               # separately reported by FW
         decode_elapsed=round(decode_total, 2),
         rtf_decode=round(rtf, 1),
         provider=f"{device}/{compute}")
    emit("state_done",
         segment_count=len(all_segments),
         elapsed=int(decode_total))

    return {
        "language": getattr(info, "language", None) or (language or ""),
        "duration": duration,
        "text": " ".join(text_parts).strip(),
        "segments": all_segments,
        "words": all_words,
    }
