"""aistack HTTP provider — ASR + TTS over OpenAI-compatible HTTP.

Replaces the in-process faster_whisper / parakeet / sensevoice providers
that used to run model weights inside VideoCraft. Models now live in the
sibling aistack repo (github.com/dosmoon/aistack) and are reached via
a localhost FastAPI service (default 127.0.0.1:11500).

This module provides two functions matching the existing provider
contracts so router.py can dispatch to it just like any other provider:

  transcribe(audio_path, ...) -> dict   (verbose_json — Whisper-family shape)
  synthesize(text, output_path, ...) -> None

aistack runs unauthenticated by default (auth_required=False in config).
A network failure here means aistack is not running; the AIError surfaces
with an actionable message pointing at how to start it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable

import requests

from core.ai.errors import AIError, Kind, map_http_status_to_kind


EventCallback = Callable[..., None]

DEFAULT_BASE_URL = "http://127.0.0.1:11500"

_ASR_CONNECT_TIMEOUT = 5
# In streaming mode the read timeout becomes an idle timeout — it fires
# only when no SSE event arrives for this many seconds. Streaming-capable
# backends emit one delta per decoded segment (every few seconds), so
# 120s is far above worst-case idle. Parakeet downgrade-path (single
# delta with full text) is bounded by audio length; raise if you expect
# to transcribe >2h on Parakeet.
_ASR_IDLE_TIMEOUT = 120
# Slot-busy retry budget. Server-side Retry-After is honored, but capped
# to keep the UI responsive even under pathological values.
_ASR_RETRY_MAX_ATTEMPTS = 3
_ASR_RETRY_CAP_SEC = 30

_TTS_CONNECT_TIMEOUT = 5
_TTS_READ_TIMEOUT = 600


# Map aistack error envelope `kind` strings (per integration.md §8) to
# the local AIError taxonomy. The two taxonomies overlap but are not
# identical — aistack has no AUTH/QUOTA/RATE_LIMIT/REFUSED because it
# is a localhost gateway.
_ENVELOPE_KIND_MAP = {
    "network":   Kind.NETWORK,
    "malformed": Kind.MALFORMED,
    "overflow":  Kind.OVERFLOW,
    "cancelled": Kind.CANCELLED,
    "unknown":   Kind.UNKNOWN,
}


def _envelope_kind(kind_str: str | None) -> Kind:
    if not kind_str:
        return Kind.UNKNOWN
    return _ENVELOPE_KIND_MAP.get(kind_str.lower(), Kind.UNKNOWN)


def _parse_error_response(resp: requests.Response) -> tuple[str, str]:
    """Extract (provider, message) from a non-2xx response.

    Tries the aistack envelope first, falls back to FastAPI stock detail
    or raw body. Per integration.md §8 every non-2xx — including the
    slot-busy 503 — should carry the envelope, but we keep the fallback
    so a misbehaving upstream still produces a readable error.
    """
    try:
        body = resp.json()
        envelope = body.get("error") if isinstance(body, dict) else None
        if isinstance(envelope, dict):
            return (str(envelope.get("provider") or "aistack"),
                    str(envelope.get("message") or resp.text[:300]))
        if isinstance(body, dict) and "detail" in body:
            return ("aistack", str(body["detail"])[:300])
    except (ValueError, AttributeError):
        pass
    return ("aistack", (resp.text or f"HTTP {resp.status_code}")[:300])


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

    Always uses SSE streaming (`stream=true`) per aistack integration.md §4.
    Backends that don't natively stream (e.g. Parakeet) send a `warning`
    event up front, then a single delta with the full text — handled by
    the same accumulation loop, surfaced to the UI via `stream_warning`.

    The verbose_json-shape dict returned matches the previous blocking
    contract so router.py and downstream callers don't need to change.

    Args:
        audio_path:  Local audio/video file.
        base_url:    aistack service base URL.
        model_name:  aistack model id (whisper-small, parakeet, sensevoice,
                     auto, ...). Server picks the backend.
        language:    ISO 639-1 hint, or None for auto.
        translate:   Whisper-family only — output English instead of source.
        on_event:    Status callback. Emits request_summary_local on entry,
                     state_processing per delta, stream_warning when a
                     non-streaming backend downgrades, state_done at end.
        cancel_token: Polled per SSE event. Triggering it closes the HTTP
                     response, propagating a TCP RST upstream so aistack
                     releases the GPU slot (per integration.md §4 cancel).

    Returns:
        verbose_json dict (Whisper-family shape — same as Lemonfox provider):
            {language, duration, text, segments[], words[]}

        ── Why we need BOTH segments[] AND words[] ──────────────────────
        VideoCraft's pipeline depends on receiving both layers of
        timestamps from every ASR call:

        - segments[] are SENTENCE-LEVEL semantic units. They drive
          translate_srt.py: each SRT row → one LLM translation call,
          so the LLM sees a complete sentence with full context (tense,
          referent, clause structure). Sub-sentence fragments here
          would silently degrade translation quality.
        - words[] are WORD/CHARACTER-LEVEL timestamps. They are the raw
          material reserved for the burn-subtitles module, which needs
          to do aspect-ratio-aware cue-sizing AFTER translation
          (portrait video wants narrower cues than landscape; a karaoke
          word-highlight overlay needs per-word timing). The current
          SRT writer is intentionally a passthrough; the future cue-
          sizer in the burn pipeline will be the sophisticated one.

        Do NOT cue-size SRT here from words[] — that would feed
        sub-sentence fragments into translation. Keep the contract
        clean: provider returns both layers, downstream picks the
        layer it needs.

        We do NOT pass `segment_granularity` to aistack — defaulting
        to "sentence" is what we want. See aistack docs/api/asr.md
        §"Segment granularity" for the upstream rationale.
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
    form = {
        "model": model_name,
        "response_format": "verbose_json",
        "translate": str(translate).lower(),
        "stream": "true",
    }
    if language:
        form["language"] = language

    # Slot-busy 503 retry loop wraps the POST open. The file is reopened
    # each attempt because requests has already consumed the stream by
    # the time the response status is known.
    last_retry_after = 0.0
    last_busy_rid: str | None = None
    for attempt in range(1, _ASR_RETRY_MAX_ATTEMPTS + 1):
        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "aistack", "Cancelled by user")

        try:
            fh = open(audio_path, "rb")
        except OSError as e:
            raise AIError(Kind.MALFORMED, "aistack",
                          f"Cannot open audio file: {e}", raw=e) from e

        try:
            files = {"file": (os.path.basename(audio_path), fh,
                              "application/octet-stream")}
            resp = requests.post(
                url, data=form, files=files,
                stream=True,
                timeout=(_ASR_CONNECT_TIMEOUT, _ASR_IDLE_TIMEOUT),
            )
        except requests.exceptions.ConnectionError as e:
            fh.close()
            raise _service_unreachable_error("aistack", e) from e
        except requests.exceptions.Timeout as e:
            fh.close()
            raise AIError(Kind.NETWORK, "aistack",
                          f"Connection timed out after {_ASR_CONNECT_TIMEOUT}s",
                          raw=e) from e

        if resp.status_code == 503:
            # Slot busy — back off and retry. Retry-After is in seconds.
            try:
                retry_after = float(resp.headers.get("Retry-After", "5"))
            except (TypeError, ValueError):
                retry_after = 5.0
            retry_after = min(max(retry_after, 0.5), _ASR_RETRY_CAP_SEC)
            last_retry_after = retry_after
            # Each rejected attempt carries its own request id; keep the
            # last one so the final exhaustion error can point at *our*
            # rejected request (the contended request that won the slot
            # has a different rid we never see).
            last_busy_rid = (resp.headers.get("X-Request-ID")
                             or resp.headers.get("x-request-id")
                             or last_busy_rid)
            resp.close()
            fh.close()
            if attempt >= _ASR_RETRY_MAX_ATTEMPTS:
                msg = (f"GPU slot busy after {attempt} attempts "
                       f"(Retry-After={last_retry_after}s). aistack is processing "
                       "another request; try again in a moment.")
                if last_busy_rid:
                    msg = f"{msg} [aistack request_id={last_busy_rid}]"
                raise AIError(Kind.NETWORK, "aistack", msg)
            emit("retry_slot_busy", attempt=attempt,
                 max_attempts=_ASR_RETRY_MAX_ATTEMPTS, wait=int(retry_after))
            # Cooperative cancel during back-off — wake every 0.5s.
            slept = 0.0
            while slept < retry_after:
                if cancel_token is not None and cancel_token.cancelled:
                    raise AIError(Kind.CANCELLED, "aistack", "Cancelled by user")
                step = min(0.5, retry_after - slept)
                time.sleep(step)
                slept += step
            continue

        # Surface aistack's request id (per observability.md) so the user
        # can cross-reference VideoCraft's log line with aistack's
        # access-YYYY-MM-DD.jsonl entry and payload capture dir.
        rid = resp.headers.get("X-Request-ID") or resp.headers.get("x-request-id")
        if rid:
            emit("aistack_request_id", request_id=rid, capability="asr")

        if resp.status_code != 200:
            inner_provider, inner_message = _parse_error_response(resp)
            kind = map_http_status_to_kind(resp.status_code, resp.text)
            resp.close()
            fh.close()
            # Suffix rid into the message — error paths often skip the
            # event log, so embedding it ensures it survives in stack
            # traces and AIError displays.
            if rid:
                inner_message = f"{inner_message} [aistack request_id={rid}]"
            raise AIError(kind, inner_provider, inner_message)

        # 200 — consume SSE. fh is closed by `with resp` once the body
        # is drained; we hold it open inside _consume_sse.
        try:
            return _consume_sse_transcription(resp, emit, cancel_token)
        finally:
            try:
                resp.close()
            finally:
                fh.close()

    # Unreachable — the loop either returns, retries, or raises.
    raise AIError(Kind.UNKNOWN, "aistack", "transcribe() retry loop exited unexpectedly")


def _consume_sse_transcription(
    resp: requests.Response,
    emit: Callable[..., None],
    cancel_token,
) -> dict:
    """Drain an `text/event-stream` ASR response into a verbose_json dict.

    Event types per integration.md §4:
      transcript.text.delta — incremental segment (text + start/end + words)
      transcript.text.done  — terminal event with detected language + duration
      warning               — non-streaming backend; one full-text delta follows
      error                 — mid-stream failure; envelope shape under "error"
    """
    text_parts: list[str] = []
    segments: list[dict] = []
    words: list[dict] = []
    language: str = ""
    duration: float = 0.0
    seg_idx = 0
    saw_done = False
    started_at = time.monotonic()

    for raw in resp.iter_lines(decode_unicode=True):
        if cancel_token is not None and cancel_token.cancelled:
            # Closing the response (the caller's finally) propagates a
            # TCP RST so aistack drops the GPU slot.
            raise AIError(Kind.CANCELLED, "aistack", "Cancelled by user")

        if raw is None or not raw:
            continue
        if not raw.startswith("data:"):
            # SSE comments / `event:` lines / heartbeats — ignore.
            continue
        payload = raw[5:].lstrip()
        if not payload:
            continue

        try:
            evt = json.loads(payload)
        except ValueError:
            continue

        etype = evt.get("type")
        if etype == "transcript.text.delta":
            seg = evt.get("segment") or {}
            delta = evt.get("delta")
            if delta is None:
                delta = seg.get("text", "")
            text_parts.append(delta)
            segments.append({
                "id": seg_idx,
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": delta,
            })
            for w in (seg.get("words") or []):
                words.append({
                    "start": w.get("start"),
                    "end": w.get("end"),
                    "word": w.get("word"),
                })
            seg_idx += 1
            emit("state_processing",
                 segment_count=seg_idx,
                 elapsed=int(time.monotonic() - started_at))
        elif etype == "transcript.text.done":
            language = evt.get("language") or language
            d = evt.get("duration")
            if isinstance(d, (int, float)):
                duration = float(d)
            saw_done = True
            break
        elif etype == "warning":
            emit("stream_warning",
                 code=evt.get("code", ""),
                 model=evt.get("model", ""),
                 message=evt.get("message", ""))
        elif etype == "error":
            err = evt.get("error") or {}
            raise AIError(
                _envelope_kind(err.get("kind")),
                str(err.get("provider") or "aistack"),
                str(err.get("message") or "Stream error"),
            )
        # else: unknown event type — forward-compatible no-op.

    if not saw_done:
        # Stream closed without a done event. If we got nothing at all,
        # surface as a network-level failure; otherwise return what we
        # have so the caller can salvage a partial transcript.
        if not text_parts:
            raise AIError(Kind.NETWORK, "aistack",
                          "Stream ended before any transcription event")

    emit("state_done",
         segment_count=len(segments),
         elapsed=int(time.monotonic() - started_at))

    return {
        "language": language,
        "duration": duration,
        "text": "".join(text_parts),
        "segments": segments,
        "words": words,
    }


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
                inner_provider, inner_message = _parse_error_response(resp)
                # Embed aistack's request id (per observability.md) into
                # the error message so failures can be cross-referenced
                # with the access log / payload capture.
                rid = (resp.headers.get("X-Request-ID")
                       or resp.headers.get("x-request-id"))
                if rid:
                    inner_message = f"{inner_message} [aistack request_id={rid}]"
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
