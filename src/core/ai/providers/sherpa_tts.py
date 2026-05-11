"""sherpa-onnx provider — in-process Kokoro TTS.

Third leg of the embedded-AI tier (alongside faster-whisper ASR and
llama-cpp-python LLM). Synthesizes text to wav fully in-process, no
network, no cloud key. Supports the multi-language Kokoro model family
shipped by csukuangfj on HuggingFace.

Same `synthesize()` contract as fish_audio / aistack so the router
dispatches it through the same path. Output is always WAV (16 kHz mono
float32 → int16 PCM); aistack-style on-the-fly mp3 transcoding is out
of scope here. Caller can post-encode if needed.

Model layout (per the catalog with download_all=True):
    <models>/sherpa-tts/<model_name>/
        model.onnx                  (or model.int8.onnx for int8 variant)
        voices.bin                  multi-voice embedding pack
        tokens.txt
        espeak-ng-data/...          phonemizer data, all languages
        dict/...                    jieba Chinese segmenter dict
        ...                         (~370 small files in total)
"""

from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import time
import wave
from typing import Callable

import numpy as np

from core.ai.errors import AIError, Kind
from core import gpu as _gpu
from core.paths import cache_subdir

# ensure_cuda_dlls is idempotent and a no-op without the CUDA wheels.
# Sherpa Kokoro can run on cuda provider too — same wheel, same DLLs.
_gpu.ensure_cuda_dlls()


EventCallback = Callable[..., None]

DEFAULT_MODEL_NAME = "kokoro-int8-multi-lang-v1_0"

# Lazy cache so loading the model (~150 MB onnx + voices) is paid once.
# Key by (model_dir, provider) so flipping CPU/GPU at runtime works.
_TTS_CACHE: dict[tuple[str, str], object] = {}


def _model_dir(name: str = DEFAULT_MODEL_NAME) -> str:
    return os.path.join(cache_subdir("sherpa-tts"), name)


def _pick_model_file(model_dir: str) -> str:
    """Prefer fp32 model.onnx when present (better GPU throughput),
    fall back to model.int8.onnx (smaller download, fine on CPU)."""
    for candidate in ("model.onnx", "model.int8.onnx"):
        p = os.path.join(model_dir, candidate)
        if os.path.exists(p):
            return p
    raise AIError(
        Kind.MALFORMED, "sherpa_tts",
        f"No Kokoro model file found in {model_dir}. "
        "Expected model.onnx or model.int8.onnx — download via Model Manager."
    )


def _load_tts(model_dir: str, *, num_threads: int, provider: str):
    """Build (or reuse) an OfflineTts engine for the given model dir."""
    import sherpa_onnx as so

    if provider == "auto":
        provider = "cuda" if _gpu.cuda_available() else "cpu"

    key = (model_dir, provider)
    cached = _TTS_CACHE.get(key)
    if cached is not None:
        return cached, provider

    if not os.path.isdir(model_dir):
        raise AIError(
            Kind.MALFORMED, "sherpa_tts",
            f"Kokoro model directory missing:\n  {model_dir}\n"
            "Download via Model Manager (entries 'kokoro-...').",
        )

    model_path = _pick_model_file(model_dir)
    voices = os.path.join(model_dir, "voices.bin")
    tokens = os.path.join(model_dir, "tokens.txt")
    data_dir = os.path.join(model_dir, "espeak-ng-data")
    dict_dir = os.path.join(model_dir, "dict")  # may or may not exist

    for required, label in (
        (voices, "voices.bin"),
        (tokens, "tokens.txt"),
        (data_dir, "espeak-ng-data/"),
    ):
        if not os.path.exists(required):
            raise AIError(
                Kind.MALFORMED, "sherpa_tts",
                f"Kokoro model is missing {label} in {model_dir}. "
                "Re-download via Model Manager.",
            )

    # Multi-lang Kokoro (>= v1.0) refuses to start unless either
    # `lang` or `lexicon` is set. Discover all lexicon-*.txt files in
    # the model dir and feed them as a comma-separated list — matches
    # the upstream sherpa CLI example. For US/CN news this auto-loads
    # lexicon-us-en.txt + lexicon-zh.txt + (gb-en if present); the
    # model picks the right one per detected script at synthesis time.
    import glob as _glob
    lexicons = sorted(_glob.glob(os.path.join(model_dir, "lexicon-*.txt")))
    lexicon_arg = ",".join(lexicons)

    kokoro_cfg = so.OfflineTtsKokoroModelConfig(
        model=model_path,
        voices=voices,
        tokens=tokens,
        data_dir=data_dir,
        dict_dir=dict_dir if os.path.isdir(dict_dir) else "",
        lexicon=lexicon_arg,
        length_scale=1.0,
        lang="",  # auto from script (for multi-lang model)
    )
    model_cfg = so.OfflineTtsModelConfig(
        kokoro=kokoro_cfg,
        num_threads=num_threads,
        provider=provider,
    )
    cfg = so.OfflineTtsConfig(model=model_cfg)

    try:
        tts = so.OfflineTts(cfg)
    except Exception as e:
        raise AIError(
            Kind.UNKNOWN, "sherpa_tts",
            f"sherpa-onnx OfflineTts construction failed: {e}",
            raw=e,
        ) from e

    _TTS_CACHE[key] = tts
    return tts, provider


def _write_wav(path: str, samples: np.ndarray, sample_rate: int) -> None:
    """Write mono 16-bit PCM wav. samples is float32 in [-1, 1]."""
    int16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)         # 16-bit
        w.setframerate(int(sample_rate))
        w.writeframes(int16.tobytes())


