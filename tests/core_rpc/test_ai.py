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


# ── Write ops (all guarded so no real config / key files are touched) ─────────


def test_ai_set_key(ctx, tmp_path, monkeypatch):
    from core.ai import console_view

    # Redirect keys/ to tmp so both the write and the key_status read hit tmp.
    monkeypatch.setattr(console_view._cfg, "keys_dir", lambda: str(tmp_path))
    snap = call(
        ctx, "ai.set_key", {"provider": "Gemini", "category": "llm", "key": "abcd1234efgh"}
    )["result"]
    g = next(p for p in snap["providers"]["llm"] if p["name"] == "Gemini")
    assert g["key_status"] == {"state": "ok", "masked": "abcd****efgh"}
    # A keyless provider is rejected.
    resp = call(ctx, "ai.set_key", {"provider": "LlamaCpp", "category": "llm", "key": "x"})
    assert "error" in resp


def test_ai_set_routing(ctx, monkeypatch):
    from core.ai.router import router

    monkeypatch.setattr(router, "_persist", lambda: None)
    orig = router.get_task_routing()["translate"]
    snap = call(
        ctx, "ai.set_routing", {"task": "translate", "provider": "Gemini", "model": "gemini-2.5-flash"}
    )["result"]
    assert snap["task_routing"]["translate"] == {"provider": "Gemini", "model": "gemini-2.5-flash"}
    call(ctx, "ai.set_routing", {"task": "translate", **orig})  # restore in-memory


def test_ai_set_tier_pref(ctx, monkeypatch):
    from core.ai.router import router

    monkeypatch.setattr(router, "_persist", lambda: None)
    snap = call(
        ctx,
        "ai.set_tier_pref",
        {"task": "translate", "tier": "cloud", "provider": "DeepSeek", "model": "deepseek-chat"},
    )["result"]
    assert snap["task_tier_prefs"]["translate"]["cloud"] == {
        "provider": "DeepSeek",
        "model": "deepseek-chat",
    }


def test_ai_set_provider_enabled(ctx, monkeypatch):
    from core.ai.router import router

    monkeypatch.setattr(router, "_persist", lambda: None)
    snap = call(
        ctx, "ai.set_provider_enabled", {"provider": "DeepSeek", "category": "llm", "enabled": False}
    )["result"]
    ds = next(p for p in snap["providers"]["llm"] if p["name"] == "DeepSeek")
    assert ds["enabled"] is False
    call(ctx, "ai.set_provider_enabled", {"provider": "DeepSeek", "category": "llm", "enabled": True})


def test_ai_update_provider(ctx, monkeypatch):
    from core.ai.router import router

    monkeypatch.setattr(router, "_persist", lambda: None)
    orig = dict(router._providers["DeepSeek"])
    snap = call(
        ctx,
        "ai.update_provider",
        {
            "provider": "DeepSeek",
            "category": "llm",
            "patch": {"base_url": "https://x.test/v1", "models": ["m1", "m2"], "enabled": False},
        },
    )["result"]
    ds = next(p for p in snap["providers"]["llm"] if p["name"] == "DeepSeek")
    assert ds["base_url"] == "https://x.test/v1"
    assert ds["models"] == ["m1", "m2"]
    # `enabled` is not in the patch allow-list → ignored (separate path).
    assert "enabled" in orig
    # An empty effective patch (no whitelisted keys) is rejected.
    resp = call(
        ctx, "ai.update_provider", {"provider": "DeepSeek", "category": "llm", "patch": {"foo": 1}}
    )
    assert "error" in resp
    router._providers["DeepSeek"] = orig  # restore in-memory


def test_ai_set_aistack_gateway(ctx, monkeypatch):
    from core.ai.router import router

    monkeypatch.setattr(router, "_persist", lambda: None)
    orig = router.get_aistack_gateway()
    snap = call(
        ctx, "ai.set_aistack_gateway", {"base_url": "http://127.0.0.1:9999/v1", "enabled": False}
    )["result"]
    assert snap["aistack"] == {
        "base_url": "http://127.0.0.1:9999/v1",
        "enabled": False,
        "models_cache": snap["aistack"]["models_cache"],
    }
    call(ctx, "ai.set_aistack_gateway", {"base_url": orig["base_url"], "enabled": orig["enabled"]})
