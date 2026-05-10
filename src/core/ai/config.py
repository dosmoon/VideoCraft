"""Configuration defaults, key file I/O, and providers.json persistence.

Split out from AIRouter so the router only orchestrates runtime state; this
module owns the on-disk format and provider catalog defaults.

Path resolution: `keys_dir()` walks up from this file's location to the
project root, then into `keys/`. Original code in src/ai_router.py went up
one level; since we're now at src/core/ai/config.py, we go up three levels.
"""

import os
import copy
import json

from core.ai.tiers import TIER_PREMIUM, TIER_STANDARD, TIER_ECONOMY


# ── Default LLM providers ────────────────────────────────────────────────────
# Provider keys must match the names used in providers.json and in legacy
# callers (e.g. srt_tools.py's AI_PROVIDERS).

_DEFAULT_PROVIDERS = {
    "Gemini": {
        "type":     "gemini",
        "key_file": "Gemini.key",
        "enabled":  True,
        "priority": 1,
        "models": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ],
        "tiers": {
            TIER_PREMIUM:  "gemini-2.5-pro",
            TIER_STANDARD: "gemini-2.5-flash",
            TIER_ECONOMY:  "gemini-2.5-flash-lite",
        },
    },
    "DeepSeek": {
        "type":     "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "key_file": "DeepSeek.key",
        "enabled":  True,
        "priority": 2,
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "tiers": {
            TIER_PREMIUM:  "deepseek-reasoner",
            TIER_STANDARD: "deepseek-chat",
            TIER_ECONOMY:  "deepseek-chat",
        },
    },
    "Custom": {
        "type":     "openai_compatible",
        "base_url": "",
        "key_file": "Custom.key",
        "enabled":  False,      # Disabled by default; user fills base_url via UI first
        "priority": 4,
        "models":   [],
        "tiers": {
            TIER_PREMIUM:  "",
            TIER_STANDARD: "",
            TIER_ECONOMY:  "",
        },
    },
    "ClaudeCode": {
        "type":       "claude_code",
        "key_file":   "",           # No API key — local `claude` CLI handles auth
        "enabled":    False,        # Off by default; user ticks Enable in Router Manager
        "priority":   3,            # Between DeepSeek(2) and Custom(4)
        "executable": "claude",     # CLI binary name or full path
        "extra_args": [],           # Advanced: additional flags for `claude -p`
        "timeout_sec": 600,
        "models": [
            "sonnet",
            "opus",
            "haiku",
        ],
        "tiers": {
            TIER_PREMIUM:  "opus",
            TIER_STANDARD: "sonnet",
            TIER_ECONOMY:  "haiku",
        },
    },
    "aistack": {
        "type":          "openai_compatible",
        "base_url":      "http://127.0.0.1:11500/v1",
        "key_file":      "",            # Local gateway — no API key
        "auth_required": False,         # Skip key check at dispatch time
        "enabled":       True,          # Default-on; same posture as ASR/TTS aistack entries
        "priority":      5,             # After Custom(4)
        "models":        [],            # Populated via "Pick Models" → /v1/models
        "tiers": {
            TIER_PREMIUM:  "",
            TIER_STANDARD: "",
            TIER_ECONOMY:  "",
        },
    },
    "LlamaCpp": {
        "type":          "llama_cpp",
        "key_file":      "",            # In-process — no API key
        "auth_required": False,
        "enabled":       True,          # Available as soon as user drops a .gguf in
        "priority":      6,             # Last in tier-fallback order; aistack/cloud win when configured
        "n_ctx":         8192,
        "n_gpu_layers":  0,             # CPU default; user opts into GPU build separately
        "n_threads":     4,
        "models":        [],            # Populated by "Refresh Models" → providers/llama_cpp.list_models()
        "tiers": {
            TIER_PREMIUM:  "",
            TIER_STANDARD: "",
            TIER_ECONOMY:  "",
        },
    },
}

# Tier-based routing was retired 2026-05-06: users now pick (provider, model)
# per task in the AI Console matrix (task_routing). The TIER_* constants in
# core.ai.tiers are still used internally by feature-layer callers that pass
# `tier=` for backward compatibility, but no default tier_routing dict is
# seeded into config any more.

# ── Default ASR providers ────────────────────────────────────────────────────
# Kept separate from LLM providers to avoid mixing tier-routing logic.

