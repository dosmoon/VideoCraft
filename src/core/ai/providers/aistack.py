"""aistack HTTP provider — ASR + TTS over OpenAI-compatible HTTP.

Replaces the in-process faster_whisper / parakeet / sensevoice providers
that used to run model weights inside VideoCraft. Models now live in the
sibling aistack repo (github.com/dosmoon/aistack) and are reached via
a localhost FastAPI service (default 127.0.0.1:11500).

This module provides two functions matching the existing provider
contracts so router.py can dispatch to it just like any other provider:

  transcribe(audio_path, ...) -> dict   (Lemonfox-shape verbose_json)
  synthesize(text, output_path, ...) -> None

aistack runs unauthenticated by default (auth_required=False in config).
A network failure here means aistack is not running; the AIError surfaces
with an actionable message pointing at how to start it.
"""

from __future__ import annotations

import os
from typing import Callable

import requests

from core.ai.errors import AIError, Kind, map_http_status_to_kind


EventCallback = Callable[..., None]

DEFAULT_BASE_URL = "http://127.0.0.1:11500"

# Cold-start ASR includes model load (faster-whisper small ~1s warm,
# 5-10s cold). Long enough to absorb the worst case without making
# legitimate hangs invisible.
_ASR_CONNECT_TIMEOUT = 5
_ASR_READ_TIMEOUT = 600

# TTS first call after a vLLM-Omni container restart triggers
# torch.compile + CUDA Graph capture (~2-3 min observed). Steady-state
# requests are sub-second.
_TTS_CONNECT_TIMEOUT = 5
_TTS_READ_TIMEOUT = 600


def list_models_with_capabilities(
    base_url: str = DEFAULT_BASE_URL,
) -> list[tuple[str, list[str]]]:
    """Hit aistack's GET /v1/models and return [(id, capabilities), ...].

    aistack publishes each entry with a `capabilities` array (asr / tts / llm)
    so the AI Console picker can filter by task category. The OpenAI Python
    SDK's `.models.list()` strips unknown fields, so the picker calls this
    helper directly when talking to a local gateway with auth_required=False.
    """
    url = base_url.rstrip("/") + "/v1/models"
    try:
        resp = requests.get(url, timeout=(5, 30))
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise _service_unreachable_error("aistack", exc) from exc

    out: list[tuple[str, list[str]]] = []
    for entry in (data.get("data") or []):
        if not isinstance(entry, dict):
            continue
        mid = entry.get("id")
        caps = entry.get("capabilities") or []
        if mid:
            out.append((str(mid), [str(c) for c in caps]))
    return out


def _service_unreachable_error(provider_label: str, exc: Exception) -> AIError:
    return AIError(
        Kind.NETWORK, provider_label,
        "aistack service is not reachable. Start it with:\n"
        "  cd D:\\My_Prjs\\dosmoon-aistack && scripts\\dev.bat\n"
        "(or run uvicorn aistack.main:app --port 11500)",
        raw=exc,
    )


def transcribe(
    audio_path: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model_name: str = "whisper-small",
    language: str | None = None,
    translate: bool = False,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio via aistack's OpenAI-compatible /v1/audio/transcriptions.

    Args:
        audio_path:  Local audio/video file (any ffmpeg-readable format).
        base_url:    aistack service base URL (no trailing /v1/...).
        model_name:  aistack model id. Examples:
                       whisper-small, whisper-medium, whisper-large-v3
                       parakeet, sensevoice
                     The aistack server picks the right backend.
        language:    ISO 639-1 code (e.g. "zh", "en") or None for auto.
        translate:   Whisper-family only — emit English instead of source.
        on_event:    Status callback. We emit the "request_summary_local"
                     and "state_done" events to match the in-process
                     providers' contract; finer-grained progress is not
                     surfaced over HTTP.
        cancel_token: Cooperatively checked before sending and after
                     receipt; we cannot interrupt aistack mid-inference
                     over a single HTTP request.

    Returns:
        Lemonfox-shape verbose_json dict:
            {language, duration, text, segments[], words[]}
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "aistack",
                      f"Audio file not found: {audio_path}")

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "aistack", "Cancelled by user")

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device="aistack",
        compute_type="aistack",
        language=language or "auto",
        translate=str(translate).lower(),
    )

    url = base_url.rstrip("/") + "/v1/audio/transcriptions"
    data = {
        "model": model_name,
        "response_format": "verbose_json",
        "translate": str(translate).lower(),
    }
    if language:
        data["language"] = language

    try:
        with open(audio_path, "rb") as fh:
            files = {"file": (os.path.basename(audio_path), fh, "application/octet-stream")}
            resp = requests.post(
                url, data=data, files=files,
                timeout=(_ASR_CONNECT_TIMEOUT, _ASR_READ_TIMEOUT),
            )
    except requests.exceptions.ConnectionError as e:
        raise _service_unreachable_error("aistack", e) from e
    except requests.exceptions.Timeout as e:
        raise AIError(Kind.NETWORK, "aistack",
                      f"Request timed out after {_ASR_READ_TIMEOUT}s", raw=e) from e

    if resp.status_code != 200:
        # aistack errors come back as {"error": {"kind","provider","message"}}.
        # Surface the embedded provider/message so the user sees which
        # backend actually failed (e.g. "Faster-Whisper: Audio file not found").
        try:
            envelope = resp.json().get("error", {})
            inner_provider = envelope.get("provider", "aistack")
            inner_message = envelope.get("message", resp.text[:300])
        except (ValueError, AttributeError):
            inner_provider = "aistack"
            inner_message = resp.text[:300] or f"HTTP {resp.status_code}"
        raise AIError(
            map_http_status_to_kind(resp.status_code, resp.text),
            inner_provider, inner_message,
        )

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "aistack", "Cancelled by user")

    try:
        result = resp.json()
    except ValueError as e:
        raise AIError(Kind.MALFORMED, "aistack",
                      f"Non-JSON response from aistack: {resp.text[:200]}",
                      raw=e) from e

    emit("state_done",
         segment_count=len(result.get("segments") or []),
         elapsed=int(resp.elapsed.total_seconds()) if resp.elapsed else 0)
    return result


