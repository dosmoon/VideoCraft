"""Creation-domain RPC tests (news_desk): config owner + component CRUD.

The base RPC layer is creation-agnostic (ADR-0004): wiring
`config_owner_cls=NewsDeskInstanceConfig` is enough for the whole component +
config face to work, exactly as clip's. These drive the dispatch kernel against
a tmp news_desk instance, mirroring test_creation.py's (ctx + _open) pattern.

Presets and the preview/render providers are NOT wired yet for news_desk (the
preset shape decision + per-chapter providers are a follow-up increment), so a
preset call is expected to error — pinned here so the deferral is explicit.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import pytest

import core_rpc.methods as methods
from core_rpc.dispatch import dispatch_message


def call(ctx, method: str, params: Optional[dict[str, Any]] = None, id: Any = 1):
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


def _open(ctx, project):
    resp = call(ctx, "project.open", {"folder": project.folder})
    assert "result" in resp, resp


@pytest.fixture
def project_with_news_desk(tmp_project):
    """tmp Project with one news_desk creation instance whose config.json
    mirrors the Tk era: components carry NO ids (only subtitle did historically),
    so the id-repair path is exercised. Registers all plugins."""
    methods.load_plugins()  # registers news_desk CreationType (config_owner_cls)
    inst_dir = tmp_project.creation_instance_dir("news_desk", "news")
    os.makedirs(inst_dir, exist_ok=True)
    config = {
        "components": [
            {"kind": "subtitle", "name": "字幕", "enabled": True},
            {"kind": "text_watermark", "name": "文字水印", "enabled": True},
        ],
    }
    with open(os.path.join(inst_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    return tmp_project


# ── config + id repair ──────────────────────────────────────────────────────

def test_load_config_returns_components(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    cfg = call(ctx, "creation.load_config", {"type": "news_desk", "instance": "news"})["result"]
    assert cfg["components"][0]["kind"] == "subtitle"


def test_load_repairs_missing_ids(ctx, project_with_news_desk):
    """Id-less Tk-era components get stable, unique ids so the RPCs can address
    them — id falls back to the kind."""
    _open(ctx, project_with_news_desk)
    comps = call(ctx, "creation.list_components", {"type": "news_desk", "instance": "news"})["result"]
    assert [c["id"] for c in comps] == ["subtitle", "text_watermark"]


# ── component CRUD ───────────────────────────────────────────────────────────

def test_add_component_appends_and_persists(ctx, project_with_news_desk, emit):
    _open(ctx, project_with_news_desk)
    comps = call(
        ctx, "creation.add_component",
        {"type": "news_desk", "instance": "news", "kind": "image_watermark"},
    )["result"]
    added = comps[-1]
    assert added["kind"] == "image_watermark"
    assert added["scale_pct"] == 15  # canonical default shape (int percent)
    assert ("event.creation.changed", {"type": "news_desk", "instance": "news"}) in emit.events
    # Persisted on disk.
    path = os.path.join(
        project_with_news_desk.creation_instance_dir("news_desk", "news"), "config.json"
    )
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert "image_watermark" in [c["kind"] for c in on_disk["components"]]


def test_add_assigns_unique_id(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    call(ctx, "creation.add_component", {"type": "news_desk", "instance": "news", "kind": "subtitle"})
    comps = call(
        ctx, "creation.add_component", {"type": "news_desk", "instance": "news", "kind": "subtitle"}
    )["result"]
    sub_ids = [c["id"] for c in comps if c["kind"] == "subtitle"]
    assert sub_ids == ["subtitle", "subtitle-2", "subtitle-3"]  # fixture's + two new
    assert len(set(sub_ids)) == len(sub_ids)


def test_added_subtitle_has_canonical_fraction_shape(ctx, project_with_news_desk):
    """The new-arch default emits fraction font sizes (resolution-independent),
    matching the merged TS contract — not the Tk specs' absolute px."""
    _open(ctx, project_with_news_desk)
    comps = call(
        ctx, "creation.add_component", {"type": "news_desk", "instance": "news", "kind": "subtitle"}
    )["result"]
    comp = comps[-1]
    assert comp["fontsize_pct"] == 0.026
    assert comp["stroke_pct"] == 0.002
    assert comp["block_margin_pct"] == 9   # int kept (TS normalises /100)
    assert "fontsize" not in comp          # no absolute-px field


def test_update_component_merges_patch(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    resp = call(
        ctx, "creation.update_component",
        {"type": "news_desk", "instance": "news",
         "component_id": "subtitle", "patch": {"fontsize_pct": 0.05}},
    )
    assert resp["result"]["fontsize_pct"] == 0.05
    comps = call(ctx, "creation.list_components", {"type": "news_desk", "instance": "news"})["result"]
    sub = next(c for c in comps if c["id"] == "subtitle")
    assert sub["fontsize_pct"] == 0.05


def test_remove_component(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    comps = call(
        ctx, "creation.remove_component",
        {"type": "news_desk", "instance": "news", "component_id": "text_watermark"},
    )["result"]
    assert "text_watermark" not in [c.get("id") for c in comps]


def test_move_component_reorders(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    comps = call(
        ctx, "creation.move_component",
        {"type": "news_desk", "instance": "news", "component_id": "text_watermark", "delta": -1},
    )["result"]
    assert [c["kind"] for c in comps] == ["text_watermark", "subtitle"]


# ── addable kinds ────────────────────────────────────────────────────────────

def test_addable_components_chapter_is_singleton(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    addable = call(
        ctx, "creation.list_addable_components", {"type": "news_desk", "instance": "news"}
    )["result"]
    assert addable[0]["kind"] == "chapter"  # registration order
    by_kind = {d["kind"]: d for d in addable}
    assert by_kind["chapter"]["multi_instance"] is False
    assert by_kind["subtitle"]["multi_instance"] is True


# ── config patch ─────────────────────────────────────────────────────────────

def test_update_config_sets_preset_name(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    cfg = call(
        ctx, "creation.update_config",
        {"type": "news_desk", "instance": "news", "patch": {"preset_name": "演讲"}},
    )["result"]
    assert cfg["preset_name"] == "演讲"


# ── deferred: presets / providers not wired yet ──────────────────────────────

def test_presets_not_supported_yet(ctx, project_with_news_desk):
    """Preset RPC is deferred for news_desk (the presets.py builtins still carry
    the legacy absolute-px shape; canonicalising them is a follow-up). The base
    layer reports it gracefully rather than crashing."""
    _open(ctx, project_with_news_desk)
    resp = call(ctx, "creation.list_presets", {"type": "news_desk", "instance": "news"})
    assert "error" in resp


def test_preview_provider_not_wired_yet(ctx, project_with_news_desk):
    """preview_data has no provider for news_desk yet (per-chapter preview is the
    next increment) → graceful -32603, not a crash."""
    _open(ctx, project_with_news_desk)
    resp = call(ctx, "creation.preview_data", {"type": "news_desk", "instance": "news"})
    assert resp["error"]["code"] == -32603
