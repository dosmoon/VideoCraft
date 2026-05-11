"""Fish Audio TTS provider.

Wraps fish_audio_sdk.Session.tts() streaming — writes audio chunks to
`output_path` as they arrive. Cooperative cancellation via a caller-
supplied `should_cancel()` callable (Phase 7 will integrate with
CancellationToken directly).

Phase 1: extracted from tools/text2video/text2video.py. Phase 7 will map
fish_audio_sdk exceptions onto AIError.Kind.
"""

from typing import Callable

from core.ai.errors import AIError, Kind, map_http_status_to_kind


def is_sdk_available() -> bool:
    """True if fish_audio_sdk is importable. UI layer uses this to grey out
    the TTS tool / show an install hint when the SDK isn't installed."""
    try:
        import fish_audio_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def synthesize(
    text: str,
    output_path: str,
    *,
    api_key: str,
    voice_id: str,
    audio_format: str = "mp3",
    should_cancel: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
    cancel_token=None,
) -> None:
    """Stream TTS audio to `output_path`.

    Args:
        text:          Input text.
        output_path:   Destination file (overwritten if exists).
        api_key:       Fish Audio API key.
        voice_id:      reference_id (fish.audio model ID).
        audio_format:  'mp3' | 'wav' | 'opus'.
        should_cancel: Optional predicate; when it returns True we raise
                       InterruptedError mid-stream. Feature layer wraps
                       this around its own stop flag.
        on_chunk:      Optional callback(total_bytes_written_so_far) for
                       progress reporting. Called after each chunk.

    Raises:
        RuntimeError:    SDK not installed or API call failed.
        InterruptedError: should_cancel() returned True.
    """
    try:
        from fish_audio_sdk import Session, TTSRequest
    except ImportError as e:
        raise AIError(
            Kind.AUTH, "FishAudio",
            "fish_audio_sdk not installed; pip install fish_audio_sdk",
            raw=e,
        ) from e

    # SDK 1.3.x: Session.tts() directly returns Generator[bytes]; no context
    # manager and no .iter_bytes() on the return value. Older code (pre-M5)
    # used a stale `with ... as resp: resp.iter_bytes()` pattern that never
    # worked against this SDK version.
    # If both should_cancel and cancel_token are passed, fold them into one
    # predicate — either signal stops the stream. Token-only is the new
    # canonical path; should_cancel is kept for backward-compat callers.
    if cancel_token is not None:
        original_should_cancel = should_cancel
        def should_cancel():
            if cancel_token.cancelled:
                return True
            if original_should_cancel is not None:
                return original_should_cancel()
            return False
    session = Session(api_key)
    total = 0
    try:
        with open(output_path, "wb") as f:
            for chunk in session.tts(TTSRequest(
                reference_id=voice_id, text=text, format=audio_format,
            )):
                if should_cancel and should_cancel():
                    raise InterruptedError("TTS cancelled")
                f.write(chunk)
                total += len(chunk)
                if on_chunk:
                    on_chunk(total)
    except InterruptedError:
        raise AIError(Kind.CANCELLED, "FishAudio", "TTS cancelled by user")
    except AIError:
        raise
    except Exception as e:
        # Fish Audio SDK doesn't expose typed exceptions; sniff status code
        # from the response if attached, otherwise scan the message.
        msg = getattr(e, "message", None) or str(e)
        msg_low = msg.lower()
        status = getattr(getattr(e, "response", None), "status_code", None)
        kind = Kind.UNKNOWN
        if status:
            kind = map_http_status_to_kind(int(status), msg)
        elif "401" in msg or "unauthorized" in msg_low or "api key" in msg_low:
            kind = Kind.AUTH
        elif "402" in msg or "payment" in msg_low or "balance" in msg_low:
            kind = Kind.QUOTA
        elif "429" in msg or "rate" in msg_low:
            kind = Kind.RATE_LIMIT
        elif any(t in msg_low for t in ("timeout", "timed out", "connection")):
            kind = Kind.NETWORK
        elif "voice" in msg_low and ("not found" in msg_low or "invalid" in msg_low):
            kind = Kind.MALFORMED
        raise AIError(
            kind, "FishAudio",
            f"{msg} (voice_id={voice_id!r}, text_len={len(text)})",
            raw=e,
        ) from e


def fetch_voice_catalog(api_key: str | None = None) -> list:
    """Pull the user's fish.audio voice models, page by page.

    Calls Session.list_models(self_only=True) — only the voices in the
    caller's own account, not the public marketplace (which is enormous
    and full of community uploads they don't actually use).

    api_key is loaded by the catalog dispatcher from
    keys/FishAudio.key. When missing, returns []; the picker UI shows
    "no key configured" upstream rather than a stack trace.
    """
    from core.ai.tts_voice import TTSVoice
    if not api_key:
        return []

    try:
        from fish_audio_sdk import Session
    except ImportError:
        return []

    try:
        sess = Session(api_key)
    except Exception:
        return []

    out: list[TTSVoice] = []
    page = 1
    page_size = 50
    while True:
        try:
            resp = sess.list_models(
                self_only=True, page_size=page_size, page_number=page,
                sort_by="created_at",
            )
        except Exception:
            # Network / auth error — return what we have so far so the
            # picker still shows something on a flaky connection.
            break

        items = resp.items or []
        for m in items:
            # Type 'tts' only (Fish also has 'svc' / voice conversion
            # entries that don't apply to standard text → audio).
            if getattr(m, "type", "tts") != "tts":
                continue
            # State 'trained' = ready to use. 'training' / 'created' /
            # 'failed' would 4xx on synth.
            if getattr(m, "state", "") != "trained":
                continue
            out.append(TTSVoice(
                provider="fish_audio",
                voice_id=m.id,
                display_name=m.title or m.id,
                # Languages is a list of ISO codes per Fish docs;
                # take the first as the primary tag.
                language=(m.languages[0] if m.languages else ""),
                gender="",     # Fish doesn't expose gender metadata
                tags=tuple(m.tags or ()),
                description=(m.description or "")[:280],
            ))

        total = getattr(resp, "total", len(out))
        if page * page_size >= total or not items:
            break
        page += 1

    return out