_DEFAULT_ASR_PROVIDERS = {
    "lemonfox": {
        "name":        "LemonFox",
        "enabled":     True,
        "key_file":    "lemonfox.key",
        "base_url":    "https://api.lemonfox.ai/v1/audio/transcriptions",
        "description": "LemonFox Whisper ASR API",
        "connect_timeout_sec": 60,
        "read_timeout_sec": 120,
        "max_retries": 1,
    },
    "aistack": {
        "name":          "aistack (本地)",
        "enabled":       True,
        "key_file":      "",            # Local service — no API key
        "base_url":      "http://127.0.0.1:11500",
        "auth_required": False,
        "description":   "本地 AI 服务 (github.com/dosmoon/aistack);model 字段决定后端: whisper-{tiny,base,small,medium,large-v3,large-v3-turbo} / parakeet / sensevoice",
        "model":         "whisper-small",
    },
    "sherpa": {
        "name":          "sherpa-onnx (内嵌)",
        "enabled":       True,
        "key_file":      "",            # In-process — no API key
        "auth_required": False,
        "description":   "内嵌 sherpa-onnx Whisper int8 (CPU);模型: <models>/sherpa/whisper-small/;无需 Docker 或云服务",
        "model":         "whisper-small",
    },
}

# ── Default TTS providers ────────────────────────────────────────────────────
# TTS needs no tier routing — just key management.

_DEFAULT_TTS_PROVIDERS = {
    "fish_audio": {
        "name":        "Fish Audio",
        "enabled":     True,
        "key_file":    "FishAudio.key",
        "description": "Fish Audio TTS — 支持音色克隆与多角色合成",
    },
    "aistack": {
        "name":          "aistack (本地 Qwen3-TTS)",
        "enabled":       True,
        "key_file":      "",            # Local service — no API key
        "base_url":      "http://127.0.0.1:11500",
        "auth_required": False,
        "description":   "本地 TTS via aistack — Qwen3-TTS-0.6B over vLLM-Omni docker sidecar",
        "model":         "qwen3-tts-12hz-0.6b-customvoice",
        "voice":         "vivian",
        "language":      "English",
        "task_type":     "CustomVoice",
    },
}

# ── Task catalog (function × tier routing) ──────────────────────────────────
# Each entry is (task_id, category, display_label). `category` drives which
# provider pool is applicable when a user picks a cell in the matrix:
#   "llm" — any LLM provider (Gemini / DeepSeek / Custom / ClaudeCode)
#   "asr" — any ASR provider (Lemonfox / future)
#   "tts" — any TTS provider (Fish Audio / future)
# Phase 1 defines the canonical task list; features that add new tasks
# (e.g. vision.ocr) register them by appending here.

TASKS: list[tuple[str, str, str]] = [
    ("translate",         "llm", "翻译 / Translate"),
    ("subtitle.post",     "llm", "字幕后处理 / Subtitle post-process"),
    ("asr.transcribe",    "asr", "语音转字幕 / ASR"),
    ("tts.synthesize",    "tts", "文本转语音 / TTS"),
]


def task_category(task_id: str) -> str | None:
    """Return 'llm' | 'asr' | 'tts' | None for a given task_id."""
    for tid, cat, _label in TASKS:
        if tid == task_id:
            return cat
    return None


# ── Default task routing ─────────────────────────────────────────────────────
# Flat schema: {task_id: {"provider": str, "model": str}}.
# Earlier versions had a 3-tier nested layer (premium/standard/economy); the
# layer was retired once the UI let users pick a specific model per task. LLM
# tasks default to an empty cell so the candidate-pool auto-fallback kicks
# in until the user explicitly configures a preference in the AI Console.

def _build_default_task_routing() -> dict:
    llm_seed = {"provider": "", "model": ""}
    asr_seed = {"provider": "lemonfox",  "model": ""}
    tts_seed = {"provider": "fish_audio", "model": ""}
    out = {}
    for tid, cat, _label in TASKS:
        if cat == "llm":
            out[tid] = copy.deepcopy(llm_seed)
        elif cat == "asr":
            out[tid] = copy.deepcopy(asr_seed)
        elif cat == "tts":
            out[tid] = copy.deepcopy(tts_seed)
    return out


# ── Legacy name normalization ────────────────────────────────────────────────
# SrtTools used Chinese provider names historically; map them to canonical.

_COMPAT_NAMES = {
    "自定义(OpenAI兼容)": "Custom",
}


def canonicalize_provider_name(name: str) -> str:
    """Map legacy Chinese provider names to canonical English."""
    return _COMPAT_NAMES.get(name, name)


def keys_dir() -> str:
    """Return absolute path to the repo's keys/ directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    # src/core/ai -> src/core -> src -> <repo root>
    return os.path.normpath(os.path.join(here, "..", "..", "..", "keys"))


def read_key(provider_cfg: dict) -> str | None:
    """Read provider's .key file. Returns None if key_file empty/missing/blank."""
    key_file = provider_cfg.get("key_file", "")
    if not key_file:
        return None
    key_path = os.path.join(keys_dir(), key_file)
    if not os.path.exists(key_path):
        return None
    with open(key_path, "r", encoding="utf-8") as f:
        key = f.read().strip()
    return key or None


