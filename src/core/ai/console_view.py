"""Pure, UI-free read model for the AI Console (provider routing / keys / stats).

The provider-tier classification and key-status logic historically lived inside
the Tk console (tools/router/ai_console.py). This module lifts that logic into a
reusable, UI-free shape so the Electron renderer (via the core_rpc `ai.*`
methods) and — eventually — the Tk console can both render from one source.

It returns STRUCTURED DATA ONLY: no i18n strings, no colors. Enums the front-end
maps to localized labels:
  - `deploy_tier`  ∈ {local, free_online, aistack, cloud}
  - `key_status.state` ∈ {cli, no_key_needed, not_configured, empty, ok}
  - routing tier ids ∈ {embedded, cloud, aistack, auto}

Read-only. Write operations (set key / set routing / test connection) land in a
later slice as separate `ai.*` methods.
"""

from __future__ import annotations

import os

from core.ai import config as _cfg
from core.ai.router import router

# Deploy-tier classification — mirrors ai_console._classify_provider_tier /
# _LOCAL_PROVIDER_NAMES / _FREE_ONLINE_PROVIDER_NAMES (the UI's real grouping,
# not the engine registry — see [[feedback_ui_menu_from_tk_not_engine]]).
_LOCAL_PROVIDERS = frozenset({"LlamaCpp", "faster_whisper"})
_FREE_ONLINE_PROVIDERS = frozenset({"edge_tts"})

# Routing tiers per category — mirrors ai_console._ROUTING_TIERS_*. LLM has an
# extra "auto" (candidate-pool fallback); ASR/TTS do not.
ROUTING_TIERS_LLM = ("embedded", "cloud", "aistack", "auto")
ROUTING_TIERS_NON_LLM = ("embedded", "cloud", "aistack")


def classify_deploy_tier(name: str) -> str:
    """Return one of: 'local' | 'free_online' | 'aistack' | 'cloud'."""
    if name == "aistack":
        return "aistack"
    if name in _LOCAL_PROVIDERS:
        return "local"
    if name in _FREE_ONLINE_PROVIDERS:
        return "free_online"
    return "cloud"


def _key_status(cfg: dict) -> dict:
    """Structured key state for a provider — {state, masked}. Mirrors
    ai_console._key_status but returns an enum + masked key instead of i18n text
    + color (the renderer localizes)."""
    if cfg.get("type") == "claude_code":
        return {"state": "cli", "masked": None}
    key_file = cfg.get("key_file", "")
    if not key_file:
        return {"state": "no_key_needed", "masked": None}
    key_path = os.path.join(_cfg.keys_dir(), key_file)
    if not os.path.exists(key_path):
        return {"state": "not_configured", "masked": None}
    with open(key_path, "r", encoding="utf-8") as f:
        key = f.read().strip()
    if not key:
        return {"state": "empty", "masked": None}
    masked = key[:4] + "****" + key[-4:] if len(key) >= 8 else "****"
    return {"state": "ok", "masked": masked}


def _models_list(name: str, cfg: dict) -> list[str]:
    """The model list for a provider's routing dropdown. Embedded providers scan
    disk (so a model installed via the model manager appears immediately, matching
    the Tk faster_whisper behaviour and fixing LlamaCpp's stale static list); cloud
    providers use their configured `models` (dict of quality tiers, or a list)."""
    if cfg.get("type") == "llama_cpp":
        from core.ai.providers import llama_cpp

        return llama_cpp.list_models()
    if name == "faster_whisper":
        from core.ai.providers import faster_whisper

        return faster_whisper.list_models()
    models = cfg.get("models")
    if isinstance(models, dict):
        return [str(m) for m in models.values() if m]
    if isinstance(models, list):
        return [str(m) for m in models]
    return []


# Per-provider editable extras the Console's Edit panel exposes (beyond key /
# base_url / models). Surfaced in `settings` and accepted by update_provider.
_EXTRA_SETTINGS = ("executable", "timeout_sec", "connect_timeout_sec", "read_timeout_sec", "max_retries")


