"""Creation-domain write-surface tests (the first RPC writes).

Drives creation.load_config / list_components / update_component against a tmp
clip creation instance, asserting the patch persists to config.json (through
the single owner) and broadcasts event.creation.changed.
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


@pytest.fixture
def project_with_clip(tmp_project):
    """tmp Project with one clip creation instance whose config.json carries
    two components, plus the clip plugin registered."""
    methods.load_plugins()  # registers the clip CreationType (config_owner_cls)
    inst_dir = tmp_project.creation_instance_dir("clip", "clip-1")
    os.makedirs(inst_dir, exist_ok=True)
    config = {
        "source_subtitle": "en",
        "components": [
            {"id": "c1", "kind": "clip_subtitle", "enabled": True, "textOpacity": 1.0},
            {"id": "c2", "kind": "clip_hook_card", "enabled": True, "position": "upper-third"},
        ],
    }
    with open(os.path.join(inst_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    return tmp_project


def _open(ctx, project):
    resp = call(ctx, "project.open", {"folder": project.folder})
    assert "result" in resp, resp


def test_load_config_and_list_components(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    cfg = call(ctx, "creation.load_config", {"type": "clip", "instance": "clip-1"})["result"]
    assert cfg["source_subtitle"] == "en"
    assert len(cfg["components"]) == 2

    comps = call(ctx, "creation.list_components", {"type": "clip", "instance": "clip-1"})["result"]
    assert [c["id"] for c in comps] == ["c1", "c2"]


def test_update_component_persists_and_emits(ctx, project_with_clip, emit):
    _open(ctx, project_with_clip)
    resp = call(
        ctx,
        "creation.update_component",
        {"type": "clip", "instance": "clip-1", "component_id": "c1", "patch": {"enabled": False}},
    )
    assert resp["result"]["enabled"] is False
    assert ("event.creation.changed", {"type": "clip", "instance": "clip-1"}) in emit.events

    # Persisted to config.json on disk (through the single owner's save()).
    path = os.path.join(
        project_with_clip.creation_instance_dir("clip", "clip-1"), "config.json"
    )
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    c1 = next(c for c in on_disk["components"] if c["id"] == "c1")
    assert c1["enabled"] is False


def test_update_component_unknown_id(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(
        ctx,
        "creation.update_component",
        {"type": "clip", "instance": "clip-1", "component_id": "nope", "patch": {"enabled": False}},
    )
    assert resp["error"]["code"] == -32602


def test_update_component_cannot_rewrite_identity(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(
        ctx,
        "creation.update_component",
        {
            "type": "clip",
            "instance": "clip-1",
            "component_id": "c1",
            "patch": {"id": "hacked", "kind": "evil", "enabled": False},
        },
    )
    # id/kind are structural — the patch can't change them.
    assert resp["result"]["id"] == "c1"
    assert resp["result"]["kind"] == "clip_subtitle"
    assert resp["result"]["enabled"] is False


def test_unknown_creation_type(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(ctx, "creation.load_config", {"type": "no_such", "instance": "x"})
    assert resp["error"]["code"] == -32602


# ── creation.preview_data (clip provider over a bound material snapshot) ───────

@pytest.fixture
def project_with_bound_clip(tmp_project):
    """clip creation bound to a news_video instance that has a hotclips JSON +
    SRT, so the preview provider has real candidates to snapshot + return."""
    methods.load_plugins()
    from materials.news_video.model import NewsVideoModel

    tmp_project.create_material_instance(
        "news_video",
        "news-1",
        initial_config={"schema_version": 1, "type_name": "news_video", "instance_name": "news-1"},
        config_filename="instance.json",
    )
    subs = NewsVideoModel(tmp_project, "news-1").subtitles_dir
    os.makedirs(subs, exist_ok=True)
    with open(os.path.join(subs, "en.hotclips.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "clips": [
                    {"start": "00:00:05.000", "end": "00:00:35.000", "hook": "H0", "outro": "O0"},
                    {"start": "00:01:00.000", "end": "00:01:20.000", "hook": "H1", "outro": "O1"},
                ]
            },
            f,
        )
    with open(os.path.join(subs, "en.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:06,000 --> 00:00:08,000\nhi\n")

    clip_dir = tmp_project.creation_instance_dir("clip", "clip-1")
    os.makedirs(clip_dir, exist_ok=True)
    with open(os.path.join(clip_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "bound_material": {"type_name": "news_video", "instance_name": "news-1"},
                "source_subtitle": "en",
                "selected_clip_indices": [1],
                "components": [],
            },
            f,
        )
    return tmp_project


def test_preview_data_returns_candidates(ctx, project_with_bound_clip):
    _open(ctx, project_with_bound_clip)
    pd = call(ctx, "creation.preview_data", {"type": "clip", "instance": "clip-1"})["result"]
    assert pd["lang"] == "en"
    assert [c["hook"] for c in pd["candidates"]] == ["H0", "H1"]
    assert pd["selectedIndex"] == 1  # from selected_clip_indices
    # SRT was snapshotted into the clip instance dir (snapshot principle).
    assert pd["subtitlePath"] and pd["subtitlePath"].endswith("source-subtitles.en.srt")


def test_preview_data_unbound_is_empty(ctx, project_with_clip):
    _open(ctx, project_with_clip)  # clip-1 here has no bound_material
    pd = call(ctx, "creation.preview_data", {"type": "clip", "instance": "clip-1"})["result"]
    assert pd["candidates"] == []


def test_preview_data_no_provider(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(ctx, "creation.preview_data", {"type": "news_video", "instance": "x"})
    # news_video is a material type, not a creation → unknown creation type.
    assert resp["error"]["code"] == -32602
