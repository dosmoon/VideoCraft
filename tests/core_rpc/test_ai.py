"""ai.* RPC — read-only AI Console view (P1-a).

Verifies the snapshot shape the renderer console renders against, and that the
read model classifies providers / reports key status the same way the Tk console
does (without touching real key files).
"""

from __future__ import annotations

from typing import Any, Optional

import core_rpc.methods  # noqa: F401  (registers handlers)
from core_rpc.dispatch import dispatch_message

# `ctx` is the shared fixture from conftest.py (real Context with session/jobs).


def call(ctx, method: str, params: Optional[dict[str, Any]] = None, id: Any = 1):
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


def test_ai_snapshot_shape(ctx):
    snap = call(ctx, "ai.snapshot")["result"]

    # Tasks: the routing-matrix rows, with category.
    task_ids = {t["id"] for t in snap["tasks"]}
    assert {"translate", "subtitle.post", "asr.transcribe"} <= task_ids
    assert all(t["category"] in ("llm", "asr", "tts") for t in snap["tasks"])

    # Routing tiers: LLM has the extra "auto"; ASR/TTS don't.
    assert snap["routing_tiers"]["llm"] == ["embedded", "cloud", "aistack", "auto"]
    assert "auto" not in snap["routing_tiers"]["non_llm"]

    # Active routing is a {task: {provider, model}} map covering every task.
    assert set(snap["task_routing"]) == task_ids
    for cell in snap["task_routing"].values():
        assert "provider" in cell and "model" in cell

    # Providers: three category buckets, each a list of normalized rows.
    assert set(snap["providers"]) == {"llm", "asr", "tts"}
    llm = {p["name"]: p for p in snap["providers"]["llm"]}
    assert "LlamaCpp" in llm and "Gemini" in llm
    assert llm["LlamaCpp"]["deploy_tier"] == "local"
    assert llm["Gemini"]["deploy_tier"] == "cloud"
    # aistack classifies to its own tier wherever it appears.
    assert all(
        p["deploy_tier"] == "aistack"
        for bucket in snap["providers"].values()
        for p in bucket
        if p["name"] == "aistack"
    )

    # Key status is structured (enum + masked), never raw key text.
    g = llm["Gemini"]["key_status"]
    assert g["state"] in ("ok", "not_configured", "empty")
    assert "claude" not in str(g.get("masked") or "").lower()
    # claude_code reports CLI auth, no key file.
    if "ClaudeCode" in llm:
        assert llm["ClaudeCode"]["key_status"]["state"] == "cli"

    # aistack gateway block.
    assert snap["aistack"]["base_url"].startswith("http")
    assert set(snap["aistack"]["models_cache"]) == {"llm", "asr", "tts"}


def test_ai_stats_shape(ctx):
    stats = call(ctx, "ai.stats")["result"]
    # Per-provider counters; entries (if seeded) carry calls/errors.
    assert isinstance(stats, dict)
    for entry in stats.values():
        assert "calls" in entry and "errors" in entry
