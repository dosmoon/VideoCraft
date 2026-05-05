"""AIRouter — orchestrates provider selection and dispatch.

Replaces the monolithic AIRouter in the old src/ai_router.py. Splits out:
  - configuration defaults + persistence -> core/ai/config.py
  - per-provider API calls              -> core/ai/providers/*.py
  - call statistics                     -> core/ai/stats.py

Phase 1 preserves the full API surface of the old AIRouter so that existing
callers (imported via the `src/ai_router.py` compatibility shim) behave
identically. Phase 7 will add error-kind mapping; Phase 4/5 will fold
ASR/TTS HTTP/SDK calls into core.ai facade functions.
"""

from __future__ import annotations

from core.ai import config as _cfg
from core.ai.providers import gemini as _gemini
from core.ai.providers import openai_compat as _openai_compat
from core.ai.providers import claude_code as _claude_code
from core.ai.providers import lemonfox as _lemonfox
from core.ai.providers import fish_audio as _fish_audio
from core.ai.errors import AIError, Kind
from core.ai.stats import Stats
from core.ai.tiers import (
    TIER_PREMIUM,
    TIER_STANDARD,
    TIER_ECONOMY,
    TIERS,
)


class AIRouter:
    """Process-wide singleton (exposed as `core.ai.router`).

    Thread-safe: multiple worker threads may call complete() concurrently.
    Stats are protected by an internal lock inside the Stats object.
    """

    def __init__(self):
        self._providers:     dict = {}
        self._asr_providers: dict = {}
        self._tts_providers: dict = {}
        self._tier_routing:  dict = {}
        self._task_routing:  dict = {}
        self._stats = Stats()
        self._load_config()

    # ── Core LLM API ─────────────────────────────────────────────────────────

    def complete(self, prompt: str, *,
                 task: str = "",
                 tier: str = TIER_STANDARD,
                 provider: str | None = None,
                 model: str | None = None) -> str:
        """Plain text completion.

        Args:
            prompt:   The user prompt.
            task:     Optional task id (e.g. "translate", "subtitle.refine").
                      When set, routing uses task_routing[task][tier] first,
                      falling back to tier_routing[tier]. Empty string keeps
                      the legacy pure-tier routing path.
            tier:     "premium" | "standard" | "economy". If provider is
                      unset, tier drives routing; if provider is set, tier
                      only chooses the default model within that provider.
            provider: Optional explicit provider name (e.g. "Gemini").
            model:    Optional explicit model ID, overrides tier default.

        Returns:
            Plain-text completion.

        Raises:
            RuntimeError: all candidate providers failed.
        """
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}, got: {tier!r}")

        if provider:
            provider = _cfg.canonicalize_provider_name(provider)
            return self._complete_explicit(provider, tier, model, prompt)
        return self._complete_by_tier(task, tier, model, prompt)

    def complete_json(self, prompt: str, *,
                      schema: dict,
                      task: str = "",
                      tier: str = TIER_STANDARD,
                      provider: str | None = None,
                      model: str | None = None,
                      cancel_token=None) -> dict:
        """Structured JSON completion constrained by `schema`.

        See complete() for `task` semantics.

        The schema is injected by the provider adapter (either as native
        response_schema, or as a system-prompt hint for OpenAI-compat).
        Callers should NOT manually repeat schema instructions in prompt.

        Raises RuntimeError on API failure, JSON parse failure, or when all
        candidate providers have been exhausted.
        """
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}, got: {tier!r}")
        if not isinstance(schema, dict):
            raise ValueError(
                f"schema must be dict, got: {type(schema).__name__}"
            )

        if provider:
            provider = _cfg.canonicalize_provider_name(provider)
            return self._complete_json_explicit(provider, tier, model, prompt,
                                                  schema, cancel_token)
        return self._complete_json_by_tier(task, tier, model, prompt, schema,
                                            cancel_token)

    def describe(self, task: str, tier: str = TIER_STANDARD) -> dict:
        """Return capability metadata for (task, tier).

        Phase 1 stub: returns a placeholder dict so feature-layer code can
        be written against the API shape. Phase 7 will fill real data
        (max_input_tokens, supports_stream, supports_json, etc.).

        Reserved fields (see docs/design/04-ai-router.md):
            max_input_tokens:          int, default 0 (unknown)
            supports_json:             bool
            supports_stream:           bool, always False in Phase 1
            supports_prefix_cache:     bool, always False in Phase 1 (X4)
            supports_response_cache:   bool, always False in Phase 1 (X4)
            safe_concurrency:          int, always 1 in Phase 1 (X6)
            latency_p50_ms:            int, 0 = unknown
            provider / model:          str, resolved target
        """
        # Resolve the provider that would be used for (task, tier) today.
        # Task is ignored in Phase 1 (no task->provider mapping yet); future
        # versions will route by (task, tier) tuple.
        _ = task  # suppress unused warning until Phase 7
        routing = self._tier_routing.get(tier, {})
        return {
            "max_input_tokens":        0,          # unknown in Phase 1
            "supports_json":           True,       # all current providers do
            "supports_stream":         False,      # Phase 5 reserved
            "supports_prefix_cache":   False,      # Phase 2 reserved (X4)
            "supports_response_cache": False,      # Phase 2 reserved (X4)
            "safe_concurrency":        1,          # Phase 2 reserved (X6)
            "latency_p50_ms":          0,          # unknown
            "provider":                routing.get("provider", ""),
            "model":                   routing.get("model", ""),
        }

    def get_stats(self) -> dict:
        """Snapshot of per-provider call counters (deep-copied, thread-safe)."""
        return self._stats.snapshot()

    def get_tier_routing(self) -> dict:
        """Deep-copy of current tier routing config.
        Structure: {"premium": {"provider": "Gemini", "model": "..."}, ...}
        """
        import copy
        return copy.deepcopy(self._tier_routing)

    def set_tier_routing(self, tier: str, provider: str, model: str) -> None:
        """Update (provider, model) for a tier and persist."""
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}")
        self._tier_routing[tier] = {"provider": provider, "model": model}
        self._persist()

    def get_task_routing(self) -> dict:
        """Deep-copy of the task routing map.
        Structure: {task_id: {"provider": str, "model": str}}
        """
        import copy
        return copy.deepcopy(self._task_routing)

    def set_task_routing(self, task: str, provider: str, model: str) -> None:
        """Set the single routing entry for a task and persist."""
        self._task_routing[task] = {"provider": provider, "model": model}
        self._persist()

    def get_provider_names(self) -> list:
        return list(self._providers.keys())

    def get_provider_models(self, provider: str) -> list:
        provider = _cfg.canonicalize_provider_name(provider)
        return self._providers.get(provider, {}).get("models", [])

    def list_models(self, provider: str) -> list[str]:
        """Fetch live model list from the provider's API.

        Supported provider types: gemini, openai_compatible. ClaudeCode's
        local CLI has no remote model endpoint; raises RuntimeError.

        Caller is expected to update the provider's `models` field via
        update_provider() if they want to persist.
        """
        provider = _cfg.canonicalize_provider_name(provider)
        cfg = self._providers.get(provider)
        if cfg is None:
            raise RuntimeError(f"Unknown provider: {provider!r}")
        ptype = cfg.get("type")
        api_key = _cfg.read_key(cfg)
        if ptype == "gemini":
            if not api_key:
                raise RuntimeError(f"API key required to list Gemini models")
            return _gemini.list_models(api_key)
        if ptype == "openai_compatible":
            if not api_key:
                raise RuntimeError(f"API key required to list models from {provider!r}")
            base_url = cfg.get("base_url", "")
            if not base_url:
                raise RuntimeError(f"provider {provider!r} has no base_url configured")
            return _openai_compat.list_models(api_key, base_url)
        if ptype == "claude_code":
            raise RuntimeError(
                "ClaudeCode runs locally via the `claude` CLI; model list "
                "is fixed (sonnet / opus / haiku). No remote refresh."
            )
        raise RuntimeError(f"Unsupported provider type for list_models: {ptype!r}")

    def get_available_providers(self, tier: str | None = None) -> list:
        """Providers that are enabled AND have valid auth for their type.

        For claude_code, the local CLI handles its own auth — enabled+present
        is enough. Returns list sorted by priority (lower number = higher).
        """
        result = []
        for name, cfg in self._providers.items():
            if not cfg.get("enabled", True):
                continue
            if not _cfg.has_auth(cfg):
                continue
            model_id = cfg["tiers"].get(tier) if tier else None
            if tier and not model_id:
                continue
            result.append({
                "name":     name,
                "type":     cfg["type"],
                "priority": cfg.get("priority", 99),
                "model":    model_id,
            })
        result.sort(key=lambda x: x["priority"])
        return result

    def reload_config(self) -> None:
        """Hot-reload from providers.json on disk."""
        self._load_config()

    # ── ASR API ──────────────────────────────────────────────────────────────

    def asr(self, audio_path: str, *,
            provider: str = "lemonfox",
            language: str | None = None,
            translate: bool = False,
            speaker_labels: bool = False,
            on_event=None,
            cancel_token=None) -> dict:
        """Dispatch an ASR (speech-to-text) call.

        Args:
            audio_path:     Path to audio/video file.
            provider:       ASR provider name. Phase 1 only supports
                            "lemonfox".
            language:       Optional source-language hint. None = auto.
            translate:      If True, provider returns English translation.
            speaker_labels: If True, provider tags speakers.
            on_event:       Optional callback(event_type, **kwargs) for
                            upload progress / wait ticks / retries.
                            See core.ai.providers.lemonfox for event types.

        Returns:
            Raw verbose_json dict from the provider (language, duration,
            segments[], words[], text).

        Raises:
            RuntimeError: provider unknown, key missing, or all HTTP
                          attempts failed.
        """
        cfg = self._asr_providers.get(provider)
        if cfg is None:
            raise RuntimeError(f"Unknown ASR provider: {provider!r}")
        if not cfg.get("enabled", True):
            raise RuntimeError(f"ASR provider {provider!r} is disabled")

        is_local = cfg.get("auth_required") is False
        api_key = None
        base_url = cfg.get("base_url") or ""
        if not is_local:
            api_key = _cfg.read_key(cfg)
            if api_key is None:
                raise RuntimeError(
                    f"ASR API key not configured for {provider!r} — "
                    f"set it in AI Router manager"
                )
            if not base_url:
                raise RuntimeError(f"ASR provider {provider!r} has no base_url")

        try:
            if provider == "lemonfox":
                result = _lemonfox.transcribe(
                    audio_path,
                    api_key=api_key,
                    base_url=base_url,
                    language=language,
                    translate=translate,
                    speaker_labels=speaker_labels,
                    connect_timeout=cfg.get("connect_timeout_sec", 60),
                    read_timeout=cfg.get("read_timeout_sec", 120),
                    max_retries=cfg.get("max_retries", 1),
                    on_event=on_event,
                    cancel_token=cancel_token,
                )
            elif provider == "faster_whisper":
                from core.ai.providers import faster_whisper_local as _fw
                result = _fw.transcribe(
                    audio_path,
                    model_name=cfg.get("model", "small"),
                    device=cfg.get("device", "auto"),
                    compute_type=cfg.get("compute_type", "auto"),
                    beam_size=cfg.get("beam_size", 5),
                    language=language,
                    translate=translate,
                    on_event=on_event,
                    cancel_token=cancel_token,
                )
            else:
                raise RuntimeError(f"Unsupported ASR provider type: {provider!r}")

            self._stats.record(provider, success=True)
            return result

        except Exception as e:
            self._stats.record(provider, success=False, error=str(e))
            raise

    def get_asr_key(self, provider: str) -> str | None:
        cfg = self._asr_providers.get(provider)
        if cfg is None:
            return None
        return _cfg.read_key(cfg)

    def get_asr_config(self, provider: str) -> dict | None:
        import copy
        cfg = self._asr_providers.get(provider)
        return copy.deepcopy(cfg) if cfg else None

    def get_available_asr_providers(self) -> list:
        return [
            {
                "name":     name,
                "display":  cfg.get("name", name),
                "enabled":  cfg.get("enabled", True),
                "has_key":  _cfg.read_key(cfg) is not None,
                "base_url": cfg.get("base_url", ""),
            }
            for name, cfg in self._asr_providers.items()
        ]

    def update_asr_provider(self, provider: str, **kwargs) -> None:
        if provider not in self._asr_providers:
            raise RuntimeError(f"Unknown ASR provider: {provider!r}")
        self._asr_providers[provider].update(kwargs)
        self._persist()

    # ── TTS API ──────────────────────────────────────────────────────────────

    def tts(self, text: str, output_path: str, *,
            provider: str = "fish_audio",
            voice_id: str,
            audio_format: str = "mp3",
            should_cancel=None,
            on_chunk=None,
            cancel_token=None) -> None:
        """Dispatch a TTS synthesis call.

        Args:
            text:          Input text.
            output_path:   Destination audio file.
            provider:      TTS provider name. Phase 1 only supports
                           "fish_audio".
            voice_id:      Voice / reference ID for the provider.
            audio_format:  'mp3' | 'wav' | 'opus'.
            should_cancel: Optional predicate for cooperative cancel;
                           provider raises InterruptedError mid-stream
                           when it returns True.
            on_chunk:      Optional callback(bytes_written_so_far) for
                           streaming progress.

        Raises:
            RuntimeError:     provider unknown / disabled / key missing /
                              SDK missing / API failure.
            InterruptedError: user cancelled via should_cancel.
        """
        cfg = self._tts_providers.get(provider)
        if cfg is None:
            raise RuntimeError(f"Unknown TTS provider: {provider!r}")
        if not cfg.get("enabled", True):
            raise RuntimeError(f"TTS provider {provider!r} is disabled")
        api_key = _cfg.read_key(cfg)
        if api_key is None:
            raise RuntimeError(
                f"TTS API key not configured for {provider!r} — "
                f"set it in AI Router manager"
            )

        try:
            if provider == "fish_audio":
                _fish_audio.synthesize(
                    text, output_path,
                    api_key=api_key,
                    voice_id=voice_id,
                    audio_format=audio_format,
                    should_cancel=should_cancel,
                    on_chunk=on_chunk,
                    cancel_token=cancel_token,
                )
            else:
                raise RuntimeError(f"Unsupported TTS provider: {provider!r}")
            self._stats.record(provider, success=True)
        except InterruptedError:
            # Treat user cancel as not-a-failure for stats (and re-raise so
            # the UI layer knows). The provider already left no partial
            # output beyond what the caller handles.
            raise
        except Exception as e:
            self._stats.record(provider, success=False, error=str(e))
            raise

    def get_tts_key(self, provider: str) -> str | None:
        cfg = self._tts_providers.get(provider)
        if cfg is None:
            return None
        return _cfg.read_key(cfg)

    def get_tts_config(self, provider: str) -> dict | None:
        import copy
        cfg = self._tts_providers.get(provider)
        return copy.deepcopy(cfg) if cfg else None

    def get_available_tts_providers(self) -> list:
        return [
            {
                "name":    name,
                "display": cfg.get("name", name),
                "enabled": cfg.get("enabled", True),
                "has_key": _cfg.read_key(cfg) is not None,
            }
            for name, cfg in self._tts_providers.items()
        ]

    def update_tts_provider(self, provider: str, **kwargs) -> None:
        if provider not in self._tts_providers:
            raise RuntimeError(f"Unknown TTS provider: {provider!r}")
        self._tts_providers[provider].update(kwargs)
        self._persist()

    def set_provider_enabled(self, provider: str, enabled: bool) -> None:
        provider = _cfg.canonicalize_provider_name(provider)
        if provider in self._providers:
            self._providers[provider]["enabled"] = enabled
            self._persist()

    def update_provider(self, provider: str, **kwargs) -> None:
        """Update arbitrary fields on an LLM provider entry. Allows new fields."""
        provider = _cfg.canonicalize_provider_name(provider)
        if provider not in self._providers:
            raise RuntimeError(f"Unknown provider: {provider!r}")
        cfg = self._providers[provider]
        for k, v in kwargs.items():
            cfg[k] = v
        self._persist()

    # ── Internal routing ─────────────────────────────────────────────────────

    def _complete_explicit(self, provider: str, tier: str,
                           model: str | None, prompt: str) -> str:
        cfg = self._providers.get(provider)
        if cfg is None:
            raise RuntimeError(
                f"Unknown provider: {provider!r}, check providers.json"
            )
        resolved_model = model or cfg["tiers"].get(tier) or cfg["tiers"].get(TIER_STANDARD)
        if not resolved_model:
            raise RuntimeError(
                f"provider {provider!r} has no model configured for tier={tier!r}"
            )
        return self._call(provider, cfg, resolved_model, prompt)

    def _resolve_task_tier(self, task: str, tier: str,
                           model_override: str | None) -> tuple[str, str]:
        """Look up (provider, model) for `task`.

        `tier` is accepted but ignored — kept in the signature so older
        feature/UI callers that still pass tier= don't break. Routing is
        flat per-task now (see config._task_routing schema).

        Priority:
          1. task_routing[task]            (exact match)
          2. tier_routing[tier]            (legacy fallback when task unknown)
        Returns ("", "") if nothing resolves — caller should auto-fallback.

        `model_override` wins over whatever the routing tables contain.
        """
        _ = tier  # legacy parameter, no longer used for routing
        if task:
            cell = self._task_routing.get(task, {})
            if cell.get("provider"):
                return cell["provider"], model_override or cell.get("model", "")
        legacy = self._tier_routing.get(TIER_STANDARD, {})
        return legacy.get("provider", ""), model_override or legacy.get("model", "")

    def _complete_by_tier(self, task: str, tier: str,
                          model: str | None, prompt: str) -> str:
        """Task/tier routing with explicit-config priority, auto-fallback on error."""
        r_provider, r_model = self._resolve_task_tier(task, tier, model)

        if r_provider and r_model:
            cfg = self._providers.get(r_provider)
            if cfg and cfg.get("enabled", True) and _cfg.read_key(cfg) is not None:
                try:
                    return self._call(r_provider, cfg, r_model, prompt)
                except Exception:
                    pass  # Explicitly configured failed -> fall through to auto

        candidates = self._get_candidates(tier)
        if not candidates:
            raise RuntimeError(
                f"No available provider for tier={tier!r}. "
                "Configure an API Key in the AI Router manager."
            )
        last_err = None
        for name, cfg, mid in candidates:
            try:
                return self._call(name, cfg, model or mid, prompt)
            except Exception as e:
                last_err = e
        raise RuntimeError(
            f"All providers for tier={tier!r} failed. Last error: {last_err}"
        )

    def _complete_json_explicit(self, provider: str, tier: str, model: str | None,
                                prompt: str, schema: dict,
                                cancel_token=None) -> dict:
        cfg = self._providers.get(provider)
        if cfg is None:
            raise RuntimeError(
                f"Unknown provider: {provider!r}, check providers.json"
            )
        resolved_model = model or cfg["tiers"].get(tier) or cfg["tiers"].get(TIER_STANDARD)
        if not resolved_model:
            raise RuntimeError(
                f"provider {provider!r} has no model configured for tier={tier!r}"
            )
        return self._call_json(provider, cfg, resolved_model, prompt, schema,
                                cancel_token=cancel_token)

    def _complete_json_by_tier(self, task: str, tier: str, model: str | None,
                               prompt: str, schema: dict,
                               cancel_token=None) -> dict:
        r_provider, r_model = self._resolve_task_tier(task, tier, model)

        if r_provider and r_model:
            cfg = self._providers.get(r_provider)
            if cfg and cfg.get("enabled", True) and _cfg.read_key(cfg) is not None:
                try:
                    return self._call_json(r_provider, cfg, r_model, prompt,
                                            schema, cancel_token=cancel_token)
                except AIError as e:
                    # Don't auto-fall-back on cancellation — user wants OUT.
                    if e.kind == Kind.CANCELLED:
                        raise
                except Exception:
                    pass

        candidates = self._get_candidates(tier)
        if not candidates:
            raise RuntimeError(
                f"No available provider for tier={tier!r}. "
                "Configure an API Key in the AI Router manager."
            )
        last_err = None
        for name, cfg, mid in candidates:
            try:
                return self._call_json(name, cfg, model or mid, prompt, schema,
                                        cancel_token=cancel_token)
            except AIError as e:
                if e.kind == Kind.CANCELLED:
                    raise
                last_err = e
            except Exception as e:
                last_err = e
        raise RuntimeError(
            f"All providers for tier={tier!r} failed. Last error: {last_err}"
        )

    def _get_candidates(self, tier: str) -> list:
        """Return (name, cfg, model_id) sorted by priority, filtering unavailable."""
        result = []
        for name, cfg in self._providers.items():
            if not cfg.get("enabled", True):
                continue
            model_id = cfg["tiers"].get(tier, "")
            if not model_id:
                continue
            if not _cfg.has_auth(cfg):
                continue
            result.append((name, cfg, model_id, cfg.get("priority", 99)))
        result.sort(key=lambda x: x[3])
        return [(n, c, m) for n, c, m, _ in result]

    # ── Provider dispatch ────────────────────────────────────────────────────

    def _call(self, name: str, cfg: dict, model_id: str, prompt: str) -> str:
        """Dispatch to the right provider adapter. Records stats; re-raises."""
        ptype = cfg.get("type")
        api_key = None
        if ptype != "claude_code":
            if cfg.get("auth_required") is False:
                # Local provider (e.g. Ollama). OpenAI SDK requires a non-empty
                # api_key string, but the local server ignores its content.
                api_key = "ollama"
            else:
                api_key = _cfg.read_key(cfg)
                if api_key is None:
                    raise RuntimeError(f"API Key not configured: {cfg.get('key_file', '?')}")

        try:
            if ptype == "gemini":
                result = _gemini.call(api_key, model_id, prompt)
            elif ptype == "openai_compatible":
                base_url = cfg.get("base_url", "")
                if not base_url:
                    raise RuntimeError(f"provider {name!r} has no base_url configured")
                result = _openai_compat.call(api_key, base_url, model_id, prompt)
            elif ptype == "claude_code":
                result = _claude_code.call(cfg, model_id, prompt)
            else:
                raise RuntimeError(f"Unsupported provider type: {ptype!r}")

            self._stats.record(name, success=True)
            return result

        except Exception as e:
            self._stats.record(name, success=False, error=str(e))
            raise

    def _call_json(self, name: str, cfg: dict, model_id: str,
                   prompt: str, schema: dict, *, cancel_token=None) -> dict:
        ptype = cfg.get("type")
        api_key = None
        if ptype != "claude_code":
            if cfg.get("auth_required") is False:
                api_key = "ollama"
            else:
                api_key = _cfg.read_key(cfg)
                if api_key is None:
                    raise RuntimeError(f"API Key not configured: {cfg.get('key_file', '?')}")

        try:
            if ptype == "gemini":
                result = _gemini.call_json(api_key, model_id, prompt, schema,
                                            cancel_token=cancel_token)
            elif ptype == "openai_compatible":
                base_url = cfg.get("base_url", "")
                if not base_url:
                    raise RuntimeError(f"provider {name!r} has no base_url configured")
                result = _openai_compat.call_json(api_key, base_url, model_id,
                                                    prompt, schema,
                                                    cancel_token=cancel_token)
            elif ptype == "claude_code":
                result = _claude_code.call_json(cfg, model_id, prompt, schema,
                                                  cancel_token=cancel_token)
            else:
                raise RuntimeError(f"Unsupported JSON provider type: {ptype!r}")

            self._stats.record(name, success=True)
            return result

        except Exception as e:
            self._stats.record(name, success=False, error=str(e))
            raise

    # ── Config load / persist ────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Load (or initialize) configuration; reseed stats."""
        data = _cfg.load_config()
        self._providers     = data["providers"]
        self._asr_providers = data["asr_providers"]
        self._tts_providers = data["tts_providers"]
        self._tier_routing  = data["tier_routing"]
        self._task_routing  = data["task_routing"]
        self._stats.init_providers(list(self._providers.keys()))

    def _persist(self) -> None:
        _cfg.save_config({
            "providers":     self._providers,
            "asr_providers": self._asr_providers,
            "tts_providers": self._tts_providers,
            "tier_routing":  self._tier_routing,
            "task_routing":  self._task_routing,
        })


# Module-level singleton. Exposed via `core.ai.router` and the legacy
# `ai_router.router` compatibility shim.
router = AIRouter()
