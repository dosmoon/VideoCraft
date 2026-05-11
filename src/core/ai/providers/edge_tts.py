"""edge_tts provider — Microsoft Edge Read-Aloud TTS, free + no key.

Talks to the same `speech.platform.bing.com/.../readaloud/edge/v1` endpoint
that the Edge browser's Read Aloud feature uses, via the rany2/edge-tts
Python library (MIT). Quality is on par with Azure Neural TTS — these are
the same voice models (XiaoxiaoNeural, YunxiNeural, etc.) — without the
Cognitive Services key requirement.

Trade-offs:
  + News-broadcast Chinese quality
  + 400+ voices including 100+ Chinese
  + Zero local model footprint
  - Requires internet connection (online-only)
  - Microsoft could shut the endpoint down at any time (it's been up 5+ years)
  - ToS gray area; fine for personal / open-source / non-commercial use

Caller contract matches fish_audio:
    synthesize(text, output_path, *, voice_id, ...) -> None

`voice_id` is the Edge voice short name (e.g. 'zh-CN-YunxiNeural').
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
from typing import Callable

from core.ai.errors import AIError, Kind


EventCallback = Callable[..., None]

DEFAULT_VOICE = "zh-CN-YunxiNeural"

# Curated subset — Edge ships 400+ voices but this list is what the AI
# Console dropdown shows. Users can still type any other Edge voice ID
# manually in the entry box. Ordered by likely usage in our news /
# Chinese content scenarios.
POPULAR_VOICES = [
    # Mandarin Chinese (mainland)
    "zh-CN-XiaoxiaoNeural",   # 晓晓 — 女声 / 标准
    "zh-CN-YunxiNeural",      # 云希 — 男声 / 新闻
    "zh-CN-YunyangNeural",    # 云扬 — 男声 / 播音
    "zh-CN-XiaoyiNeural",     # 晓伊 — 女声 / 知性
    "zh-CN-YunjianNeural",    # 云健 — 男声 / 体育
    "zh-CN-YunxiaNeural",     # 云夏 — 男声 / 少年
    "zh-CN-XiaochenNeural",   # 晓辰 — 女声 / 朋友
    "zh-CN-XiaohanNeural",    # 晓涵 — 女声 / 温暖
    "zh-CN-XiaomengNeural",   # 晓梦 — 女声 / 甜美
    "zh-CN-XiaomoNeural",     # 晓墨 — 女声 / 多情感
    "zh-CN-XiaoqiuNeural",    # 晓秋 — 女声
    "zh-CN-XiaoshuangNeural", # 晓双 — 童声
    "zh-CN-XiaoxuanNeural",   # 晓萱 — 女声 / 多情感
    "zh-CN-XiaoyanNeural",    # 晓颜 — 女声
    "zh-CN-XiaoyouNeural",    # 晓悠 — 童声
    "zh-CN-XiaozhenNeural",   # 晓甄 — 女声 / 多情感
    "zh-CN-YunfengNeural",    # 云枫 — 男声
    "zh-CN-YunhaoNeural",     # 云皓 — 男声 / 广告
    "zh-CN-YunyeNeural",      # 云野 — 男声 / 多情感
    "zh-CN-YunzeNeural",      # 云泽 — 男声 / 老者
    # Cantonese / Taiwanese
    "zh-HK-HiuMaanNeural",    # 曉曼 — 粤语女声
    "zh-HK-WanLungNeural",    # 雲龍 — 粤语男声
    "zh-TW-HsiaoChenNeural",  # 曉臻 — 国语女声 (台)
    "zh-TW-YunJheNeural",     # 雲哲 — 国语男声 (台)
    # English (most common)
    "en-US-AriaNeural",       # US female / news
    "en-US-GuyNeural",         # US male / news
    "en-US-JennyNeural",       # US female / friendly
    "en-GB-SoniaNeural",       # UK female
    "en-GB-RyanNeural",        # UK male
]


def _run_async(coro):
    """Drive an async coroutine to completion from sync caller code.

    Uses asyncio.run() when no loop is active (typical from a worker
    thread); falls back to a fresh loop for safety."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # asyncio.run() rejects when an event loop is already running
        # in this thread (rare for our callers, but be defensive).
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _transcode_with_ffmpeg(src_mp3: str, dst: str) -> None:
    """Convert src_mp3 → dst when caller wants wav/opus etc.
    Re-encodes since edge-tts always returns MP3."""
    cmd = ["ffmpeg", "-y", "-i", src_mp3, "-loglevel", "error", dst]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as e:
        raise AIError(
            Kind.MALFORMED, "edge_tts",
            "ffmpeg not on PATH; cannot transcode mp3 to requested format.",
            raw=e,
        ) from e
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise AIError(
            Kind.UNKNOWN, "edge_tts",
            f"ffmpeg transcode failed: {msg}", raw=e,
        ) from e


def _percent(n: float) -> str:
    """Format float ratio (1.0=normal, 1.5=+50%) as edge-tts rate string."""
    delta = (n - 1.0) * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{int(round(delta))}%"


