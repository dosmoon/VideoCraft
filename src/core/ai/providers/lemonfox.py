"""Lemonfox ASR provider (type='asr').

HTTP call to Lemonfox's Whisper-compatible transcription endpoint. Handles
upload progress reporting, wait-status ticks, and connection retries. The
caller passes an `on_event` callback so the UI layer can translate status
events (e.g. "state_uploading" with attempt/percent kwargs) via i18n.

Returns verbose_json with BOTH sentence-level segments[] AND word-level
words[] — required by VideoCraft's downstream pipeline (sentence segments
feed translate_srt.py row-by-row; words[] feed the future aspect-ratio-
aware burn-subs cue-sizer). See core/asr.py module docstring for the
full contract.

Phase 1: extracted from tools/speech/speech2text.py. Phase 7 will map
requests exceptions to AIError with the appropriate Kind so feature/UI
layers can branch on structured errors.
"""

import os
import threading
import time
from typing import Callable

import requests

from core.ai.errors import AIError, Kind, map_http_status_to_kind


EventCallback = Callable[..., None]


def transcribe(
    audio_path: str,
    *,
    api_key: str,
    base_url: str,
    language: str | None = None,
    translate: bool = False,
    speaker_labels: bool = False,
    connect_timeout: int = 60,
    read_timeout: int = 120,
    max_retries: int = 1,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio via the Lemonfox Whisper-compatible API.

    Args:
        audio_path:      Path to audio/video file (mp3/mp4/wav/m4a/mkv).
        api_key:         Bearer token for Lemonfox.
        base_url:        Full transcription endpoint URL.
        language:        Optional ISO/display name hint (None = auto-detect).
        translate:       If True, request translate-to-English output.
        speaker_labels:  If True, request SPEAKER_xx tags per segment.
        connect_timeout: TCP connect timeout in seconds.
        read_timeout:    Per-read timeout in seconds.
        max_retries:     Retries on transient errors (connect/read/conn).
        on_event:        Optional callback(event_type, **kwargs) fired on
                         state transitions. See EVENT_TYPES below.

    Returns:
        Raw verbose_json response dict from Lemonfox (fields: text,
        language, duration, segments[], words[]).

    Raises:
        RuntimeError: All attempts failed or response was not valid JSON.

    Events (all carry attempt/max_attempts unless noted):
        "request_summary":      url, filename, mime, language, translate,
                                speaker, timeout
        "mime_fallback":        mime — fallback application/octet-stream used
        "state_uploading":      percent (0-100)
        "state_waiting_start":  upload done, waiting on server
        "state_waiting_tick":   elapsed, total — every ~1s during wait
        "retry_connect_timeout": wait (seconds until next attempt)
        "retry_read_timeout":   wait
        "retry_connection_error": wait
    """
    def emit(event_type: str, **kwargs):
        if on_event is not None:
            try:
                on_event(event_type, **kwargs)
            except Exception:
                pass  # UI errors in callbacks must not derail transcription

    mime_type, used_fallback_mime = _resolve_upload_mime(audio_path)
    data = _build_request_data(language, translate, speaker_labels)
    headers = {"Authorization": f"Bearer {api_key}"}

    emit(
        "request_summary",
        url=base_url,
        filename=os.path.basename(audio_path),
        mime=mime_type,
        language=language or "auto",
        translate=str(translate).lower(),
        speaker=str(speaker_labels).lower(),
        timeout=f"{connect_timeout}/{read_timeout}",
    )
    if used_fallback_mime:
        emit("mime_fallback", mime=mime_type)

    timeout = (connect_timeout, read_timeout)
    max_attempts = max_retries + 1

    for attempt in range(1, max_attempts + 1):
        # Cooperative cancel between retry attempts (the within-attempt
        # path uses session.close() via register_abort to interrupt mid-flight).
        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "Lemonfox", "Cancelled by user")
        result = _attempt(
            audio_path,
            base_url=base_url,
            headers=headers,
            data=data,
            mime_type=mime_type,
            timeout=timeout,
            read_timeout=read_timeout,
            attempt=attempt,
            max_attempts=max_attempts,
            emit=emit,
            cancel_token=cancel_token,
        )
        if isinstance(result, dict):
            return result
        # Otherwise result is a ("retry", reason, exc) marker OR ("fatal", exc)
        kind, payload = result
        if kind == "retry" and attempt < max_attempts:
            reason, _exc = payload
            wait_s = min(2 ** attempt, 30)
            emit(f"retry_{reason}", attempt=attempt, max_attempts=max_attempts, wait=wait_s)
            time.sleep(wait_s)
            continue
        # Either fatal OR retries exhausted
        _raise_retry_exhausted(kind, payload)

    raise AIError(Kind.UNKNOWN, "Lemonfox",
                  "Transcription: no result after all attempts")


# ── Internal helpers ─────────────────────────────────────────────────────────

def _attempt(
    audio_path: str,
    *,
    base_url: str,
    headers: dict,
    data: list,
    mime_type: str,
    timeout: tuple,
    read_timeout: int,
    attempt: int,
    max_attempts: int,
    emit: Callable,
    cancel_token=None,
):
    """Run a single HTTP attempt. Returns dict on success, tuple marker on error."""
    # Per-attempt state for progress throttling
    state_lock = threading.Lock()
    state = {
        "upload_reported": -1,
        "wait_log_second": -1,
        "wait_started_at": None,
        "waiting_started": False,
    }
    wait_stop_event = threading.Event()

    def start_waiting_status():
        with state_lock:
            if state["waiting_started"]:
                return
            state["waiting_started"] = True
            state["wait_started_at"] = time.time()
        emit("state_waiting_start", attempt=attempt, max_attempts=max_attempts)

    def report_upload(uploaded: int, total: int):
        if total <= 0:
            return
        percent = int(uploaded * 100 / total)
        if percent > 100:
            percent = 100
        should_emit = False
        with state_lock:
            if percent != state["upload_reported"] and (percent % 5 == 0 or percent == 100):
                state["upload_reported"] = percent
                should_emit = True
        if should_emit:
            emit("state_uploading", attempt=attempt, max_attempts=max_attempts, percent=percent)
        if percent >= 100:
            start_waiting_status()

    def wait_tick_loop():
        while not wait_stop_event.wait(1):
            with state_lock:
                started = state["wait_started_at"]
            if started is None:
                continue
            elapsed = int(time.time() - started)
            with state_lock:
                last_log = state["wait_log_second"]
                if elapsed != last_log and elapsed % 5 == 0:
                    state["wait_log_second"] = elapsed
                    should_tick = True
                else:
                    should_tick = False
            if should_tick:
                emit(
                    "state_waiting_tick",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    elapsed=elapsed,
                    total=read_timeout,
                )

    wait_thread = threading.Thread(target=wait_tick_loop, daemon=True)
    wait_thread.start()

    # Use a per-attempt session so register_abort can close it cleanly.
    # Closing the session tears down the underlying urllib3 connection
    # pool and any in-flight socket, which surfaces in the blocked
    # POST as ConnectionError → caught below as a cancel marker.
    session = requests.Session()
    if cancel_token is not None:
        cancel_token.register_abort(lambda s=session: s.close())

    try:
        progress_fp = _ProgressFile(audio_path, report_upload,
                                      cancel_token=cancel_token)
        try:
            files = {"file": (os.path.basename(audio_path), progress_fp, mime_type)}
            response = session.post(
                base_url,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout,
            )
        finally:
            progress_fp.close()

        if not response.ok:
            body_preview = (response.text or "")[:500]
            kind = map_http_status_to_kind(response.status_code, body_preview)
            return ("fatal", AIError(
                kind, "Lemonfox",
                f"API error ({response.status_code}): {body_preview}",
            ))

        try:
            return response.json()
        except ValueError:
            return ("fatal", AIError(
                Kind.MALFORMED, "Lemonfox", "Returned invalid JSON"))

    except InterruptedError as e:
        # Raised by _ProgressFile when cancelled mid-upload.
        return ("fatal", AIError(Kind.CANCELLED, "Lemonfox",
                                  "Cancelled by user", raw=e))
    except requests.exceptions.ConnectTimeout as e:
        # Cancellation can manifest as ConnectionError from session.close;
        # check token to disambiguate from a real connection drop.
        if cancel_token is not None and cancel_token.cancelled:
            return ("fatal", AIError(Kind.CANCELLED, "Lemonfox",
                                      "Cancelled by user", raw=e))
        return ("retry", ("connect_timeout", e))
    except requests.exceptions.ReadTimeout as e:
        if cancel_token is not None and cancel_token.cancelled:
            return ("fatal", AIError(Kind.CANCELLED, "Lemonfox",
                                      "Cancelled by user", raw=e))
        return ("retry", ("read_timeout", e))
    except requests.exceptions.ConnectionError as e:
        if cancel_token is not None and cancel_token.cancelled:
            return ("fatal", AIError(Kind.CANCELLED, "Lemonfox",
                                      "Cancelled by user", raw=e))
        return ("retry", ("connection_error", e))
    except requests.exceptions.RequestException as e:
        return ("fatal", AIError(
            Kind.NETWORK, "Lemonfox", f"Request failed: {e}", raw=e))
    finally:
        wait_stop_event.set()


def _raise_retry_exhausted(kind: str, payload):
    """Translate the tuple marker into an AIError for the caller."""
    if kind == "fatal":
        raise payload
    reason, exc = payload
    messages = {
        "connect_timeout":  "Connect timeout (retries exhausted)",
        "read_timeout":     "Read timeout (retries exhausted)",
        "connection_error": "Connection error (retries exhausted)",
    }
    raise AIError(
        Kind.NETWORK, "Lemonfox",
        messages.get(reason, f"Failed: {reason}"), raw=exc) from exc


def _resolve_upload_mime(file_path: str) -> tuple[str, bool]:
    """Infer upload MIME type from extension, with safe fallback.
    Returns (mime, used_fallback)."""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
    }
    if ext in mime_map:
        return mime_map[ext], False
    return "application/octet-stream", True


def _build_request_data(language: str | None, translate: bool, speaker_labels: bool) -> list:
    data = [
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "segment"),
        ("timestamp_granularities[]", "word"),
    ]
    if language:
        data.append(("language", language))
    if translate:
        data.append(("translate_to_english", "true"))
    if speaker_labels:
        data.append(("speaker_labels", "true"))
    return data


class _ProgressFile:
    """Wraps a file-like object so requests can stream upload progress.
    Close the file explicitly after the HTTP call — requests doesn't."""

    def __init__(self, path: str, callback: Callable[[int, int], None],
                  cancel_token=None):
        self._fp = open(path, "rb")
        self._total = os.path.getsize(path)
        self._uploaded = 0
        self._callback = callback
        self._cancel_token = cancel_token

    def read(self, size: int = -1) -> bytes:
        # Per-chunk cancel check — interrupts uploads instantly without
        # waiting for register_abort/session.close to take effect.
        if self._cancel_token is not None and self._cancel_token.cancelled:
            raise InterruptedError("Upload cancelled by user")
        chunk = self._fp.read(size)
        if chunk:
            self._uploaded += len(chunk)
            self._callback(self._uploaded, self._total)
        else:
            self._callback(self._total, self._total)
        return chunk

    def close(self) -> None:
        self._fp.close()

    def __getattr__(self, item):
        return getattr(self._fp, item)
