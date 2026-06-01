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
