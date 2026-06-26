"""core.ai — Unified AI facade for VideoCraft.

Design principles (see docs/design/04-ai-router.md):
  1. Three-layer architecture: UI -> core/<feature> -> core/ai
  2. UI layer must NOT import core.ai directly (except infrastructure tools
     like the AI console / Router tab itself).
  3. Feature layer (core/translate.py, core/asr.py, etc.) is the proper
     consumer of this facade.

Module layout:
  - router.py: AIRouter class + singleton
  - tiers.py: TIER_* constants + Tier enum
  - config.py: providers.json loader
  - errors.py / cancellation.py: cross-cutting contracts
  - providers/: per-provider adapters (gemini / openai_compat / claude_code / ...)
"""

from core.ai.router import router, AIRouter
from core.ai.tiers import (
    Tier,
    TIER_PREMIUM,
    TIER_STANDARD,
    TIER_ECONOMY,
    TIERS,
)
from core.ai.errors import AIError, Kind
from core.ai.cancellation import CancellationToken


# ── Facade functions ────────────────────────────────────────────────────────
# Feature layer (core/translate.py etc.) calls these. They are thin wrappers
# around the router singleton. Keeping them as module-level functions keeps
# feature-layer call sites concise:
#   `from core import ai; text = ai.complete(prompt, task="translate")`

def complete(prompt: str, *,
             task: str = "",
             tier: str = TIER_STANDARD,
             provider: str | None = None,
             model: str | None = None) -> str:
    """Plain text completion.

    `task` is the namespace identifier (e.g. "translate", "subtitle.refine").
    Routing consults task_routing[task][tier] first, then falls back to
    tier_routing[tier] for legacy callers that pass task=''.
    """
    return router.complete(prompt, task=task, tier=tier,
                           provider=provider, model=model)


def complete_json(prompt: str, *,
                  schema: dict,
                  task: str = "",
                  tier: str = TIER_STANDARD,
                  provider: str | None = None,
                  model: str | None = None,
                  cancel_token=None) -> dict:
    """Structured JSON completion. See complete() for `task` semantics."""
    return router.complete_json(
        prompt, schema=schema, task=task, tier=tier,
        provider=provider, model=model, cancel_token=cancel_token,
    )


def describe(task: str = "", tier: str = TIER_STANDARD) -> dict:
    """Capability metadata for (task, tier). Phase 1 returns placeholders."""
    return router.describe(task, tier)


def asr(audio_path: str, *,
        task: str = "asr.transcribe",
        provider: str | None = None,
        language: str | None = None,
        translate: bool = False,
        speaker_labels: bool = False,
        on_event=None,
        cancel_token=None) -> dict:
    """Transcribe audio. Returns raw provider response dict.

    When `provider` is None, the router resolves it from
    task_routing[task] (configurable in AI Console). Pass an explicit
    provider name to override routing. `on_event` receives structured
    state events — see core.ai.providers.lemonfox.transcribe() and
    core.ai.providers.aistack.transcribe() for event types.
    """
    return router.asr(
        audio_path,
        task=task,
        provider=provider,
        language=language,
        translate=translate,
        speaker_labels=speaker_labels,
        on_event=on_event,
        cancel_token=cancel_token,
    )


def tts(text: str, output_path: str, *,
        provider: str,
        voice_id: str,
        task: str = "",
        audio_format: str = "mp3",
        speed: float | None = None,
        should_cancel=None,
        on_chunk=None,
        cancel_token=None) -> None:
    """Stream TTS audio to a file.

    `provider` is now required (the old `provider="fish_audio"` default
    was removed 2026-05-11 since TTS no longer routes — every caller
    knows the engine via VoicePickerDialog at use time, and silently
    defaulting to fish_audio masked "forgot to pass provider" bugs).

    `task` is now optional (no default) since tts.synthesize was removed
    from TASKS; pass an empty string when there's no task tag to record.

    `speed` is an optional per-call rate override (1.0 = normal). Only
    providers with native rate control honor it (edge_tts today); others
    ignore it. None falls back to the provider's configured default. The
    dubbing pipeline drives it per cue to fit subtitle slots.

    `should_cancel` is the legacy predicate API (kept for back-compat);
    `cancel_token` is the canonical CancellationToken integration. Either
    or both work; both signals stop the stream.
    """
    return router.tts(
        text, output_path,
        task=task,
        provider=provider,
        voice_id=voice_id,
        audio_format=audio_format,
        speed=speed,
        should_cancel=should_cancel,
        on_chunk=on_chunk,
        cancel_token=cancel_token,
    )


def list_models(provider: str) -> list[str]:
    """Fetch the live model list from the given LLM provider's API.
    Only supported for Gemini / OpenAI-compatible providers; ClaudeCode
    raises RuntimeError (its model list is fixed local aliases)."""
    return router.list_models(provider)


__all__ = [
    "router",
    "AIRouter",
    "Tier",
    "TIER_PREMIUM",
    "TIER_STANDARD",
    "TIER_ECONOMY",
    "TIERS",
    "AIError",
    "Kind",
    "CancellationToken",
    "complete",
    "complete_json",
    "describe",
    "asr",
    "tts",
    "list_models",
]
