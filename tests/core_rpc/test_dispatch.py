"""Integration tests for dispatch_message + the real handler bindings.

Drives the sidecar's request loop with plain dicts (the headless stand-in for
stdio) against a fresh tmp Project, asserting the same wire shapes the renderer
client will see.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pytest

import core_rpc.methods as methods
from core_rpc import protocol
from core_rpc.dispatch import dispatch_message


def call(ctx, method: str, params: Optional[dict[str, Any]] = None, id: Any = 1):
    """Build + dispatch one request; return the response dict (or None)."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


# ── Transport-level behaviour ─────────────────────────────────────────────────

def test_ping(ctx):
    resp = call(ctx, "system.ping")
    assert resp["result"] == {"ok": True, "protocol": 1, "has_project": False}
    assert resp["id"] == 1


def test_echo_roundtrips_params(ctx):
    resp = call(ctx, "system.echo", {"hello": "世界", "n": 3})
    assert resp["result"] == {"hello": "世界", "n": 3}


def test_unknown_method(ctx):
    resp = call(ctx, "nope.nope")
    assert resp["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_malformed_request_with_id_gets_error(ctx):
    resp = dispatch_message(ctx, {"jsonrpc": "2.0", "id": 9})  # no method
    assert resp["id"] == 9
    assert resp["error"]["code"] == protocol.INVALID_REQUEST


def test_notification_returns_none(ctx):
    # No id ⇒ notification ⇒ no response, even for an unknown method.
    assert dispatch_message(ctx, {"jsonrpc": "2.0", "method": "whatever"}) is None


def test_bad_params_shape_is_invalid_params(ctx):
    # list_material_instances requires `type`; omitting it is a missing-kwarg
    # TypeError (raised before session is touched) → INVALID_PARAMS, loop survives.
    resp = call(ctx, "project.list_material_instances", {})
    assert resp["error"]["code"] == protocol.INVALID_PARAMS


def test_handler_rpcerror_when_no_project(ctx):
    # project.list_material_types touches session.project, which raises
    # RpcError(-32001) when nothing is open.
    resp = call(ctx, "project.list_material_types")
    assert resp["error"]["code"] == -32001


# ── Project domain ────────────────────────────────────────────────────────────

def open_project_in(ctx, project=None):
    """Open the given (or ctx-less default) project through the RPC surface."""
    folder = project.folder
    resp = call(ctx, "project.open", {"folder": folder})
    assert "result" in resp, resp
    return resp


def test_open_sets_current_and_emits(ctx, tmp_project, emit):
    resp = open_project_in(ctx, tmp_project)
    assert resp["result"]["folder"] == tmp_project.folder
    assert resp["result"]["name"] == os.path.basename(tmp_project.folder)
    assert ctx.session.has_project()
    assert "event.project.opened" in emit.methods()

    cur = call(ctx, "project.current")["result"]
    assert cur["folder"] == tmp_project.folder


def test_open_rejects_missing_dir(ctx):
    resp = call(ctx, "project.open", {"folder": "Z:/does/not/exist/xyz"})
    assert resp["error"]["code"] == -32602


def test_close_clears_current(ctx, tmp_project, emit):
    open_project_in(ctx, tmp_project)
    assert call(ctx, "project.close")["result"] == {"closed": True}
    assert call(ctx, "project.current")["result"] is None
    assert "event.project.closed" in emit.methods()


def test_list_materials_empty_project(ctx, tmp_project):
    open_project_in(ctx, tmp_project)
    resp = call(ctx, "project.list_materials")
    assert isinstance(resp["result"], dict)


# ── Creation lifecycle: list types + create instance (the 创作 [+] surface) ─────

def test_list_creation_types(ctx, tmp_project):
    methods.load_plugins()  # registers clip + news_desk CreationTypes
    open_project_in(ctx, tmp_project)
    types = call(ctx, "project.list_creation_types")["result"]
    by_name = {t["type_name"]: t for t in types}
    assert "clip" in by_name and "news_desk" in by_name
    # User-facing description present; never expects the renderer to show type_name.
    assert by_name["news_desk"]["description_zh"]
    assert by_name["news_desk"]["single_instance"] is False


def test_create_creation_instance_autonames_and_emits(ctx, tmp_project, emit):
    methods.load_plugins()
    open_project_in(ctx, tmp_project)
    # First create → auto-named news-1; second → news-2 (suggest_instance_name).
    r1 = call(ctx, "project.create_creation_instance", {"type": "news_desk"})["result"]
    assert r1 == {"type": "news_desk", "instance": "news-1"}
    r2 = call(ctx, "project.create_creation_instance", {"type": "news_desk"})["result"]
    assert r2["instance"] == "news-2"
    assert "event.creations.changed" in emit.methods()
    # It now shows up in list_creations.
    creations = call(ctx, "project.list_creations")["result"]
    assert sorted(creations.get("news_desk", [])) == ["news-1", "news-2"]


def test_create_creation_instance_explicit_name(ctx, tmp_project):
    methods.load_plugins()
    open_project_in(ctx, tmp_project)
    r = call(ctx, "project.create_creation_instance", {"type": "news_desk", "name": "briefing"})["result"]
    assert r["instance"] == "briefing"
    # An empty config.json was written (the single owner fills it on first edit).
    cfg = os.path.join(tmp_project.creation_instance_dir("news_desk", "briefing"), "config.json")
    assert os.path.isfile(cfg)


def test_create_creation_instance_unknown_type(ctx, tmp_project):
    methods.load_plugins()
    open_project_in(ctx, tmp_project)
    resp = call(ctx, "project.create_creation_instance", {"type": "no_such"})
    assert resp["error"]["code"] == -32602


def test_create_creation_instance_duplicate_name(ctx, tmp_project):
    methods.load_plugins()
    open_project_in(ctx, tmp_project)
    call(ctx, "project.create_creation_instance", {"type": "news_desk", "name": "dup"})
    resp = call(ctx, "project.create_creation_instance", {"type": "news_desk", "name": "dup"})
    assert resp["error"]["code"] == -32602


# ── Material domain (requires the news_video plugin registered) ───────────────

@pytest.fixture
def project_with_news(tmp_project):
    """tmp Project holding one empty news_video instance + the plugin loaded."""
    methods.load_plugins()  # registers the news_video MaterialType
    tmp_project.create_material_instance(
        "news_video",
        "news-1",
        initial_config={
            "schema_version": 1,
            "type_name": "news_video",
            "instance_name": "news-1",
            "display_name": "news-1",
        },
        config_filename="instance.json",
    )
    inst_dir = tmp_project.material_instance_dir("news_video", "news-1")
    os.makedirs(os.path.join(inst_dir, "source"), exist_ok=True)
    os.makedirs(os.path.join(inst_dir, "subtitles"), exist_ok=True)
    return tmp_project


def test_slot_readiness_serializes_dataclasses(ctx, project_with_news):
    open_project_in(ctx, project_with_news)
    resp = call(
        ctx, "material.slot_readiness", {"type": "news_video", "instance": "news-1"}
    )
    states = resp["result"]
    # SlotState dataclasses became plain dicts with the expected keys.
    assert isinstance(states, dict) and states
    any_state = next(iter(states.values()))
    assert set(any_state) >= {"slot_id", "is_locked", "is_filled", "summary"}


def test_get_artifact_absent_source_is_null(ctx, project_with_news):
    open_project_in(ctx, project_with_news)
    resp = call(
        ctx,
        "material.get_artifact",
        {"type": "news_video", "instance": "news-1", "key": "source"},
    )
    assert resp["result"] is None  # no source video imported yet


def test_get_artifact_unknown_type(ctx, project_with_news):
    open_project_in(ctx, project_with_news)
    resp = call(
        ctx,
        "material.get_artifact",
        {"type": "no_such_type", "instance": "x", "key": "source"},
    )
    assert resp["error"]["code"] == -32602
