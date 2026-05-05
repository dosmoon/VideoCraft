"""Filesystem path resolvers for VideoCraft runtime artefacts.

Currently owns one resolver: `models_dir()` — the root for all locally
downloaded ML model weights (HuggingFace hub, NeMo, torch hub).

Read order, first non-empty wins:
  1. `models_dir` field in keys/providers.json (user override via AI Console)
  2. `<repo>/user_data/models/` (default — keeps Portable install self-contained)

Kept dependency-free on purpose: the startup hook in VideoCraftHub.py must
call this BEFORE importing torch / huggingface_hub / nemo, so we cannot
pull in core.ai (which transitively imports the OpenAI SDK).
"""

from __future__ import annotations

import json
import os

from core.user_data import user_data_dir


def _providers_json_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # src/core -> src -> <repo root>
    root = os.path.normpath(os.path.join(here, "..", ".."))
    return os.path.join(root, "keys", "providers.json")


def _read_models_dir_override() -> str | None:
    """Best-effort read of `models_dir` from providers.json. Returns None
    if file missing, malformed, or field empty/unset. Never raises."""
    path = _providers_json_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get("models_dir")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def models_dir() -> str:
    """Return absolute path to the model cache root, creating it on demand.

    Subdirectories used by the startup env-var hook:
        hf/         HF_HOME (huggingface_hub + transformers + faster-whisper)
        hf/hub/     HF_HUB_CACHE (explicit hub override; HF_HOME normally
                    derives this, but newer huggingface_hub respects
                    HF_HUB_CACHE first)
        torch/      TORCH_HOME (torch.hub.load weights)
        nemo/       NEMO_CACHE_DIR (NVIDIA NeMo checkpoint cache)
    """
    override = _read_models_dir_override()
    root = override or os.path.join(user_data_dir(), "models")
    os.makedirs(root, exist_ok=True)
    return root


def cache_subdir(name: str) -> str:
    """Return <models_dir>/<name>, creating it on demand."""
    p = os.path.join(models_dir(), name)
    os.makedirs(p, exist_ok=True)
    return p


# ── Startup env-var hook ─────────────────────────────────────────────────────

# Maps env var → subdir under models_dir(). Set in apply_cache_env() ONCE at
# process start, before any heavy ML import. Existing values in the
# environment win (so power users can still point HF_HOME at a shared pool
# via OS env).
_CACHE_ENV_MAP = {
    # HF_HOME is the modern HuggingFace root — transformers / huggingface_hub /
    # datasets / faster-whisper all derive their caches from it. Avoid setting
    # the legacy TRANSFORMERS_CACHE: transformers ≥ 4.42 deprecates it and
    # warns at import.
    "HF_HOME":        "hf",
    "HF_HUB_CACHE":   "hf/hub",
    "TORCH_HOME":     "torch",
    "NEMO_CACHE_DIR": "nemo",
}


def apply_cache_env() -> dict[str, str]:
    """Set ML cache env vars to subdirs under models_dir().

    Idempotent: already-set vars in os.environ are left alone (so OS-level
    overrides win). Returns a dict of {var: resolved_path} for what this
    call set, useful for logging / debugging.
    """
    root = models_dir()
    applied = {}
    for var, sub in _CACHE_ENV_MAP.items():
        if os.environ.get(var):
            continue
        target = os.path.join(root, *sub.split("/"))
        os.makedirs(target, exist_ok=True)
        os.environ[var] = target
        applied[var] = target
    return applied


# ── Legacy cache detection (informational only) ─────────────────────────────

_LEGACY_HF_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "huggingface")


def detect_legacy_hf_cache() -> tuple[str, int] | None:
    """Return (path, size_bytes) if the default ~/.cache/huggingface exists
    and is non-empty, else None. The AI Console renders a banner from this
    so users know they have stale weights they can manually reclaim.

    Size walk is best-effort: errors during traversal are swallowed and
    accumulated bytes returned anyway.
    """
    if not os.path.isdir(_LEGACY_HF_CACHE):
        return None
    total = 0
    for dirpath, _dirnames, filenames in os.walk(_LEGACY_HF_CACHE):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    if total <= 0:
        return None
    return _LEGACY_HF_CACHE, total