def _transcode_with_ffmpeg(src_wav: str, dst: str) -> None:
    """Convert src_wav → dst, format inferred from dst extension. Used so
    sherpa-onnx (wav-only output) can satisfy callers asking for mp3/opus.
    Errors are wrapped as AIError so the router records the right kind."""
    cmd = ["ffmpeg", "-y", "-i", src_wav, "-loglevel", "error", dst]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as e:
        raise AIError(
            Kind.MALFORMED, "sherpa_tts",
            "ffmpeg not on PATH; cannot transcode wav to requested format. "
            "Install ffmpeg or set audio_format='wav'.",
            raw=e,
        ) from e
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise AIError(
            Kind.UNKNOWN, "sherpa_tts",
            f"ffmpeg transcode failed: {msg}", raw=e,
        ) from e


def synthesize(
    text: str,
    output_path: str,
    *,
    model_dir: str | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    voice_id: str = "0",
    speed: float = 1.0,
    audio_format: str = "wav",
    num_threads: int = 4,
    provider: str = "auto",
    should_cancel: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> None:
    """Synthesize `text` to `output_path` via in-process sherpa Kokoro TTS.

    Args:
        text:           Input text. Multi-language Kokoro auto-detects script.
        output_path:    Destination wav file (overwritten if exists).
        model_dir:      Override; None = `<models>/sherpa-tts/<model_name>/`.
        model_name:     Subdir name under `<models>/sherpa-tts/`. Default
                        is the int8 multi-lang variant (smaller download).
        voice_id:       String index into voices.bin. The Kokoro multi-lang
                        v1.0 pack ships ~50 voices keyed 0..49. Pass "0"
                        unless you know better; the AI Console UI exposes
                        the full picker.
        speed:          1.0 = normal. <1.0 slower, >1.0 faster.
        audio_format:   Only "wav" supported here. mp3/opus must transcode
                        externally (call ffmpeg from feature layer).
        num_threads:    CPU threads (only matters when device=cpu).
        provider:       "auto" | "cpu" | "cuda".
        should_cancel:  Optional predicate. Polled before each generate
                        call (no mid-call cancel — sherpa's C++ side runs
                        synchronously to completion).
        on_chunk:       Optional callback(bytes_written_so_far). Fired
                        once after the wav file is written.
        on_event:       Status callback. Emits request_summary_local +
                        state_done compatible with speech tool log.

    Raises:
        AIError(MALFORMED): missing model files / unsupported voice_id /
                            audio_format != 'wav' / non-numeric voice_id.
        AIError(CANCELLED): should_cancel returned True or cancel_token tripped.
        AIError(UNKNOWN):   sherpa-onnx internal error during synthesis.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not text or not text.strip():
        raise AIError(Kind.MALFORMED, "sherpa_tts",
                      "Empty text — nothing to synthesize.")
    fmt = (audio_format or "wav").lower()
    try:
        sid = int(voice_id)
    except (TypeError, ValueError):
        raise AIError(
            Kind.MALFORMED, "sherpa_tts",
            f"voice_id must be an integer string (e.g. '0'); got {voice_id!r}.",
        )

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa_tts", "Cancelled by user")
    if should_cancel is not None and should_cancel():
        raise AIError(Kind.CANCELLED, "sherpa_tts", "Cancelled by user")

    md = model_dir or _model_dir(model_name)
    tts, resolved_provider = _load_tts(
        md, num_threads=num_threads, provider=provider,
    )

    if sid < 0 or sid >= tts.num_speakers:
        raise AIError(
            Kind.MALFORMED, "sherpa_tts",
            f"voice_id={sid} out of range; this model has "
            f"{tts.num_speakers} voices (valid sid: 0..{tts.num_speakers - 1}).",
        )

    emit(
        "request_summary_local",
        model=model_name,
        device=f"sherpa-tts-{resolved_provider}",
        voice=str(sid),
        speed=str(speed),
        text_len=len(text),
    )

    started = time.monotonic()
    try:
        result = tts.generate(text, sid=sid, speed=speed)
    except Exception as e:
        raise AIError(
            Kind.UNKNOWN, "sherpa_tts",
            f"sherpa-onnx TTS generate failed: {e}",
            raw=e,
        ) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa_tts", "Cancelled by user")

    samples = np.asarray(result.samples, dtype=np.float32)
    sample_rate = int(result.sample_rate)
    audio_sec = len(samples) / float(sample_rate) if sample_rate else 0.0
    elapsed = time.monotonic() - started
    rtf = audio_sec / max(elapsed, 1e-3)

    # Write wav to a temp file when the caller wants something else, then
    # let ffmpeg do the conversion. For wav callers we write directly.
    if fmt == "wav":
        _write_wav(output_path, samples, sample_rate)
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            _write_wav(tmp.name, samples, sample_rate)
            _transcode_with_ffmpeg(tmp.name, output_path)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    bytes_written = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    if on_chunk is not None:
        try:
            on_chunk(bytes_written)
        except Exception:
            pass

    emit("state_done",
         elapsed=int(elapsed),
         audio_sec=round(audio_sec, 2),
         rtf=round(rtf, 1),
         provider=resolved_provider)


def list_voices(model_dir: str | None = None,
                model_name: str = DEFAULT_MODEL_NAME) -> int:
    """Return the speaker count of the loaded model. Used by the AI
    Console's voice picker — the catalog model ships an opaque
    `voices.bin` so the only metadata available is the count."""
    md = model_dir or _model_dir(model_name)
    tts, _ = _load_tts(md, num_threads=1, provider="cpu")
    return int(tts.num_speakers)
