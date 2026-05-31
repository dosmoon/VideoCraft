"""Creation-domain RPC tests (news_desk): config owner + component CRUD.

The base RPC layer is creation-agnostic (ADR-0004): wiring
`config_owner_cls=NewsDeskInstanceConfig` is enough for the whole component +
config face to work, exactly as clip's. These drive the dispatch kernel against
a tmp news_desk instance, mirroring test_creation.py's (ctx + _open) pattern.

Presets and the preview/render/import providers are all wired now; the preset
builtins are canonical (component_defs is the single shape source after the Tk
workbench retired). The preset RPCs are covered at the bottom of this file.
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


# ── material binding (ADR-0005; the new-arch create flow makes unbound) ───────

def test_bind_material_sets_bound_material(ctx, project_with_news_desk, emit):
    """A fresh creation is unbound; bind_material writes bound_material via the
    single owner, persists, and broadcasts so the preview can refresh."""
    _open(ctx, project_with_news_desk)
    cfg = call(ctx, "creation.bind_material", {
        "type": "news_desk", "instance": "news",
        "material_type": "news_video", "material_instance": "demo",
    })["result"]
    assert cfg["bound_material"]["type_name"] == "news_video"
    assert cfg["bound_material"]["instance_name"] == "demo"
    assert ("event.creation.changed",
            {"type": "news_desk", "instance": "news"}) in emit.events
    # persisted on disk
    path = os.path.join(
        project_with_news_desk.creation_instance_dir("news_desk", "news"), "config.json")
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["bound_material"]["instance_name"] == "demo"


def test_bind_material_rejects_empty(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    resp = call(ctx, "creation.bind_material", {
        "type": "news_desk", "instance": "news",
        "material_type": "", "material_instance": "demo",
    })
    assert "error" in resp


# ── preview provider (news_desk: full-source media + snapshot SRTs) ───────────

@pytest.fixture
def project_with_bound_news_desk(tmp_project):
    """news_desk instance bound to a news_video material, with a subtitle
    component whose snapshot SRT exists in the instance dir — enough for the
    preview provider to resolve mediaRef + subtitlePaths."""
    methods.load_plugins()
    tmp_project.create_material_instance(
        "news_video", "news-1",
        initial_config={"schema_version": 1, "type_name": "news_video", "instance_name": "news-1"},
        config_filename="instance.json",
    )
    inst_dir = tmp_project.creation_instance_dir("news_desk", "news")
    os.makedirs(os.path.join(inst_dir, "subtitles"), exist_ok=True)
    with open(os.path.join(inst_dir, "subtitles", "sub.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nhello\n")
    with open(os.path.join(inst_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "bound_material": {"type_name": "news_video", "instance_name": "news-1"},
                "components": [
                    {"id": "sub", "kind": "subtitle", "srt_path": "subtitles/sub.srt"},
                    # a subtitle with no snapshot yet → excluded from subtitlePaths
                    {"id": "sub2", "kind": "subtitle", "srt_path": ""},
                    {"id": "chap", "kind": "chapter"},
                ],
            },
            f,
        )
    return tmp_project


def test_preview_data_returns_media_and_snapshot_srt(ctx, project_with_bound_news_desk):
    _open(ctx, project_with_bound_news_desk)
    pd = call(ctx, "creation.preview_data", {"type": "news_desk", "instance": "news"})["result"]
    # mediaRef = the bound material's source video path.
    from materials.news_video.model import NewsVideoModel
    expected = NewsVideoModel(project_with_bound_news_desk, "news-1").source_video_path
    assert pd["mediaRef"] == expected
    assert isinstance(pd["durationSec"], float)
    # Only the subtitle whose snapshot exists is resolved, keyed by its srt_path.
    assert list(pd["subtitlePaths"].keys()) == ["subtitles/sub.srt"]
    assert pd["subtitlePaths"]["subtitles/sub.srt"].endswith("sub.srt")
    assert os.path.isfile(pd["subtitlePaths"]["subtitles/sub.srt"])


def test_preview_data_unbound_is_empty(ctx, project_with_news_desk):
    """The fixture instance has no bound_material → empty preview shape."""
    _open(ctx, project_with_news_desk)
    pd = call(ctx, "creation.preview_data", {"type": "news_desk", "instance": "news"})["result"]
    assert pd == {"mediaRef": None, "durationSec": 0.0, "subtitlePaths": {}}


# ── render provider (news_desk: single full-source output) ────────────────────

def test_plan_render_single_output(ctx, project_with_bound_news_desk):
    _open(ctx, project_with_bound_news_desk)
    plan = call(ctx, "creation.plan_render", {"type": "news_desk", "instance": "news"})["result"]
    from materials.news_video.model import NewsVideoModel
    expected = NewsVideoModel(project_with_bound_news_desk, "news-1").source_video_path
    assert plan["mediaRef"] == expected
    assert plan["outIdx"] == 1
    assert plan["outputPath"].replace("\\", "/").endswith("output.mp4")
    assert isinstance(plan["durationSec"], float)


def test_commit_render_writes_sidecar_and_records(ctx, project_with_bound_news_desk, emit):
    _open(ctx, project_with_bound_news_desk)
    rendered = call(
        ctx, "creation.commit_render",
        {"type": "news_desk", "instance": "news", "src_idx": 0, "out_idx": 1, "duration_sec": 42.0},
    )["result"]
    assert len(rendered) == 1
    assert rendered[0]["file"] == "output.mp4"
    assert rendered[0]["output_index"] == 1
    assert ("event.creation.changed", {"type": "news_desk", "instance": "news"}) in emit.events

    inst_dir = project_with_bound_news_desk.creation_instance_dir("news_desk", "news")
    with open(os.path.join(inst_dir, "output.json"), encoding="utf-8") as f:
        sidecar = json.load(f)
    assert sidecar["duration_sec"] == 42.0
    assert sidecar["output_index"] == 1
    # rendered[] persisted into config.json.
    with open(os.path.join(inst_dir, "config.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    assert [r["output_index"] for r in on_disk["rendered"]] == [1]


def test_delete_render_unlinks_and_clears(ctx, project_with_bound_news_desk):
    _open(ctx, project_with_bound_news_desk)
    inst_dir = project_with_bound_news_desk.creation_instance_dir("news_desk", "news")
    call(
        ctx, "creation.commit_render",
        {"type": "news_desk", "instance": "news", "src_idx": 0, "out_idx": 1, "duration_sec": 42.0},
    )
    # Simulate the renderer's mp4 on disk (written via vc:writeFile in the app).
    with open(os.path.join(inst_dir, "output.mp4"), "wb") as f:
        f.write(b"\x00")

    rendered = call(
        ctx, "creation.delete_render", {"type": "news_desk", "instance": "news", "out_idx": 1}
    )["result"]
    assert rendered == []
    assert not os.path.exists(os.path.join(inst_dir, "output.mp4"))
    assert not os.path.exists(os.path.join(inst_dir, "output.json"))


# ── import provider (snapshot subtitle SRT / chapter schedule from material) ──

def _seed_material_artifacts(project):
    """Populate the bound news_video material with two subtitle languages + an
    analysis.json envelope, so the import provider has something to snapshot."""
    from materials.news_video.model import NewsVideoModel

    model = NewsVideoModel(project, "news-1")
    os.makedirs(model.subtitles_dir, exist_ok=True)
    with open(os.path.join(model.subtitles_dir, "zh.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n你好\n")
    with open(os.path.join(model.subtitles_dir, "en.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nhello\n")
    with open(os.path.join(model.subtitles_dir, "zh.analysis.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "schema_version": 2,
                "chapters": [
                    {"start_sec": 0.0, "end_sec": 30.0, "title": "开始", "refined": "intro", "key_points": ["a"]},
                    {"start_sec": 30.0, "end_sec": 90.0, "title": "正文", "refined": "body", "key_points": []},
                ],
            },
            f,
        )


def test_list_imports_reports_material_artifacts(ctx, project_with_bound_news_desk):
    _seed_material_artifacts(project_with_bound_news_desk)
    _open(ctx, project_with_bound_news_desk)
    res = call(ctx, "creation.list_imports", {"type": "news_desk", "instance": "news"})["result"]
    assert res["subtitleLangs"] == ["en", "zh"]
    assert res["analyses"] == ["zh.analysis.json"]


def test_import_subtitle_snapshots_and_sets_srt_path(ctx, project_with_bound_news_desk, emit):
    _seed_material_artifacts(project_with_bound_news_desk)
    _open(ctx, project_with_bound_news_desk)
    comp = call(
        ctx, "creation.import_resource",
        {"type": "news_desk", "instance": "news", "component_id": "sub2",
         "params": {"kind": "subtitle", "lang": "zh"}},
    )["result"]
    assert comp["srt_path"] == "subtitles/sub2.srt"
    assert ("event.creation.changed", {"type": "news_desk", "instance": "news"}) in emit.events
    # The SRT was snapshotted into the creation instance dir (snapshot principle).
    inst_dir = project_with_bound_news_desk.creation_instance_dir("news_desk", "news")
    snap = os.path.join(inst_dir, "subtitles", "sub2.srt")
    assert os.path.isfile(snap)
    assert "你好" in open(snap, encoding="utf-8").read()
    # Persisted into config.json.
    with open(os.path.join(inst_dir, "config.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    sub2 = next(c for c in on_disk["components"] if c["id"] == "sub2")
    assert sub2["srt_path"] == "subtitles/sub2.srt"


def test_import_invalidates_owner_cache_so_relist_keeps_srt_path(
    ctx, project_with_bound_news_desk
):
    """Regression: the import provider writes config.json out-of-band, so the
    session's cached owner went stale — list_components after import (e.g. on
    switching instances and back) returned the pre-import component and the
    import appeared to vanish. The cache must be invalidated so a relist reflects
    the snapshot."""
    _seed_material_artifacts(project_with_bound_news_desk)
    _open(ctx, project_with_bound_news_desk)
    # Caches the owner (mirrors the workbench having loaded components once).
    before = call(ctx, "creation.list_components", {"type": "news_desk", "instance": "news"})["result"]
    assert next(c for c in before if c["id"] == "sub2").get("srt_path", "") == ""
    call(ctx, "creation.import_resource",
         {"type": "news_desk", "instance": "news", "component_id": "sub2",
          "params": {"kind": "subtitle", "lang": "zh"}})
    # Relist — the cache must have been invalidated and reloaded from disk.
    after = call(ctx, "creation.list_components", {"type": "news_desk", "instance": "news"})["result"]
    assert next(c for c in after if c["id"] == "sub2")["srt_path"] == "subtitles/sub2.srt"


def test_import_chapters_fills_schedule(ctx, project_with_bound_news_desk):
    _seed_material_artifacts(project_with_bound_news_desk)
    _open(ctx, project_with_bound_news_desk)
    comp = call(
        ctx, "creation.import_resource",
        {"type": "news_desk", "instance": "news", "component_id": "chap",
         "params": {"kind": "chapters", "filename": "zh.analysis.json"}},
    )["result"]
    sched = comp["schedule"]
    assert [s["title"] for s in sched] == ["开始", "正文"]
    assert sched[0]["start_sec"] == 0.0 and sched[0]["end_sec"] == 30.0
    assert sched[0]["key_points"] == ["a"]


def test_import_subtitle_unknown_lang(ctx, project_with_bound_news_desk):
    _seed_material_artifacts(project_with_bound_news_desk)
    _open(ctx, project_with_bound_news_desk)
    resp = call(
        ctx, "creation.import_resource",
        {"type": "news_desk", "instance": "news", "component_id": "sub2",
         "params": {"kind": "subtitle", "lang": "fr"}},
    )
    assert resp["error"]["code"] == -32602


def test_import_wrong_component_kind(ctx, project_with_bound_news_desk):
    _seed_material_artifacts(project_with_bound_news_desk)
    _open(ctx, project_with_bound_news_desk)
    # chapters import targeting a subtitle component → rejected.
    resp = call(
        ctx, "creation.import_resource",
        {"type": "news_desk", "instance": "news", "component_id": "sub2",
         "params": {"kind": "chapters", "filename": "zh.analysis.json"}},
    )
    assert resp["error"]["code"] == -32602


# ── presets (canonical builtins; component_defs is the single shape source) ───

def test_list_presets_returns_builtins(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    res = call(ctx, "creation.list_presets",
               {"type": "news_desk", "instance": "news"})["result"]
    assert "新闻发布会" in res["names"]
    assert "新闻发布会" in res["builtins"]
    assert res["lastUsed"]  # current preset_name or the default


def test_apply_preset_replaces_components(ctx, project_with_news_desk, emit):
    """Applying 极简 (a single subtitle) wholesale-replaces the fixture's two
    components, sets preset_name, re-uniques ids, persists, and broadcasts."""
    _open(ctx, project_with_news_desk)
    cfg = call(ctx, "creation.apply_preset",
               {"type": "news_desk", "instance": "news", "name": "极简"})["result"]
    assert cfg["preset_name"] == "极简"
    assert [c["kind"] for c in cfg["components"]] == ["subtitle"]
    # canonical fractional shape (component_defs single source), not legacy px
    sub = cfg["components"][0]
    assert "fontsize_pct" in sub and "fontsize" not in sub
    ids = [c["id"] for c in cfg["components"]]
    assert len(ids) == len(set(ids)) and all(ids)
    assert ("event.creation.changed",
            {"type": "news_desk", "instance": "news"}) in emit.events


def test_apply_unknown_preset_errors(ctx, project_with_news_desk):
    _open(ctx, project_with_news_desk)
    resp = call(ctx, "creation.apply_preset",
                {"type": "news_desk", "instance": "news", "name": "不存在的预设"})
    assert "error" in resp


def test_save_and_delete_user_preset(ctx, project_with_news_desk, tmp_path, monkeypatch):
    """save_preset upserts the current components as a user preset (then lists);
    delete_preset removes it. Builtins are protected on both. The preset store
    is redirected to tmp so the test never touches user_data."""
    from creations.news_desk import presets as nd_presets
    monkeypatch.setattr(nd_presets, "PRESETS_PATH", str(tmp_path / "store.json"))
    _open(ctx, project_with_news_desk)

    saved = call(ctx, "creation.save_preset",
                 {"type": "news_desk", "instance": "news", "name": "我的预设"})["result"]
    assert "我的预设" in saved["names"]

    # builtin name is protected on save
    resp = call(ctx, "creation.save_preset",
                {"type": "news_desk", "instance": "news", "name": "新闻发布会"})
    assert "error" in resp

    deleted = call(ctx, "creation.delete_preset",
                   {"type": "news_desk", "instance": "news", "name": "我的预设"})["result"]
    assert "我的预设" not in deleted["names"]

    # builtins are protected on delete too
    resp = call(ctx, "creation.delete_preset",
                {"type": "news_desk", "instance": "news", "name": "新闻发布会"})
    assert "error" in resp
