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


@pytest.fixture
def isolated_presets(monkeypatch, tmp_path):
    """Redirect the global clip preset store to a tmp file so preset tests don't
    touch the user's real store (user_data/presets/clip_preset.json)."""
    import creations.clip.presets as presets
    monkeypatch.setattr(presets, "CLIP_PRESETS_PATH", str(tmp_path / "clip_preset.json"))


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


def test_update_config_crop_apply_to_all(ctx, project_with_clip, emit):
    """Style-tab 'apply crop to all': write crop_rect into every candidate's
    override via clips_overrides_merge; persists + emits."""
    _open(ctx, project_with_clip)
    crop = {"x": 0.1, "y": 0.0, "w": 0.5, "h": 1.0}
    resp = call(
        ctx,
        "creation.update_config",
        {
            "type": "clip",
            "instance": "clip-1",
            "patch": {"clips_overrides_merge": {"0": {"crop_rect": crop}, "1": {"crop_rect": crop}}},
        },
    )
    assert "result" in resp, resp
    assert ("event.creation.changed", {"type": "clip", "instance": "clip-1"}) in emit.events

    path = os.path.join(
        project_with_clip.creation_instance_dir("clip", "clip-1"), "config.json"
    )
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    # JSON object keys are strings; load() coerces back to int, save() re-stringifies.
    assert on_disk["clips_overrides"]["0"]["crop_rect"] == crop
    assert on_disk["clips_overrides"]["1"]["crop_rect"] == crop


def test_update_config_merge_preserves_siblings_and_clears(ctx, project_with_clip):
    """Deep-merge keeps other per-candidate override keys; a None value deletes
    just that key, and an emptied override is dropped."""
    _open(ctx, project_with_clip)
    # Seed candidate 0 with a hook override + a crop.
    call(
        ctx,
        "creation.update_config",
        {
            "type": "clip",
            "instance": "clip-1",
            "patch": {"clips_overrides_merge": {"0": {"hook": "kept", "crop_rect": {"x": 0, "y": 0, "w": 1, "h": 1}}}},
        },
    )
    # Clear only crop_rect → hook survives, override stays.
    call(
        ctx,
        "creation.update_config",
        {"type": "clip", "instance": "clip-1", "patch": {"clips_overrides_merge": {"0": {"crop_rect": None}}}},
    )
    path = os.path.join(
        project_with_clip.creation_instance_dir("clip", "clip-1"), "config.json"
    )
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["clips_overrides"]["0"] == {"hook": "kept"}


# ── component add / remove / reorder (the [+ Add] / 删除 / ↑↓ surface) ─────────


