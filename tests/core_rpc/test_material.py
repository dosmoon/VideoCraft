"""Material-domain RPC tests (news_video): create instance, context round-trip,
source acquisition, ASR / analysis jobs, AI fill, chapter save.

Mirrors test_creation_news_desk.py's (ctx + _open + call) pattern. The base RPC
layer is material-agnostic (ADR-0004): the type string drives the registry's
instance_factory, and the model owns dataclass conversion (write_*_dict), so this
layer just shuttles dicts. Long jobs run on daemon threads; tests run the job
work inline by monkeypatching JobRegistry.start so assertions are deterministic
(no sleeps), then check the same emit/persistence the threaded path would produce.
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


@pytest.fixture(autouse=True)
def _plugins():
    """Register every plugin (news_video MaterialType) before each test."""
    methods.load_plugins()


@pytest.fixture
def inline_jobs(ctx, monkeypatch):
    """Run jobs synchronously (no daemon thread) so assertions don't race.

    Mirrors JobRegistry.runner's terminal-event contract exactly, just inline:
    work(job) runs, then a terminal event.job fires with the same status/result/
    error shape the threaded path produces."""
    from core_rpc.jobs import Job

    seq = {"n": 0}

    def start(kind, work):
        seq["n"] += 1
        job = Job(id=f"job-{seq['n']}", kind=kind, _emit=ctx.emit)
        status, result, error = "succeeded", None, None
        try:
            result = work(job)
            if job.cancelled:
                status = "cancelled"
        except Exception as exc:  # noqa: BLE001 — mirror runner
            status, error = "failed", str(exc)
        payload = {"job_id": job.id, "kind": kind, "status": status}
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        ctx.emit("event.job", payload)
        return job.id

    monkeypatch.setattr(ctx.jobs, "start", start)
    return ctx


def _terminal(emit):
    """The last terminal event.job payload (status/result/error)."""
    jobs = emit.of("event.job")
    assert jobs, "no terminal event.job emitted"
    return jobs[-1]


# ── language catalog (ASR/translate/import picker) ───────────────────────────

def test_list_languages(ctx):
    langs = call(ctx, "system.list_languages")["result"]
    assert len(langs) > 50
    assert [l["iso"] for l in langs[:6]] == ["ar", "zh", "en", "fr", "ru", "es"]  # UN-6 first
    en = next(l for l in langs if l["iso"] == "en")
    assert "English" in en["display"] and "—" in en["display"]


def test_get_locale(ctx):
    # The renderer awaits this at boot; it must echo i18n.get_current_lang.
    from i18n import get_current_lang

    lang = call(ctx, "system.get_locale")["result"]["lang"]
    assert lang == get_current_lang()
    assert lang in ("zh", "en")


def test_set_locale_round_trip(ctx, tmp_path, monkeypatch):
    # Persist hot-switch choice back to settings.json. Redirect the settings file
    # to a tmp path so the real user_data/settings.json is never touched.
    import i18n

    monkeypatch.setattr(i18n, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    assert call(ctx, "system.set_locale", {"lang": "zh"})["result"]["lang"] == "zh"
    assert call(ctx, "system.get_locale")["result"]["lang"] == "zh"
    assert call(ctx, "system.set_locale", {"lang": "en"})["result"]["lang"] == "en"


def test_set_locale_rejects_unsupported(ctx, tmp_path, monkeypatch):
    import i18n

    monkeypatch.setattr(i18n, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    resp = call(ctx, "system.set_locale", {"lang": "xx"})
    assert "error" in resp  # ValueError → HANDLER_ERROR, channel survives


# ── create instance + type listing (M0) ──────────────────────────────────────

def test_list_material_types_info(ctx, tmp_project):
    _open(ctx, tmp_project)
    types = call(ctx, "project.list_material_types_info")["result"]
    by_name = {t["type_name"]: t for t in types}
    assert "news_video" in by_name
    assert by_name["news_video"]["single_instance"] is True
    assert by_name["news_video"]["description_zh"]  # user-facing, never raw name


def test_create_material_instance(ctx, tmp_project, emit):
    _open(ctx, tmp_project)
    res = call(ctx, "project.create_material_instance", {"type": "news_video"})["result"]
    assert res == {"type": "news_video", "instance": "news-1"}
    # Skeleton slot dirs exist so later source/ASR writes don't ENOENT.
    inst_dir = tmp_project.material_instance_dir("news_video", "news-1")
    assert os.path.isdir(os.path.join(inst_dir, "source"))
    assert os.path.isdir(os.path.join(inst_dir, "subtitles"))
    assert os.path.isfile(os.path.join(inst_dir, "instance.json"))
    assert ("event.materials.changed", {"type": "news_video", "instance": "news-1"}) in emit.events
    # It shows up in the tree.
    assert call(ctx, "project.list_materials")["result"]["news_video"] == ["news-1"]


def test_material_instance_dir_rpc(ctx, tmp_project):
    """The generic framework dir resolver the TS material model uses (ADR-0008),
    symmetric to project.creation_instance_dir."""
    _open(ctx, tmp_project)
    call(ctx, "project.create_material_instance", {"type": "news_video"})  # news-1
    d = call(ctx, "project.material_instance_dir", {"type": "news_video", "instance": "news-1"})["result"]
    assert d == tmp_project.material_instance_dir("news_video", "news-1")
    assert d.replace("\\", "/").endswith("materials/news_video/news-1")


def test_project_source_meta_writes(ctx, tmp_project):
    """The project-meta write RPCs the TS material backend calls after capability
    jobs (which touch no project meta): commit_source / set_source_language /
    add_translated_language (ADR-0008 B3.2)."""
    _open(ctx, tmp_project)
    src = call(ctx, "project.commit_source", {
        "source": {"origin": "link", "url": "http://x"},
        "title": "Briefing", "duration_sec": 90.0, "width": 1920, "height": 1080,
    })["result"]
    assert src["title"] == "Briefing" and src["width"] == 1920
    # Persisted: project.current reflects the session project's live meta.
    meta = call(ctx, "project.current")["result"]["meta"]
    assert meta["source"]["title"] == "Briefing"

    assert call(ctx, "project.set_source_language", {"lang": "en"})["result"] == {"source": "en"}
    assert call(ctx, "project.current")["result"]["meta"]["language"]["source"] == "en"

    call(ctx, "project.add_translated_language", {"lang": "zh"})
    again = call(ctx, "project.add_translated_language", {"lang": "zh"})["result"]  # idempotent
    assert again == {"translated_to": ["zh"]}
    assert call(ctx, "project.add_translated_language", {"lang": "ja"})["result"]["translated_to"] == ["zh", "ja"]

    # validation
    assert "error" in call(ctx, "project.set_source_language", {"lang": ""})


def test_create_material_instance_autonumbers(ctx, tmp_project):
    _open(ctx, tmp_project)
    call(ctx, "project.create_material_instance", {"type": "news_video"})
    second = call(ctx, "project.create_material_instance", {"type": "news_video"})["result"]
    assert second["instance"] == "news-2"


def test_rename_and_delete_material_instance(ctx, tmp_project, emit):
    _open(ctx, tmp_project)
    call(ctx, "project.create_material_instance", {"type": "news_video"})  # news-1
    # rename → dir moves, tree reflects it, change event fires
    res = call(ctx, "project.rename_instance",
               {"kind": "material", "type": "news_video", "instance": "news-1", "new_name": "renamed"})["result"]
    assert res == {"type": "news_video", "instance": "renamed"}
    assert call(ctx, "project.list_materials")["result"]["news_video"] == ["renamed"]
    assert not os.path.isdir(tmp_project.material_instance_dir("news_video", "news-1"))
    assert os.path.isdir(tmp_project.material_instance_dir("news_video", "renamed"))
    assert ("event.materials.changed", {"type": "news_video", "instance": "renamed"}) in emit.events
    # collision rejected
    call(ctx, "project.create_material_instance", {"type": "news_video", "name": "other"})
    assert "error" in call(ctx, "project.rename_instance",
                           {"kind": "material", "type": "news_video", "instance": "other", "new_name": "renamed"})
    # delete → gone from disk + tree
    assert call(ctx, "project.delete_instance",
                {"kind": "material", "type": "news_video", "instance": "renamed"})["result"] == {"ok": True}
    assert "renamed" not in call(ctx, "project.list_materials")["result"].get("news_video", [])
    assert not os.path.isdir(tmp_project.material_instance_dir("news_video", "renamed"))


def test_rename_instance_rejects_bad_name_and_unknown_kind(ctx, tmp_project):
    _open(ctx, tmp_project)
    call(ctx, "project.create_material_instance", {"type": "news_video"})
    assert "error" in call(ctx, "project.rename_instance",
                           {"kind": "material", "type": "news_video", "instance": "news-1", "new_name": "bad/name"})
    assert "error" in call(ctx, "project.delete_instance",
                           {"kind": "nope", "type": "news_video", "instance": "news-1"})


def test_create_material_instance_duplicate_name_rejected(ctx, tmp_project):
    _open(ctx, tmp_project)
    call(ctx, "project.create_material_instance", {"type": "news_video", "name": "news-1"})
    resp = call(ctx, "project.create_material_instance", {"type": "news_video", "name": "news-1"})
    assert resp["error"]["code"] == -32602


def test_create_unknown_material_type_rejected(ctx, tmp_project):
    _open(ctx, tmp_project)
    resp = call(ctx, "project.create_material_instance", {"type": "nope"})
    assert resp["error"]["code"] == -32602


# ── context (15 fields) + basic_info round-trip (M1) ─────────────────────────

@pytest.fixture
def project_with_material(tmp_project):
    """tmp Project with one news_video instance (source/ + subtitles/ dirs)."""
    tmp_project.create_material_instance(
        "news_video", "news-1",
        initial_config={"schema_version": 1, "type_name": "news_video", "instance_name": "news-1"},
        config_filename="instance.json",
    )
    inst_dir = tmp_project.material_instance_dir("news_video", "news-1")
    os.makedirs(os.path.join(inst_dir, "source"), exist_ok=True)
    os.makedirs(os.path.join(inst_dir, "subtitles"), exist_ok=True)
    return tmp_project


def test_context_round_trip(ctx, project_with_material, emit):
    _open(ctx, project_with_material)
    written = {"host": "张三", "episode_topic": "发布会", "background": "多行\n背景"}
    stored = call(ctx, "material.write_context",
                  {"type": "news_video", "instance": "news-1", "context": written})["result"]
    # All 15 fields present; provided ones set, the rest empty.
    assert stored["host"] == "张三"
    assert stored["episode_topic"] == "发布会"
    assert stored["background"] == "多行\n背景"
    assert stored["guests"] == ""
    assert len(stored) == 15
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events
    # Re-read from disk via a fresh call matches.
    again = call(ctx, "material.read_context", {"type": "news_video", "instance": "news-1"})["result"]
    assert again == stored
    # Persisted to source/context.json.
    path = os.path.join(
        project_with_material.material_instance_dir("news_video", "news-1"), "source", "context.json")
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["host"] == "张三"


def test_basic_info_round_trip(ctx, project_with_material):
    _open(ctx, project_with_material)
    stored = call(ctx, "material.write_basic_info",
                  {"type": "news_video", "instance": "news-1",
                   "basic_info": {"host": "李四", "event_date": "2026-05-31"}})["result"]
    assert stored["host"] == "李四"
    assert stored["event_date"] == "2026-05-31"
    assert len(stored) == 5
    again = call(ctx, "material.read_basic_info", {"type": "news_video", "instance": "news-1"})["result"]
    assert again == stored


def test_context_completion(ctx, project_with_material):
    _open(ctx, project_with_material)
    call(ctx, "material.write_context",
         {"type": "news_video", "instance": "news-1", "context": {"host": "x", "guests": "y"}})
    comp = call(ctx, "material.context_completion", {"type": "news_video", "instance": "news-1"})["result"]
    assert comp == {"filled": 2, "total": 15}


def test_write_context_rejects_non_object(ctx, project_with_material):
    _open(ctx, project_with_material)
    resp = call(ctx, "material.write_context",
                {"type": "news_video", "instance": "news-1", "context": "nope"})
    assert resp["error"]["code"] == -32602


# ── source acquisition job (M2) ──────────────────────────────────────────────

def test_set_source_local(inline_jobs, project_with_material, emit, monkeypatch):
    """A local import job: mocked acquire writes the dest video + returns probe
    values; the handler commits them and the slot fills."""
    ctx = inline_jobs
    _open(ctx, project_with_material)
    import core.source_acquire as sa

    def fake_acquire(src, dest_video, dest_meta, *, progress_cb=None, cancel_token=None):
        os.makedirs(os.path.dirname(dest_video), exist_ok=True)
        with open(dest_video, "wb") as f:
            f.write(b"\x00\x00\x00\x00")  # non-empty so source_status == ready
        if progress_cb:
            progress_cb(sa.ProgressInfo(phase="copying", percent=100.0))
        return sa.AcquireResult(title="My Clip", duration_sec=12.5, width=1920, height=1080, info_json={})

    monkeypatch.setattr(sa, "acquire", fake_acquire)

    resp = call(ctx, "material.set_source", {
        "type": "news_video", "instance": "news-1",
        "source": {"origin": "local", "imported_from": "C:/tmp/in.mp4"},
    })
    assert "job_id" in resp["result"]
    term = _terminal(emit)
    assert term["status"] == "succeeded"
    assert term["result"]["title"] == "My Clip"
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events
    # progress tick forwarded as progress.material.source
    assert any(m == "progress.material.source" for m, _ in emit.events)
    # Slot now ready (probe values stamped on project.meta.source).
    ready = call(ctx, "material.slot_readiness", {"type": "news_video", "instance": "news-1"})["result"]
    assert ready["source"]["is_filled"] is True


def test_set_source_failure_surfaces_category(inline_jobs, project_with_material, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, project_with_material)
    import core.source_acquire as sa

    def boom(*a, **k):
        raise sa.AcquireError(sa.ERR_JS_RUNTIME, "缺少 Node.js JS 运行时", "node not found")

    monkeypatch.setattr(sa, "acquire", boom)

    call(ctx, "material.set_source", {
        "type": "news_video", "instance": "news-1",
        "source": {"origin": "link", "url": "https://example.com/v"},
    })
    term = _terminal(emit)
    assert term["status"] == "failed"
    assert term["error"].startswith("js_runtime:")  # category prefix for the UI hint


def test_set_source_cancel_marks_cancelled(inline_jobs, project_with_material, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, project_with_material)
    import core.source_acquire as sa

    def cancel_during(src, dest_video, dest_meta, *, progress_cb=None, cancel_token=None):
        cancel_token.cancel()  # simulate the user hitting cancel mid-acquire
        raise sa.AcquireError(sa.ERR_CANCELLED, "已取消", "User cancelled")

    monkeypatch.setattr(sa, "acquire", cancel_during)
    call(ctx, "material.set_source", {
        "type": "news_video", "instance": "news-1",
        "source": {"origin": "local", "imported_from": "x"},
    })
    assert _terminal(emit)["status"] == "cancelled"


# ── ASR + analysis jobs (M3 / M4) ────────────────────────────────────────────

@pytest.fixture
def project_with_subtitles(project_with_material):
    """news_video instance with a source SRT on disk (en.srt)."""
    from materials.news_video.model import NewsVideoModel

    model = NewsVideoModel(project_with_material, "news-1")
    os.makedirs(model.subtitles_dir, exist_ok=True)
    with open(os.path.join(model.subtitles_dir, "en.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:30,000\nhello\n\n2\n00:00:30,000 --> 00:01:30,000\nworld\n")
    return project_with_material


def test_run_asr_job_writes_srt(inline_jobs, project_with_material, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, project_with_material)

    def fake_run_asr(project, *, source_lang_iso=None, progress_cb=None, cancel_token=None):
        from materials.news_video import paths as p
        sd = p.subtitles_dir(project)
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "en.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:03,000\nhi\n")
        return {"lang_iso": "en", "srt_path": os.path.join(sd, "en.srt"), "segment_count": 1}

    monkeypatch.setattr("core.subtitle_pipeline.run_asr", fake_run_asr)

    call(ctx, "material.run_asr", {"type": "news_video", "instance": "news-1"})
    assert _terminal(emit)["status"] == "succeeded"
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events
    langs = call(ctx, "material.list_subtitle_languages", {"type": "news_video", "instance": "news-1"})["result"]
    assert langs == ["en"]


def test_run_analysis_job_writes_analysis(inline_jobs, project_with_subtitles, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, project_with_subtitles)

    def fake_run(kind, srt, subtitles_dir, lang_iso, progress_cb, cancel_token):
        path = os.path.join(subtitles_dir, f"{lang_iso}.analysis.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 2, "titles": ["T"],
                       "chapters": [{"start_sec": 0.0, "end_sec": 30.0, "title": "a"}]}, f)
        return {"path": path, "kind": kind}

    monkeypatch.setattr("core.subtitle_analysis_runners.run", fake_run)

    call(ctx, "material.run_analysis",
         {"type": "news_video", "instance": "news-1", "lang": "en", "analysis_kind": "analysis"})
    assert _terminal(emit)["status"] == "succeeded"
    files = call(ctx, "material.list_analyses", {"type": "news_video", "instance": "news-1"})["result"]
    assert files == ["en.analysis.json"]
    summary = call(ctx, "material.analysis_summary",
                   {"type": "news_video", "instance": "news-1", "filename": "en.analysis.json"})["result"]
    assert summary["chapter_count"] == 1 and summary["title_count"] == 1


def test_save_chapters_normalizes(ctx, project_with_subtitles, emit):
    """Reordered chapters with no 00:00 start → server sorts + inserts the
    synthetic intro + sets end=next.start (exercises chapters_io)."""
    _open(ctx, project_with_subtitles)
    from materials.news_video.model import NewsVideoModel
    model = NewsVideoModel(project_with_subtitles, "news-1")
    # Seed an analysis.json so save_analysis_chapters_only preserves its titles.
    with open(os.path.join(model.subtitles_dir, "en.analysis.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "titles": ["keep"], "chapters": []}, f)

    env = call(ctx, "material.save_chapters", {
        "type": "news_video", "instance": "news-1", "filename": "en.analysis.json", "lang": "en",
        "chapters": [
            {"start": "00:00:40", "title": "second", "refined": "r2", "key_points": ["k"]},
            {"start": "00:00:10", "title": "first", "refined": "r1", "key_points": []},
        ],
    })["result"]
    titles = [c["title"] for c in env["chapters"]]
    # Sorted by start; synthetic 00:00 intro prepended (first real starts at 0:10).
    assert env["chapters"][0]["start"] == "00:00:00"
    assert titles[1:] == ["first", "second"]
    assert env["titles"] == ["keep"]  # preserved
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events


# ── subtitle view + quality check + import + analysis artifacts (gaps B/D) ───

def test_read_subtitle(ctx, project_with_subtitles):
    _open(ctx, project_with_subtitles)
    res = call(ctx, "material.read_subtitle", {"type": "news_video", "instance": "news-1", "lang": "en"})["result"]
    assert "hello" in res["text"] and "world" in res["text"]


def test_read_subtitle_missing(ctx, project_with_subtitles):
    _open(ctx, project_with_subtitles)
    resp = call(ctx, "material.read_subtitle", {"type": "news_video", "instance": "news-1", "lang": "zz"})
    assert resp["error"]["code"] == -32602


def test_check_subtitle_clean(ctx, project_with_subtitles):
    _open(ctx, project_with_subtitles)
    chk = call(ctx, "material.check_subtitle", {"type": "news_video", "instance": "news-1", "lang": "en"})["result"]
    assert chk["cue_count"] == 2
    assert chk["hard"] == 0  # well-formed fixture SRT
    assert isinstance(chk["issues"], list)


def test_quick_fix_subtitle_removes_residue(ctx, project_with_material, emit):
    """A subtitle with format-residue (batch marker) → fixable>0 → quick_fix
    strips it → re-check fixable drops."""
    _open(ctx, project_with_material)
    from materials.news_video.model import NewsVideoModel
    model = NewsVideoModel(project_with_material, "news-1")
    os.makedirs(model.subtitles_dir, exist_ok=True)
    with open(os.path.join(model.subtitles_dir, "en.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n【1】hello\n")

    before = call(ctx, "material.check_subtitle", {"type": "news_video", "instance": "news-1", "lang": "en"})["result"]
    assert before["fixable"] >= 1
    after = call(ctx, "material.quick_fix_subtitle", {"type": "news_video", "instance": "news-1", "lang": "en"})["result"]
    assert after["fixable"] == 0
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events


def test_import_subtitle(ctx, project_with_material, emit, tmp_path):
    _open(ctx, project_with_material)
    ext = tmp_path / "external.srt"
    ext.write_text("1\n00:00:01,000 --> 00:00:02,000\nbonjour\n", encoding="utf-8")
    res = call(ctx, "material.import_subtitle",
               {"type": "news_video", "instance": "news-1", "path": str(ext), "lang": "fr"})["result"]
    assert res["lang"] == "fr"
    langs = call(ctx, "material.list_subtitle_languages", {"type": "news_video", "instance": "news-1"})["result"]
    assert "fr" in langs
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events


def test_list_analysis_artifacts_and_read_text(ctx, project_with_subtitles):
    _open(ctx, project_with_subtitles)
    from materials.news_video.model import NewsVideoModel
    model = NewsVideoModel(project_with_subtitles, "news-1")
    with open(os.path.join(model.subtitles_dir, "en.transcript.md"), "w", encoding="utf-8") as f:
        f.write("# Transcript\n\nhello world\n")
    with open(os.path.join(model.subtitles_dir, "en.analysis.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "titles": [], "chapters": []}, f)

    arts = call(ctx, "material.list_analysis_artifacts", {"type": "news_video", "instance": "news-1", "lang": "en"})["result"]
    kinds = {a["kind"] for a in arts}
    assert {"transcript", "analysis"} <= kinds
    txt = call(ctx, "material.read_analysis_text",
               {"type": "news_video", "instance": "news-1", "lang": "en", "kind": "transcript"})["result"]
    assert "hello world" in txt["text"]


# ── AI fill context (M5) ─────────────────────────────────────────────────────

def test_ai_fill_context(inline_jobs, project_with_material, emit, monkeypatch):
    """AI fill job: mocked extract returns a fresh SourceContext, which is
    written to context.json (replacement). Regression-guards the no-progress_cb
    call path (extract does not accept progress_cb — the model must not forward
    it)."""
    ctx = inline_jobs
    _open(ctx, project_with_material)
    from materials.news_video import ai_fill
    from materials.news_video.schema import SourceContext

    captured = {}

    def fake_extract(source_dir, subtitles_dir=None, cancel_token=None):
        captured["called"] = True
        return SourceContext(host="AI Host", episode_topic="AI Topic")

    monkeypatch.setattr(ai_fill, "extract", fake_extract)

    call(ctx, "material.ai_fill_context", {"type": "news_video", "instance": "news-1"})
    term = _terminal(emit)
    assert term["status"] == "succeeded", term
    assert captured.get("called") is True  # the call path didn't TypeError
    assert term["result"]["host"] == "AI Host"
    # Persisted (replacement) to context.json.
    stored = call(ctx, "material.read_context", {"type": "news_video", "instance": "news-1"})["result"]
    assert stored["host"] == "AI Host"
    assert stored["episode_topic"] == "AI Topic"
    assert ("event.material.changed", {"type": "news_video", "instance": "news-1"}) in emit.events