def synthesize(
    text: str,
    output_path: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model_name: str = "qwen3-tts-12hz-0.6b-customvoice",
    voice_id: str = "vivian",
    audio_format: str = "wav",
    language: str = "English",
    task_type: str = "CustomVoice",
    should_cancel: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
    cancel_token=None,
) -> None:
    """Stream TTS audio from aistack to `output_path`.

    aistack proxies to vLLM-Omni's /v1/audio/speech, which accepts these
    fields beyond OpenAI standard: task_type (CustomVoice / VoiceClone /
    VoiceDesign), language, ref_audio, ref_text. Cooperative cancel is
    coarse — checked before send and during streaming chunks — because
    HTTP cannot interrupt a mid-flight inference cleanly.

    Args:
        text:          Input text.
        output_path:   Destination audio file (overwritten if exists).
        base_url:      aistack service base URL.
        model_name:    aistack TTS model id.
        voice_id:      Voice name for the model (default "vivian" for Qwen3-TTS).
        audio_format:  Forwarded to aistack; vLLM-Omni currently emits WAV
                       regardless, so this hint is informational.
        language:      Per Qwen3-TTS API (English, Chinese, ...).
        task_type:     Qwen3-TTS API task slot.
        should_cancel: Cooperative cancel predicate.
        on_chunk:      Called with cumulative bytes after each chunk.

    Raises:
        AIError:          aistack unreachable / upstream failure.
        InterruptedError: should_cancel returned True or cancel_token set.
    """
    if cancel_token is not None and cancel_token.cancelled:
        raise InterruptedError("Cancelled before request")
    if should_cancel and should_cancel():
        raise InterruptedError("Cancelled before request")

    url = base_url.rstrip("/") + "/v1/audio/speech"
    body = {
        "input": text,
        "voice": voice_id,
        "task_type": task_type,
        "language": language,
        "response_format": audio_format,
    }
    # vLLM-Omni serves a single TTS model and rejects requests whose
    # `model` field doesn't match its case-sensitive registered id.
    # Omit the field unless the caller explicitly overrides — vLLM-Omni
    # then uses its loaded model. Custom model_name kept for future
    # multi-model deployments.
    if model_name and model_name != "qwen3-tts-12hz-0.6b-customvoice":
        body["model"] = model_name

    try:
        with requests.post(
            url, json=body,
            timeout=(_TTS_CONNECT_TIMEOUT, _TTS_READ_TIMEOUT),
            stream=True,
        ) as resp:
            if resp.status_code != 200:
                try:
                    envelope = resp.json().get("error", {})
                    inner_provider = envelope.get("provider", "aistack")
                    inner_message = envelope.get("message", resp.text[:300])
                except (ValueError, AttributeError):
                    inner_provider = "aistack"
                    inner_message = (resp.text[:300] if resp.text
                                     else f"HTTP {resp.status_code}")
                raise AIError(
                    map_http_status_to_kind(resp.status_code, resp.text or ""),
                    inner_provider, inner_message,
                )

            written = 0
            with open(output_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    if cancel_token is not None and cancel_token.cancelled:
                        raise InterruptedError("Cancelled mid-stream")
                    if should_cancel and should_cancel():
                        raise InterruptedError("Cancelled mid-stream")
                    fh.write(chunk)
                    written += len(chunk)
                    if on_chunk is not None:
                        try:
                            on_chunk(written)
                        except Exception:
                            pass
    except requests.exceptions.ConnectionError as e:
        raise _service_unreachable_error("aistack", e) from e
    except requests.exceptions.Timeout as e:
        raise AIError(Kind.NETWORK, "aistack",
                      f"TTS request timed out after {_TTS_READ_TIMEOUT}s",
                      raw=e) from e