def test_list_addable_components(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    addable = call(
        ctx, "creation.list_addable_components", {"type": "clip", "instance": "clip-1"}
    )["result"]
    kinds = [a["kind"] for a in addable]
    assert kinds == [
        "clip_subtitle",
        "clip_text_watermark",
        "clip_image_watermark",
        "clip_hook_card",
        "clip_outro_card",
    ]
    by_kind = {a["kind"]: a["multi_instance"] for a in addable}
    assert by_kind["clip_subtitle"] is True
    assert by_kind["clip_hook_card"] is False  # single-instance


def test_add_component_unique_id_and_persist(ctx, project_with_clip, emit):
    _open(ctx, project_with_clip)
    # Add two subtitles — the spec hands out a fixed "sub1" id, so the owner
    # must make the second unique (the latent dup-id bug this surface fixes).
    comps = call(
        ctx, "creation.add_component", {"type": "clip", "instance": "clip-1", "kind": "clip_subtitle"}
    )["result"]
    comps = call(
        ctx, "creation.add_component", {"type": "clip", "instance": "clip-1", "kind": "clip_subtitle"}
    )["result"]
    # The fixture already has one subtitle (c1); plus the two just added = 3,
    # all with unique ids (the spec's fixed "sub1" is uniquified on add).
    sub_ids = [c["id"] for c in comps if c["kind"] == "clip_subtitle"]
    assert len(sub_ids) == 3
    assert len(set(sub_ids)) == 3  # unique
    assert ("event.creation.changed", {"type": "clip", "instance": "clip-1"}) in emit.events

    # New components land at the end of the list (lowest z), faithful to _on_add.
    assert comps[-1]["kind"] == "clip_subtitle"

    # Persisted, and each addressable independently by id.
    path = os.path.join(project_with_clip.creation_instance_dir("clip", "clip-1"), "config.json")
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    on_disk_ids = [c["id"] for c in on_disk["components"]]
    assert len(on_disk_ids) == len(set(on_disk_ids))  # all unique on disk


def test_add_subtitle_inherits_active_language(ctx, project_with_clip):
    """A newly added subtitle inherits source_subtitle so the first add works
    (faithful to style_panel._on_add); the user switches it for bilingual."""
    _open(ctx, project_with_clip)  # config source_subtitle == "en"
    comps = call(
        ctx, "creation.add_component", {"type": "clip", "instance": "clip-1", "kind": "clip_subtitle"}
    )["result"]
    added = comps[-1]
    assert added["kind"] == "clip_subtitle"
    assert added["language"] == "en"


def test_add_component_unknown_kind(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(
        ctx, "creation.add_component", {"type": "clip", "instance": "clip-1", "kind": "bogus"}
    )
    assert resp["error"]["code"] == -32602


def test_remove_component(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    comps = call(
        ctx, "creation.remove_component", {"type": "clip", "instance": "clip-1", "component_id": "c1"}
    )["result"]
    assert [c["id"] for c in comps] == ["c2"]


def test_move_component_reorders(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    # c1, c2 → move c2 up one → c2, c1.
    comps = call(
        ctx,
        "creation.move_component",
        {"type": "clip", "instance": "clip-1", "component_id": "c2", "delta": -1},
    )["result"]
    assert [c["id"] for c in comps] == ["c2", "c1"]
    # Out-of-range move is a no-op (c2 already at top).
    comps = call(
        ctx,
        "creation.move_component",
        {"type": "clip", "instance": "clip-1", "component_id": "c2", "delta": -1},
    )["result"]
    assert [c["id"] for c in comps] == ["c2", "c1"]


def test_load_dedupes_colliding_ids(ctx, tmp_project):
    """A config from the index-based Tk era can carry two components with the
    same id; load() must repair them so the id-based RPCs address each one."""
    methods.load_plugins()
    inst_dir = tmp_project.creation_instance_dir("clip", "dup-1")
    os.makedirs(inst_dir, exist_ok=True)
    with open(os.path.join(inst_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "components": [
                    {"id": "sub1", "kind": "clip_subtitle", "language": "zh"},
                    {"id": "sub1", "kind": "clip_subtitle", "language": "en"},
                ]
            },
            f,
        )
    _open(ctx, tmp_project)
    comps = call(ctx, "creation.list_components", {"type": "clip", "instance": "dup-1"})["result"]
    ids = [c["id"] for c in comps]
    assert len(ids) == len(set(ids))  # repaired to unique
    # Each is now independently patchable (was the dup-id bug).
    second_id = ids[1]
    resp = call(
        ctx,
        "creation.update_component",
        {"type": "clip", "instance": "dup-1", "component_id": second_id, "patch": {"language": "fr"}},
    )
    assert resp["result"]["language"] == "fr"


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
    # Every SUBTITLE language's SRT is exposed for bilingual subtitle components
    # (distinct from candidate/hotclips languages).
    assert "en" in pd["subtitlePaths"]
    assert pd["availableLangs"] == ["en"]  # hotclips langs
    assert "en" in pd["subtitleLangs"]  # SRT langs


def test_preview_data_unbound_is_empty(ctx, project_with_clip):
    _open(ctx, project_with_clip)  # clip-1 here has no bound_material
    pd = call(ctx, "creation.preview_data", {"type": "clip", "instance": "clip-1"})["result"]
    assert pd["candidates"] == []


# ── presets (Style-tab toolbar) ───────────────────────────────────────────────


def test_list_presets_has_builtins(isolated_presets, ctx, project_with_clip):
    _open(ctx, project_with_clip)
    res = call(ctx, "creation.list_presets", {"type": "clip", "instance": "clip-1"})["result"]
    assert "Default 9:16" in res["names"]
    assert "Default 9:16" in res["builtins"]


def test_apply_preset_replaces_components_and_output(isolated_presets, ctx, project_with_clip, emit):
    _open(ctx, project_with_clip)
    cfg = call(
        ctx,
        "creation.apply_preset",
        {"type": "clip", "instance": "clip-1", "name": "Default 9:16"},
    )["result"]
    assert cfg["output_aspect"] == "9:16"
    assert cfg["preset_name"] == "Default 9:16"
    # Default preset = subtitle + hook card; ids are unique after apply.
    kinds = [c["kind"] for c in cfg["components"]]
    assert "clip_subtitle" in kinds and "clip_hook_card" in kinds
    ids = [c["id"] for c in cfg["components"]]
    assert len(ids) == len(set(ids))
    assert ("event.creation.changed", {"type": "clip", "instance": "clip-1"}) in emit.events


def test_save_and_delete_user_preset(isolated_presets, ctx, project_with_clip):
    _open(ctx, project_with_clip)
    saved = call(
        ctx, "creation.save_preset", {"type": "clip", "instance": "clip-1", "name": "我的预设"}
    )["result"]
    assert "我的预设" in saved["names"]
    after = call(
        ctx, "creation.delete_preset", {"type": "clip", "instance": "clip-1", "name": "我的预设"}
    )["result"]
    assert "我的预设" not in after["names"]


def test_cannot_delete_builtin_preset(isolated_presets, ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(
        ctx, "creation.delete_preset", {"type": "clip", "instance": "clip-1", "name": "Default 9:16"}
    )
    assert resp["error"]["code"] == -32602


# ── render orchestration (plan_render / commit_render / delete_render) ─────────


def test_plan_render_selected_paths(ctx, project_with_bound_clip):
    """selected_clip_indices → output paths + geometry; out_idx ascends by src."""
    _open(ctx, project_with_bound_clip)  # config selects candidate index [1] (hook H1)
    plan = call(ctx, "creation.plan_render", {"type": "clip", "instance": "clip-1"})["result"]
    assert plan["mode"] == "reframe"
    assert plan["aspect"] == "9:16"
    assert len(plan["clips"]) == 1
    c = plan["clips"][0]
    assert c["srcIdx"] == 1 and c["outIdx"] == 1
    assert c["outputPath"].replace("\\", "/").endswith("clip_001_H1.mp4")  # hook in basename
    assert c["startSec"] == 60.0 and c["endSec"] == 80.0
    assert c["cropRect"] is None  # no per-candidate crop override


def test_commit_render_writes_sidecar_and_records(ctx, project_with_bound_clip, emit):
    _open(ctx, project_with_bound_clip)
    rendered = call(
        ctx,
        "creation.commit_render",
        {"type": "clip", "instance": "clip-1", "src_idx": 1, "out_idx": 1, "duration_sec": 20.0},
    )["result"]
    assert len(rendered) == 1
    assert rendered[0]["output_index"] == 1
    assert rendered[0]["file"] == "clip_001_H1.mp4"
    assert ("event.creation.changed", {"type": "clip", "instance": "clip-1"}) in emit.events

    inst_dir = project_with_bound_clip.creation_instance_dir("clip", "clip-1")
    with open(os.path.join(inst_dir, "clip_001_H1.json"), encoding="utf-8") as f:
        sidecar = json.load(f)
    assert sidecar["hook"] == "H1"
    assert sidecar["outro"] == "O1"
    assert sidecar["start_sec"] == 60.0 and sidecar["end_sec"] == 80.0
    assert sidecar["output_index"] == 1

    # rendered[] persisted to config.json.
    with open(os.path.join(inst_dir, "config.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    assert [r["output_index"] for r in on_disk["rendered"]] == [1]


def test_delete_render_unlinks_and_drops(ctx, project_with_bound_clip):
    _open(ctx, project_with_bound_clip)
    inst_dir = project_with_bound_clip.creation_instance_dir("clip", "clip-1")
    call(
        ctx,
        "creation.commit_render",
        {"type": "clip", "instance": "clip-1", "src_idx": 1, "out_idx": 1, "duration_sec": 20.0},
    )
    # Simulate the rendered mp4 on disk (the renderer writes it via vc:writeFile).
    with open(os.path.join(inst_dir, "clip_001_H1.mp4"), "wb") as f:
        f.write(b"\x00")

    rendered = call(
        ctx, "creation.delete_render", {"type": "clip", "instance": "clip-1", "out_idx": 1}
    )["result"]
    assert rendered == []
    assert not os.path.exists(os.path.join(inst_dir, "clip_001_H1.mp4"))
    assert not os.path.exists(os.path.join(inst_dir, "clip_001_H1.json"))


# ── publish docs (regression: clip's new-arch export also dropped them) ───────

def test_commit_render_writes_publish_docs(ctx, project_with_bound_clip):
    """commit_render writes the per-clip clip_NNN[_hook].md caption copy and an
    instance index.md. Regression guard: clip's new-arch export emitted only the
    JSON sidecar; the Tk clip_tool wrote the .md docs, so the new shell lost them.
    """
    _open(ctx, project_with_bound_clip)
    call(ctx, "creation.commit_render",
         {"type": "clip", "instance": "clip-1", "src_idx": 1, "out_idx": 1, "duration_sec": 20.0})

    inst_dir = project_with_bound_clip.creation_instance_dir("clip", "clip-1")
    md_path = os.path.join(inst_dir, "clip_001_H1.md")  # hook in basename
    assert os.path.isfile(md_path)
    assert "H1" in open(md_path, encoding="utf-8").read()  # hook section
    index = os.path.join(inst_dir, "index.md")
    assert os.path.isfile(index)
    assert "clip_001_H1.mp4" in open(index, encoding="utf-8").read()  # listed in table


def test_delete_render_rebuilds_index(ctx, project_with_bound_clip):
    """Deleting a clip removes its per-clip .md (via _existing_clip_files) and
    rebuilds index.md so the dropped clip no longer appears."""
    _open(ctx, project_with_bound_clip)
    inst_dir = project_with_bound_clip.creation_instance_dir("clip", "clip-1")
    call(ctx, "creation.commit_render",
         {"type": "clip", "instance": "clip-1", "src_idx": 1, "out_idx": 1, "duration_sec": 20.0})
    assert os.path.isfile(os.path.join(inst_dir, "clip_001_H1.md"))

    call(ctx, "creation.delete_render", {"type": "clip", "instance": "clip-1", "out_idx": 1})
    assert not os.path.exists(os.path.join(inst_dir, "clip_001_H1.md"))
    index = open(os.path.join(inst_dir, "index.md"), encoding="utf-8").read()
    assert "clip_001_H1.mp4" not in index  # rebuilt without the deleted clip


def test_preview_data_no_provider(ctx, project_with_clip):
    _open(ctx, project_with_clip)
    resp = call(ctx, "creation.preview_data", {"type": "news_video", "instance": "x"})
    # news_video is a material type, not a creation → unknown creation type.
    assert resp["error"]["code"] == -32602