def _provider_view(name: str, cfg: dict, category: str) -> dict:
    """One provider row, normalized. `needs_key` = has a key_file (so the UI can
    distinguish 'not_configured' (actionable) from 'no_key_needed' (local).
    `base_url` is "" unless the provider has one (openai_compatible); `settings`
    carries the editable extras present on this provider (timeouts, etc.)."""
    return {
        "name": name,
        "category": category,
        "deploy_tier": classify_deploy_tier(name),
        "type": cfg.get("type", ""),
        "enabled": bool(cfg.get("enabled", True)),
        "needs_key": bool(cfg.get("key_file")),
        "has_auth": _cfg.has_auth(cfg),
        "key_status": _key_status(cfg),
        "base_url": cfg.get("base_url", ""),
        "models": _models_list(name, cfg),
        "settings": {k: cfg[k] for k in _EXTRA_SETTINGS if k in cfg},
    }


def snapshot() -> dict:
    """Full read-only state for the AI Console (everything but live model probes
    and per-call stats — the latter is `stats()`, refreshed on its own)."""
    tasks = [{"id": tid, "category": cat, "label": label} for tid, cat, label in _cfg.TASKS]

    # Per-(task, tier) sticky picks the user has configured (sparse — only set
    # cells). Built from router.get_task_tier_pref since there's no bulk getter.
    prefs: dict[str, dict] = {}
    for tid, cat, _label in _cfg.TASKS:
        tiers = ROUTING_TIERS_LLM if cat == "llm" else ROUTING_TIERS_NON_LLM
        cell = {}
        for tier in tiers:
            pref = router.get_task_tier_pref(tid, tier)
            if pref:
                cell[tier] = pref
        if cell:
            prefs[tid] = cell

    providers = {
        "llm": [_provider_view(n, c, "llm") for n, c in router._providers.items()],
        "asr": [_provider_view(n, c, "asr") for n, c in router._asr_providers.items()],
        "tts": [_provider_view(n, c, "tts") for n, c in router._tts_providers.items()],
    }

    gw = router.get_aistack_gateway()
    return {
        "tasks": tasks,
        "routing_tiers": {
            "llm": list(ROUTING_TIERS_LLM),
            "non_llm": list(ROUTING_TIERS_NON_LLM),
        },
        "task_routing": router.get_task_routing(),
        "task_tier_prefs": prefs,
        "providers": providers,
        "aistack": {
            "base_url": gw["base_url"],
            "enabled": gw["enabled"],
            "models_cache": router.get_aistack_models_cache(),
        },
    }


def stats() -> dict:
    """Per-provider call counters for the Stats tab —
    {provider: {calls, errors, last_used, ...}} (in-memory, deep-copied)."""
    return router.get_stats()


# ── Write side (config edits; each persists via the router) ───────────────────
# Network actions (LLM test, aistack test & refresh) are NOT here — they block on
# I/O and must run as jobs, not on the dispatch thread.

_CATEGORY_REGISTRY = {
    "llm": "_providers",
    "asr": "_asr_providers",
    "tts": "_tts_providers",
}


def _find_cfg(provider: str, category: str) -> dict | None:
    attr = _CATEGORY_REGISTRY.get(category)
    if not attr:
        return None
    return getattr(router, attr).get(provider)


def set_key(provider: str, category: str, key: str) -> None:
    """Write a cloud provider's API key to keys/<key_file> (plain text, matching
    the Tk console). Raises if the provider is unknown or takes no key."""
    cfg = _find_cfg(provider, category)
    if cfg is None:
        raise ValueError(f"unknown provider {provider!r} in category {category!r}")
    key_file = cfg.get("key_file", "")
    if not key_file:
        raise ValueError(f"provider {provider!r} takes no API key")
    kd = _cfg.keys_dir()
    os.makedirs(kd, exist_ok=True)
    with open(os.path.join(kd, key_file), "w", encoding="utf-8") as f:
        f.write(key.strip())