def has_auth(provider_cfg: dict) -> bool:
    """True if provider has credentials to run. claude_code relies on the
    local CLI's own login state — presence of the entry is enough.
    Providers with `auth_required: False` (e.g. Ollama on localhost) skip
    the key check entirely.
    """
    if provider_cfg.get("type") == "claude_code":
        return True
    if provider_cfg.get("auth_required") is False:
        return True
    return read_key(provider_cfg) is not None


# ── Persistence ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load providers.json, applying defaults + migrations. Writes back on
    first run or when schema migration triggered a fix.

    Returns dict with keys: providers / asr_providers / tts_providers /
    task_routing / models_dir. The legacy `tier_routing` field is dropped
    on load if the on-disk file still has it.
    """
    cfg_path = os.path.join(keys_dir(), "providers.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        providers     = data.get("providers",     {})
        asr_providers = data.get("asr_providers", copy.deepcopy(_DEFAULT_ASR_PROVIDERS))
        tts_providers = data.get("tts_providers", copy.deepcopy(_DEFAULT_TTS_PROVIDERS))
        task_routing  = data.get("task_routing")
        models_dir    = data.get("models_dir", "")
        models_dir_dirty = "models_dir" not in data
        # Drop the retired tier_routing field; flag dirty so the cleanup
        # is persisted on first load after upgrade.
        tier_routing_dropped = "tier_routing" in data
        wrote_on_first_run = False
    else:
        providers     = copy.deepcopy(_DEFAULT_PROVIDERS)
        asr_providers = copy.deepcopy(_DEFAULT_ASR_PROVIDERS)
        tts_providers = copy.deepcopy(_DEFAULT_TTS_PROVIDERS)
        task_routing  = None
        models_dir    = ""
        models_dir_dirty = False
        tier_routing_dropped = False
        wrote_on_first_run = True
        # First-run write happens below after migrations run

    providers, migrated = _migrate_removed_providers(providers)
    providers, normalized = _normalize_providers(providers)
    asr_providers, task_routing, asr_migrated = _migrate_removed_asr_providers(
        asr_providers, task_routing
    )
    asr_providers = _normalize_asr_providers(asr_providers)
    tts_providers, tts_normalized = _normalize_tts_providers(tts_providers)
    task_routing, task_routing_dirty = _migrate_task_routing(task_routing)

    result = {
        "providers":     providers,
        "asr_providers": asr_providers,
        "tts_providers": tts_providers,
        "task_routing":  task_routing,
        "models_dir":    models_dir,
    }

    if (wrote_on_first_run or migrated or asr_migrated or normalized
            or tts_normalized or task_routing_dirty or models_dir_dirty
            or tier_routing_dropped):
        save_config(result)

    return result


def save_config(data: dict) -> None:
    """Write providers.json. Creates the keys/ directory if missing."""
    cfg_path = os.path.join(keys_dir(), "providers.json")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "models_dir":    data.get("models_dir", ""),
            "task_routing":  data.get("task_routing", {}),
            "providers":     data["providers"],
            "asr_providers": data["asr_providers"],
            "tts_providers": data["tts_providers"],
        }, f, ensure_ascii=False, indent=2)


# ── Schema migrations ────────────────────────────────────────────────────────

def _migrate_removed_providers(providers: dict):
    """Drop providers that were removed in newer versions.

    Groq was removed because its Llama/gpt-oss/qwen models did not meet
    VideoCraft's NLP quality bar. Ollama was removed 2026-05-06 when the
    aistack gateway took over local-LLM dispatch — its base_url moved
    from 11434 to 11500/v1, and the user's old `models` list does not
    transfer (aistack publishes its own inventory via /v1/models, which
    the user re-picks via the Pick Models button).
    """
    removed = ["Groq", "Ollama"]
    dirty = False
    for name in removed:
        if name in providers:
            providers.pop(name, None)
            dirty = True
    return providers, dirty


def _normalize_providers(providers: dict):
    """Backfill provider entries added in newer versions (e.g. ClaudeCode).

    Users upgrading from a previous release would otherwise not see newly
    introduced providers in their Router Manager because their providers.json
    only carries the providers that existed when it was written.
    """
    dirty = False
    for name, default_cfg in _DEFAULT_PROVIDERS.items():
        if name not in providers:
            providers[name] = copy.deepcopy(default_cfg)
            dirty = True
    return providers, dirty


def _normalize_asr_providers(asr_providers: dict) -> dict:
    """Backfill missing fields on ASR providers for backward compat."""
    for name, default_cfg in _DEFAULT_ASR_PROVIDERS.items():
        current = asr_providers.setdefault(name, copy.deepcopy(default_cfg))
        for key, value in default_cfg.items():
            current.setdefault(key, value)
    return asr_providers


def _normalize_tts_providers(tts_providers: dict) -> tuple[dict, bool]:
    """Backfill missing TTS providers (e.g. the aistack entry added 2026-05-06)
    and missing fields on existing entries.
    """
    dirty = False
    for name, default_cfg in _DEFAULT_TTS_PROVIDERS.items():
        if name not in tts_providers:
            tts_providers[name] = copy.deepcopy(default_cfg)
            dirty = True
        else:
            current = tts_providers[name]
            for key, value in default_cfg.items():
                if key not in current:
                    current[key] = value
                    dirty = True
    return tts_providers, dirty


def _migrate_removed_asr_providers(
    asr_providers: dict, task_routing: dict | None
) -> tuple[dict, dict | None, bool]:
    """Drop ASR providers removed in newer versions and redirect references.

    On 2026-05-06 the in-process providers (faster_whisper, parakeet,
    sensevoice) were extracted into the sibling aistack service
    (github.com/dosmoon/aistack). User configs carrying those entries
    are cleaned here; task_routing slots that pointed at them are
    redirected to 'aistack'.
    """
    removed = {"faster_whisper", "parakeet", "sensevoice"}
    redirect_to = "aistack"
    dirty = False

    for name in list(asr_providers.keys()):
        if name in removed:
            asr_providers.pop(name, None)
            dirty = True

    if task_routing:
        for cell in task_routing.values():
            if not isinstance(cell, dict):
                continue
            if cell.get("provider") in removed:
                cell["provider"] = redirect_to
                cell["model"] = ""
                dirty = True

    return asr_providers, task_routing, dirty


def _migrate_task_routing(task_routing: dict | None) -> tuple[dict, bool]:
    """Build / backfill / collapse task_routing.

    Three cases handled:
    1. task_routing is None (very first load): seed via defaults.
    2. Old 3-tier nested structure detected (M6 era):
       collapse {task: {tier: {p, m}}} → {task: {p, m}} taking standard
       (or premium / economy as fallback).
    3. New flat structure missing a task: backfill from defaults.

    Returns (fixed_dict, dirty_flag).
    """
    dirty = False

    if task_routing is None:
        return _build_default_task_routing(), True

    # Collapse the legacy three subtitle.* entries into the consolidated
    # `subtitle.post` task. If the user already customized any of them, the
    # first non-empty cell wins; the old keys are then removed from disk.
    legacy_subtitle_keys = ("subtitle.segments", "subtitle.refine",
                            "subtitle.titles")
    if any(k in task_routing for k in legacy_subtitle_keys):
        if "subtitle.post" not in task_routing:
            for k in legacy_subtitle_keys:
                cell = task_routing.get(k)
                if isinstance(cell, dict) and cell.get("provider"):
                    task_routing["subtitle.post"] = copy.deepcopy(cell)
                    break
        for k in legacy_subtitle_keys:
            task_routing.pop(k, None)
        dirty = True

    # Detect + collapse old 3-tier nested structure
    flattened: dict = {}
    for tid, value in task_routing.items():
        if isinstance(value, dict) and any(t in value for t in (TIER_PREMIUM, TIER_STANDARD, TIER_ECONOMY)):
            # Old structure: pick standard, fall back to premium / economy
            cell = (value.get(TIER_STANDARD)
                    or value.get(TIER_PREMIUM)
                    or value.get(TIER_ECONOMY)
                    or {})
            flattened[tid] = copy.deepcopy(cell)
            dirty = True
        else:
            flattened[tid] = value

    # Backfill any task that isn't present
    defaults = _build_default_task_routing()
    for tid, cat, _label in TASKS:
        if tid not in flattened or not isinstance(flattened.get(tid), dict):
            flattened[tid] = copy.deepcopy(defaults[tid])
            dirty = True
        else:
            # Ensure both keys exist
            cell = flattened[tid]
            if "provider" not in cell:
                cell["provider"] = defaults[tid]["provider"]
                dirty = True
            if "model" not in cell:
                cell["model"] = defaults[tid]["model"]
                dirty = True
            # 2026-05-06 Phase 2b: language_routing mechanism retired.
            # aistack now owns ASR auto-routing by language hint, so the
            # per-task language_routing map and its master switch are
            # stripped from any legacy cell that still carries them.
            for legacy_key in ("language_routing", "language_routing_enabled"):
                if legacy_key in cell:
                    cell.pop(legacy_key, None)
                    dirty = True
            # 2026-05-06 Phase 2b: legacy Ollama LLM provider entries get
            # redirected to the aistack gateway (which now proxies Ollama
            # via /v1/chat/completions). The model field is cleared because
            # the user's old Ollama model list does not transfer; they
            # re-pick from aistack's /v1/models inventory.
            if cell.get("provider") == "Ollama":
                cell["provider"] = "aistack"
                cell["model"] = ""
                dirty = True

    return flattened, dirty
