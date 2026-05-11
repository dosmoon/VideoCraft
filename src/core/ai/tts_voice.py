"""TTS voice catalog — provider-agnostic voice metadata + on-disk cache.

Each TTS provider exposes a different voice concept:
  - edge_tts:   ~322 named voices with rich metadata (Locale, Gender,
                ContentCategories, VoicePersonalities)
  - fish_audio: user's cloned voices from their fish.audio account,
                fetched via authenticated API
  - aistack:    voices depend on the gateway-side TTS backend

This module abstracts that into one TTSVoice dataclass and a lazy
disk-backed catalog at user_data/voice_catalog/<provider>.json. UI
surfaces (VoicePickerDialog, TTS tab status cards) consume the unified
shape without knowing per-provider quirks.

Catalogs are NOT fetched at import time — get_catalog(provider) reads
disk first, only hitting the network when refresh=True (or no cache
exists). Refresh is triggered explicitly by user clicks in the TTS tab.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass

from core.user_data import user_data_dir


@dataclass(frozen=True)
class TTSVoice:
    """A single voice exposed by a TTS provider.

    `voice_id` is the literal string the provider's synthesize() expects —
    Microsoft Edge short-name (e.g. "zh-CN-XiaoxiaoNeural"), fish.audio's
    32-char hex, aistack's named voice (e.g. "vivian"). Anything else is
    metadata for the picker UI.
    """
    provider:     str
    voice_id:     str
    display_name: str
    language:     str             # BCP-47, e.g. "zh-CN" / "en-US" / "yue-CN"
    gender:       str             # "F" | "M" | "" (unknown / non-binary)
    tags:         tuple[str, ...] = ()    # e.g. ("News", "Warm", "Cheerful")
    description:  str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TTSVoice":
        return cls(
            provider=d.get("provider", ""),
            voice_id=d.get("voice_id", ""),
            display_name=d.get("display_name", ""),
            language=d.get("language", ""),
            gender=d.get("gender", ""),
            tags=tuple(d.get("tags", ())),
            description=d.get("description", ""),
        )


# ── Disk layout ──────────────────────────────────────────────────────────────

_CATALOG_FILE_VERSION = 1


def _catalog_root() -> str:
    """user_data/voice_catalog/, created on demand."""
    root = os.path.join(user_data_dir(), "voice_catalog")
    os.makedirs(root, exist_ok=True)
    return root


def _catalog_path(provider: str) -> str:
    return os.path.join(_catalog_root(), f"{provider}.json")


def _extras_path(provider: str) -> str:
    """Sidecar JSON of voice IDs the user marked / favorited on the
    provider's web app. Currently only fish_audio uses this — Fish v1
    API has no "list my marks" endpoint, so we keep a local list and
    fetch metadata for each ID at refresh time."""
    return os.path.join(_catalog_root(), f"{provider}_extras.json")


def get_extra_voice_ids(provider: str) -> list[str]:
    """Read the sidecar list of marked IDs for `provider`. Returns []
    when the sidecar doesn't exist yet."""
    path = _extras_path(provider)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [str(x) for x in (data.get("voice_ids") or []) if x]
    except (OSError, json.JSONDecodeError):
        return []


def set_extra_voice_ids(provider: str, voice_ids: list[str]) -> None:
    """Persist the sidecar list. Caller is responsible for triggering
    a catalog refresh afterwards (so the new IDs get fetched)."""
    path = _extras_path(provider)
    cleaned = sorted({v.strip() for v in voice_ids if v and v.strip()})
    payload = {"version": 1, "voice_ids": cleaned}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ── Public API ───────────────────────────────────────────────────────────────

def get_catalog(provider: str, *, refresh: bool = False) -> list[TTSVoice]:
    """Return cached voice list for `provider`.

    Reads disk by default. When refresh=True (or no cache exists yet),
    calls the provider's fetch_voice_catalog() and writes the fresh
    list to disk. On fetch failure with an existing cache, falls back
    to the cache silently — UI shows last-refresh age so the user can
    notice staleness.

    Returns [] when the provider has no catalog adapter implemented yet
    (e.g. fish_audio / aistack pre-P6).
    """
    path = _catalog_path(provider)
    if refresh or not os.path.exists(path):
        fetched = _fetch(provider)
        if fetched is not None:
            _save_to_disk(path, fetched)
            return fetched
        # Fetch failed or unsupported — fall through to disk if we have
        # a previous snapshot, else return empty.
    if os.path.exists(path):
        return _load_from_disk(path)
    return []


def get_catalog_meta(provider: str) -> dict:
    """Return {count, last_refresh_ts, has_cache} for the TTS tab status
    cards. last_refresh_ts is a UNIX timestamp (0 when no cache); UI
    side formats it via tr() so the wording stays localized.
    """
    path = _catalog_path(provider)
    if not os.path.exists(path):
        return {"count": 0, "last_refresh_ts": 0.0, "has_cache": False}
    try:
        mtime = os.path.getmtime(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "count": len(data.get("voices", [])),
            "last_refresh_ts": mtime,
            "has_cache": True,
        }
    except (OSError, json.JSONDecodeError):
        return {"count": 0, "last_refresh_ts": 0.0, "has_cache": False}


def find_voice(provider: str, voice_id: str) -> TTSVoice | None:
    """Look up a single voice by ID in the cached catalog. Returns None
    when the catalog is empty or the ID isn't found — caller decides
    whether to surface as "unknown voice" or treat as a raw passthrough.
    """
    for v in get_catalog(provider):
        if v.voice_id == voice_id:
            return v
    return None


# ── Internal ─────────────────────────────────────────────────────────────────

def _load_from_disk(path: str) -> list[TTSVoice]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [TTSVoice.from_dict(d) for d in data.get("voices", [])]
    except (OSError, json.JSONDecodeError):
        return []


def _save_to_disk(path: str, voices: list[TTSVoice]) -> None:
    payload = {
        "version":    _CATALOG_FILE_VERSION,
        "fetched_at": time.time(),
        "voices":     [v.to_dict() for v in voices],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _fetch(provider: str) -> list[TTSVoice] | None:
    """Dispatch to the named provider's catalog adapter. Returns None
    when the provider has no adapter yet OR when the fetch raised — in
    both cases the caller falls back to disk.

    fish_audio needs an API key, loaded from keys/FishAudio.key via
    core.ai.config.read_key(). Without a key the adapter returns []
    (an empty catalog, not None — there's nothing to retry on disk).
    """
    try:
        if provider == "edge_tts":
            from core.ai.providers import edge_tts as _edge
            return _edge.fetch_voice_catalog()
        if provider == "fish_audio":
            from core.ai.providers import fish_audio as _fish
            from core.ai import config as _cfg
            from core.ai.router import router as _router
            cfg = _router._tts_providers.get("fish_audio", {}) or {}
            api_key = _cfg.read_key(cfg)
            extras = tuple(get_extra_voice_ids("fish_audio"))
            return _fish.fetch_voice_catalog(
                api_key=api_key, extra_voice_ids=extras)
        if provider == "aistack":
            from core.ai.providers import aistack as _aistack
            from core.ai.router import router as _router
            gw = _router.get_aistack_gateway()
            return _aistack.fetch_voice_catalog(base_url=gw.get("base_url"))
        return None
    except Exception:
        return None