def set_provider_enabled(provider: str, category: str, enabled: bool) -> None:
    """Enable/disable a provider (the per-row checkbox). Routes to the right
    registry by category; the router persists."""
    if category == "llm":
        router.set_provider_enabled(provider, enabled)
    elif category == "asr":
        router.set_asr_provider_enabled(provider, enabled)
    elif category == "tts":
        router.set_tts_provider_enabled(provider, enabled)
    else:
        raise ValueError(f"unknown category {category!r}")


def set_routing(task: str, provider: str, model: str) -> None:
    """Set a task's ACTIVE routing (the tier radio). Empty provider = Auto."""
    router.set_task_routing(task, provider, model)


def set_tier_pref(task: str, tier: str, provider: str, model: str) -> None:
    """Set a task's per-tier sticky pick (a dropdown change that doesn't move the
    active radio)."""
    router.set_task_tier_pref(task, tier, provider, model)


def set_aistack_gateway(base_url: str, enabled: bool) -> None:
    """Set the aistack gateway URL + enabled (one logical entry across LLM/ASR/
    TTS; the router keeps the three registry copies in sync)."""
    router.set_aistack_gateway(base_url, enabled)


# Editable config keys per category (the Console Edit panel). Mirrors the fields
# the Tk console's per-provider Edit dialog writes (base_url + active models +
# per-provider settings). The API key is a separate path (set_key).
_PATCH_ALLOW = {
    "llm": {"base_url", "models", "executable", "timeout_sec"},
    "asr": {"models", "connect_timeout_sec", "read_timeout_sec", "max_retries"},
    "tts": {"connect_timeout_sec", "read_timeout_sec", "max_retries"},
}


def update_provider(provider: str, category: str, patch: dict) -> None:
    """Apply a config patch to a provider (base_url / models / settings). Only
    whitelisted keys for the category are accepted; the rest are ignored. Raises
    on an unknown provider or an empty effective patch."""
    cfg = _find_cfg(provider, category)
    if cfg is None:
        raise ValueError(f"unknown provider {provider!r} in category {category!r}")
    allow = _PATCH_ALLOW.get(category, set())
    clean = {k: v for k, v in patch.items() if k in allow}
    if not clean:
        raise ValueError(f"no editable fields for category {category!r} in patch")
    if "models" in clean and not isinstance(clean["models"], list):
        raise ValueError("models must be a list")
    if category == "llm":
        router.update_provider(provider, **clean)
    elif category == "asr":
        router.update_asr_provider(provider, **clean)
    else:  # tts
        router.update_tts_provider(provider, **clean)


# ── Network actions (run inside jobs — they block on I/O) ─────────────────────


def test_provider(provider: str, model: str | None = None) -> dict:
    """Send a 1-word probe completion to an LLM provider and report the reply.
    LLM only (the Tk console disables Test for ASR/TTS — they need sample input).
    Raises on auth / network failure (→ job failed)."""
    import core.ai as ai

    reply = ai.complete(
        "Please reply with the single word OK and nothing else.",
        provider=provider,
        model=model or None,
    )
    return {"ok": True, "reply": reply.strip()[:200]}


def test_aistack(base_url: str) -> dict:
    """Hit the aistack gateway's /v1/models, bucket by capability, and (on
    success only) persist the URL + refresh the model cache so the routing tab's
    aistack model dropdowns fill. Mirrors the Tk 'Test & Refresh' action."""
    from core.ai.providers import aistack as _aistack

    bare = base_url.rstrip("/")
    if bare.endswith("/v1"):
        bare = bare[:-3]
    pairs = _aistack.list_models_with_capabilities(bare)
    buckets: dict[str, list[str]] = {"llm": [], "asr": [], "tts": []}
    for mid, caps in pairs:
        for cap in caps:
            if cap in buckets:
                buckets[cap].append(mid)
    enabled = router.get_aistack_gateway()["enabled"]
    router.set_aistack_gateway(base_url, enabled)
    router.set_aistack_models_cache(buckets)
    return {"buckets": buckets, "total": sum(len(v) for v in buckets.values())}


def refresh_models(provider: str) -> dict:
    """Fetch the live model list from an LLM provider's API (does not persist —
    the caller picks + saves via update_provider). LLM only."""
    return {"models": router.list_models(provider)}
