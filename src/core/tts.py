"""TTS feature layer — text/dialogue -> audio file.

UI calls synthesize_text() / synthesize_dialogue() with progress and
cancellation callbacks; this module owns dialogue parsing and multi-
segment ffmpeg concatenation. AI dispatch goes through core.ai.tts().

Per architecture principle 1, UI should import this module (core.tts),
not core.ai directly.
"""

import os
import subprocess
import tempfile
from typing import Callable

from core import ai


ProgressCallback = Callable[[int, int, str], None]  # (done, total, msg)
CancelPredicate  = Callable[[], bool]


# ── Synthesis ───────────────────────────────────────────────────────────────

def synthesize_text(
    text: str,
    output_path: str,
    *,
    voice_id: str,
    provider: str,
    audio_format: str = "mp3",
    should_cancel: CancelPredicate | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_token=None,
) -> str:
    """Single-voice TTS. Streams audio to output_path.

    `provider` is required (no default since 2026-05-11 — TTS picks
    are context-specific, callers always know which engine they want
    via VoicePickerDialog).

    on_progress is called with (bytes_written, -1, "streaming") per chunk.
    The -1 total indicates the total is unknown (streaming API).
    """
    def on_chunk(written: int):
        if on_progress:
            on_progress(written, -1, "streaming")

    ai.tts(
        text, output_path,
        provider=provider,
        voice_id=voice_id,
        audio_format=audio_format,
        should_cancel=should_cancel,
        on_chunk=on_chunk,
        cancel_token=cancel_token,
    )
    return output_path


def synthesize_dialogue(
    segments: list[tuple[str, str]],
    role_voice_map: dict[str, tuple[str, str]],
    output_path: str,
    *,
    audio_format: str = "mp3",
    should_cancel: CancelPredicate | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_token=None,
) -> str:
    """Multi-voice dialogue TTS — each role independently picks its
    engine + voice.

    role_voice_map shape:  {role_name: (provider, voice_id)}

    Roles can mix providers freely (e.g. narrator on edge_tts, child
    voice on fish_audio); each segment dispatches to whatever the role
    is mapped to.

    Synthesizes each (role, text) segment to a temp file, then ffmpeg-concat
    into `output_path`. Cleans up temps whether the run succeeds, fails, or
    is cancelled mid-stream.

    on_progress semantics:
        (i, total, role)         — about to synthesize segment i (0-based)
        (total, total, "merging") — all segments done, concatenating now
    """
    if not segments:
        raise ValueError("No dialogue segments to synthesize")

    total = len(segments)
    tmp_files: list[str] = []

    try:
        for i, (role, text) in enumerate(segments):
            # Both signal types stop the loop. cancel_token wins for the new
            # Hub-driven Cancel button; should_cancel for older callers that
            # still pass a predicate.
            if cancel_token is not None and cancel_token.cancelled:
                raise InterruptedError("Cancelled")
            if should_cancel and should_cancel():
                raise InterruptedError("Cancelled")

            entry = role_voice_map.get(role)
            if not entry:
                raise RuntimeError(f"No voice configured for role {role!r}")
            provider, voice_id = entry
            if not provider or not voice_id:
                raise RuntimeError(
                    f"Role {role!r} has incomplete voice mapping "
                    f"(provider={provider!r}, voice_id={voice_id!r})")

            if on_progress:
                on_progress(i, total, role)

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{audio_format}")
            tmp.close()
            tmp_files.append(tmp.name)

            ai.tts(
                text, tmp.name,
                provider=provider,
                voice_id=voice_id,
                audio_format=audio_format,
                should_cancel=should_cancel,
                on_chunk=None,
                cancel_token=cancel_token,
            )

        if on_progress:
            on_progress(total, total, "merging")
        _concat_audio(tmp_files, output_path)

    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except OSError:
                pass

    return output_path


def parse_dialogue(raw: str, role_voice_map: dict) -> list[tuple[str, str]]:
    """Parse 'Name:text' / 'Name：text' lines into (role, text) segments.

    Consecutive lines by the same speaker are merged (single TTS call with
    space-joined text) to avoid choppy output. Only roles present in
    role_voice_map are recognized.
    """
    segments: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        for role in role_voice_map:
            matched = False
            for sep in ['：', ':']:
                if line.startswith(role + sep):
                    text = line[len(role) + 1:].strip()
                    if text:
                        if segments and segments[-1][0] == role:
                            segments[-1] = (role, segments[-1][1] + " " + text)
                        else:
                            segments.append((role, text))
                    matched = True
                    break
            if matched:
                break
    return segments


# ── Internal ────────────────────────────────────────────────────────────────

def _concat_audio(files: list[str], output_path: str) -> None:
    """ffmpeg concat demuxer — merges audio files without re-encoding."""
    lf = tempfile.NamedTemporaryFile(
        mode='w', delete=False, suffix='.txt', encoding='utf-8')
    for f in files:
        lf.write(f"file '{f}'\n")
    lf.close()
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
             '-i', lf.name, '-c', 'copy', output_path],
            capture_output=True, check=True)
    finally:
        try:
            os.unlink(lf.name)
        except OSError:
            pass
