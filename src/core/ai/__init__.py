"""core.ai — Unified AI facade for VideoCraft.

Design principles (see docs/design/04-ai-router.md):
  1. Three-layer architecture: UI -> core/<feature> -> core/ai
  2. UI layer must NOT import core.ai directly (except infrastructure tools
     like the AI console / Router tab itself).
  3. Feature layer (core/translate.py, core/asr.py, etc.) is the proper
     consumer of this facade.

Phase 1 scope (current):
  - Router + stats + config split out of the old ai_router.py monolith.
  - LLM provider adapters extracted (gemini / openai_compat / claude_code).
  - AIError + CancellationToken contracts scaffolded (implementation in
    Phase 7).
  - describe() returns Phase 1 placeholder capability metadata.
  - ASR / TTS dispatch NOT yet folded in — those migrations happen in
    M4 / M5 respectively. For now, callers continue to use
    `router.get_asr_key(...)` / `router.get_tts_key(...)` and make their
    own HTTP/SDK calls.

Legacy compatibility:
  - `src/ai_router.py` is a thin shim that re-exports `router`, `TIER_*`,
    and the legacy constants so existing `import ai_router` callers keep
    working unchanged.
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
    core.ai.providers.faster_whisper_local.transcribe() for event types.
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
        task: str = "tts.synthesize",
        provider: str = "fish_audio",
        voice_id: str,
        audio_format: str = "mp3",
        should_cancel=None,
        on_chunk=None,
        cancel_token=None) -> None:
    """Stream TTS audio to a file.

    `task` is recorded for forward compatibility; Phase 1 ignores it.
    `should_cancel` is the legacy predicate API (kept for back-compat);
    `cancel_token` is the canonical CancellationToken integration. Either
    or both work; both signals stop the stream.
    """
    _ = task
    return router.tts(
        text, output_path,
        provider=provider,
        voice_id=voice_id,
        audio_format=audio_format,
        should_cancel=should_cancel,
        on_chunk=on_chunk,
        cancel_token=cancel_token,
    )


def is_tts_sdk_available(provider: str = "fish_audio") -> bool:
    """Check whether the given TTS provider's SDK is installed."""
    from core.ai.providers import fish_audio as _fish_audio
    if provider == "fish_audio":
        return _fish_audio.is_sdk_available()
    return False


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
    "is_tts_sdk_available",
    "list_models",
]