def synthesize(
    text: str,
    output_path: str,
    *,
    voice_id: str = DEFAULT_VOICE,
    speed: float = 1.0,
    audio_format: str = "mp3",
    pitch: str = "+0Hz",
    volume: str = "+0%",
    should_cancel: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> None:
    """Synthesize via Microsoft Edge Read Aloud endpoint.

    Args:
        text:           Input text (any language Edge supports — auto-detect
                        not needed since voice carries language).
        output_path:    Destination file. Format inferred from extension.
        voice_id:       Edge voice short name like 'zh-CN-YunxiNeural'.
                        See POPULAR_VOICES for curated list; full catalog
                        is on Microsoft's docs (edge-tts also exposes
                        async list_voices()).
        speed:          1.0 = normal. Mapped to edge-tts rate '+N%'.
        audio_format:   'mp3' (native), 'wav', 'opus' — non-mp3 needs ffmpeg.
        pitch:          edge-tts pitch string e.g. '+5Hz' / '-10Hz'.
        volume:         edge-tts volume string e.g. '+10%' / '-50%'.
        should_cancel:  Polled before request. No mid-stream cancel — edge-tts
                        finishes its HTTP transfer either way; for typical
                        news clips that's seconds.
        on_chunk:       Called once after the file is written with bytes_written.
        on_event:       Status callbacks (request_summary_local + state_done).
        cancel_token:   Polled before request, same as should_cancel.

    Raises:
        AIError(MALFORMED): empty text / unknown voice / unsupported format.
        AIError(NETWORK):   HTTP failure to MS endpoint.
        AIError(CANCELLED): user cancelled before the request fired.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not text or not text.strip():
        raise AIError(Kind.MALFORMED, "edge_tts",
                      "Empty text — nothing to synthesize.")
    if not voice_id:
        voice_id = DEFAULT_VOICE

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "edge_tts", "Cancelled by user")
    if should_cancel is not None and should_cancel():
        raise AIError(Kind.CANCELLED, "edge_tts", "Cancelled by user")

    fmt = (audio_format or "mp3").lower()

    emit("request_summary_local",
         model="edge-tts",
         device="online",
         voice=voice_id,
         speed=str(speed),
         text_len=len(text))

    try:
        import edge_tts
    except ImportError as e:
        raise AIError(
            Kind.MALFORMED, "edge_tts",
            "edge-tts library not installed. Run: pip install edge-tts",
            raw=e,
        ) from e

    rate_str = _percent(speed)

    async def _run():
        com = edge_tts.Communicate(text, voice_id,
                                    rate=rate_str, volume=volume, pitch=pitch)
        # Native output is mp3. When caller wants something else we save
        # to a temp mp3 then ffmpeg-transcode.
        if fmt == "mp3":
            os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".",
                        exist_ok=True)
            await com.save(output_path)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            try:
                await com.save(tmp.name)
                _transcode_with_ffmpeg(tmp.name, output_path)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

    started = time.monotonic()
    try:
        _run_async(_run())
    except AIError:
        raise
    except Exception as e:
        msg = str(e).lower()
        kind = Kind.NETWORK if any(k in msg for k in
                                    ("timeout", "connection", "network",
                                     "websocket", "socket")) else Kind.UNKNOWN
        raise AIError(
            kind, "edge_tts",
            f"edge-tts call failed: {e}", raw=e,
        ) from e

    elapsed = time.monotonic() - started
    bytes_written = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    if on_chunk is not None:
        try:
            on_chunk(bytes_written)
        except Exception:
            pass

    emit("state_done",
         elapsed=int(elapsed),
         bytes=bytes_written,
         provider="edge")


def list_popular_voices() -> list[str]:
    """Curated voice short-names suitable for the AI Console dropdown."""
    return list(POPULAR_VOICES)


def list_all_voices() -> list[dict]:
    """Live fetch from Microsoft's voice catalog. Used when the user wants
    to browse beyond POPULAR_VOICES (e.g. some less common language)."""
    try:
        import edge_tts
    except ImportError:
        return []
    return _run_async(edge_tts.list_voices())


def fetch_voice_catalog() -> list:
    """Pull the live Edge voice catalog and convert to TTSVoice records
    consumed by core.ai.tts_voice. Imports tts_voice lazily so the
    catalog module doesn't have to import every provider eagerly.

    Microsoft's list_voices() returns dicts shaped like:
      {
        "Name":         "Microsoft Server Speech ... (zh-CN, XiaoxiaoNeural)",
        "ShortName":    "zh-CN-XiaoxiaoNeural",
        "Gender":       "Female",
        "Locale":       "zh-CN",
        "FriendlyName": "Microsoft Xiaoxiao Online (Natural) - Chinese ...",
        "Status":       "GA",
        "VoiceTag":     {"ContentCategories": ["News","Novel"],
                         "VoicePersonalities": ["Warm"]},
      }

    Map:
      voice_id     = ShortName  (what synthesize() expects)
      display_name = trimmed FriendlyName
      language     = Locale
      gender       = "F" / "M" (Edge only emits Female / Male today)
      tags         = ContentCategories + VoicePersonalities
      description  = Name (the long verbose form)
    """
    from core.ai.tts_voice import TTSVoice
    raw = list_all_voices()
    out: list[TTSVoice] = []
    for v in raw:
        gender_raw = v.get("Gender", "")
        gender = "F" if gender_raw == "Female" else "M" if gender_raw == "Male" else ""
        tag_block = v.get("VoiceTag") or {}
        tags = tuple(
            list(tag_block.get("ContentCategories", []))
            + list(tag_block.get("VoicePersonalities", []))
        )
        # FriendlyName is the most human-readable surface; trim the noisy
        # "Microsoft" / "Online (Natural)" boilerplate so the picker
        # column stays narrow.
        friendly = v.get("FriendlyName") or v.get("ShortName", "")
        display = (friendly
                   .replace("Microsoft ", "")
                   .replace(" Online (Natural)", "")
                   .strip())
        out.append(TTSVoice(
            provider="edge_tts",
            voice_id=v.get("ShortName", ""),
            display_name=display,
            language=v.get("Locale", ""),
            gender=gender,
            tags=tags,
            description=v.get("Name", ""),
        ))
    return out
