"""AI console RPC — read-only view of provider routing / keys / stats (P1-a).

Thin wrapper over `core.ai.console_view` (the UI-free read model). This is what
lets the Electron shell render the AI Console at all; without it the new shell
can't show or configure providers, so every AI job (ASR / translate / analysis /
ai_fill) is unconfigurable there. Write ops (set key, set routing, test
connection) land in a later slice as separate `ai.*` methods.
"""

from __future__ import annotations

from typing import Any

from ..registry import Context, rpc_method


@rpc_method("ai.snapshot")
def snapshot(ctx: Context) -> dict[str, Any]:
    """Full read-only AI Console state: tasks + routing matrix (active routing +
    per-tier sticky prefs), provider rows (per category, with deploy tier + key
    status), and the aistack gateway. No live model probes (those hit the
    network — separate method) and no call stats (see `ai.stats`)."""
    from core.ai import console_view

    return console_view.snapshot()


@rpc_method("ai.stats")
def stats(ctx: Context) -> dict[str, Any]:
    """Per-provider call counters for the Stats tab (in-memory; refreshed on its
    own so the snapshot stays cheap)."""
    from core.ai import console_view

    return console_view.stats()


# ── Write ops ─────────────────────────────────────────────────────────────────
# Each persists via the router and returns a fresh snapshot so the renderer
# re-syncs the whole console from one source (cheap; config is small). Network
# actions (LLM test, aistack test & refresh) are NOT here — they block on I/O and
# will land as jobs.


@rpc_method("ai.set_key")
def set_key(ctx: Context, provider: str, category: str, key: str) -> dict[str, Any]:
    """Write a cloud provider's API key to keys/<key_file>. Rejects unknown
    providers / providers that take no key (→ HANDLER_ERROR)."""
    from core.ai import console_view

    console_view.set_key(provider, category, key)
    return console_view.snapshot()


@rpc_method("ai.set_provider_enabled")
def set_provider_enabled(
    ctx: Context, provider: str, category: str, enabled: bool
) -> dict[str, Any]:
    """Toggle a provider's enabled flag (the per-row checkbox)."""
    from core.ai import console_view

    console_view.set_provider_enabled(provider, category, bool(enabled))
    return console_view.snapshot()


@rpc_method("ai.set_routing")
def set_routing(ctx: Context, task: str, provider: str, model: str) -> dict[str, Any]:
    """Set a task's active routing (tier radio). Empty provider = Auto."""
    from core.ai import console_view

    console_view.set_routing(task, provider, model)
    return console_view.snapshot()


@rpc_method("ai.set_tier_pref")
def set_tier_pref(
    ctx: Context, task: str, tier: str, provider: str, model: str
) -> dict[str, Any]:
    """Set a task's per-tier sticky pick (dropdown change; does not move the
    active radio)."""
    from core.ai import console_view

    console_view.set_tier_pref(task, tier, provider, model)
    return console_view.snapshot()


@rpc_method("ai.set_aistack_gateway")
def set_aistack_gateway(ctx: Context, base_url: str, enabled: bool) -> dict[str, Any]:
    """Set the aistack gateway URL + enabled (one logical entry across
    LLM/ASR/TTS)."""
    from core.ai import console_view

    console_view.set_aistack_gateway(base_url, bool(enabled))
    return console_view.snapshot()
