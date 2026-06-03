"""Capability-gateway RPC tests (ADR-0008 Phase B2).

The gateway is plugin-agnostic + path-based: tests pass absolute paths inside the
open project and monkeypatch the heavy cores (acquire / ASR / translate / analyze
/ ai.complete_json). Sync ops (subtitle_check / quick_fix / save_chapters) run the
real core over fixture files. Long jobs run inline (no daemon thread) so terminal
event.job assertions don't race — same pattern as test_material.py.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from core_rpc.dispatch import dispatch_message


def call(ctx, method: str, params: Optional[dict[str, Any]] = None, id: Any = 1):
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


def _open(ctx, project):
    assert "result" in call(ctx, "project.open", {"folder": project.folder})


def _terminal(emit):
    jobs = emit.of("event.job")
    assert jobs, "no terminal event.job emitted"
    return jobs[-1]


@pytest.fixture
def inline_jobs(ctx, monkeypatch):
    """Run jobs synchronously, mirroring JobRegistry.runner's terminal contract."""
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
        except Exception as exc:  # noqa: BLE001
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


def _subs_dir(project) -> str:
    d = os.path.join(project.folder, "materials", "news_video", "n1", "subtitles")
    os.makedirs(d, exist_ok=True)
    return d


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


_CLEAN_SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n2\n00:00:03,500 --> 00:00:05,000\nSecond line\n"


# ── Path safety ───────────────────────────────────────────────────────────────

def test_no_project_rejected(ctx):
    assert "error" in call(ctx, "capability.subtitle_check", {"srt_path": "/x/y.srt"})


def test_path_escape_rejected(ctx, tmp_project):
    _open(ctx, tmp_project)
    outside = os.path.abspath(os.path.join(tmp_project.folder, "..", "escape.srt"))
    resp = call(ctx, "capability.subtitle_check", {"srt_path": outside})
    assert "error" in resp and "escapes project" in resp["error"]["message"]


# ── Long jobs (monkeypatched cores) ──────────────────────────────────────────

def test_asr_job(inline_jobs, tmp_project, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, tmp_project)
    subs = _subs_dir(tmp_project)
    video = os.path.join(tmp_project.folder, "materials", "news_video", "n1", "source", "video.mp4")
    seen: dict[str, Any] = {}

    def fake(**kw):
        seen.update(kw)
        return {"lang_iso": "en", "srt_path": os.path.join(kw["subtitles_dir"], "en.srt"), "segment_count": 4}

    monkeypatch.setattr("core.subtitle_pipeline.run_asr_paths", fake)
    call(ctx, "capability.asr", {"source_video_path": video, "subtitles_dir": subs})
    term = _terminal(emit)
    assert term["status"] == "succeeded"
    assert term["result"]["lang_iso"] == "en" and term["result"]["segment_count"] == 4
    assert seen["source_video_path"] == video and seen["subtitles_dir"] == subs


def test_asr_normalizes_mixed_separator_paths(inline_jobs, tmp_project, emit, monkeypatch):
    """The TS layer sends Windows mixed-separator paths (instance dir from
    os.path.join + '/source/...' joined in JS); capability must normalize before
    handing them to faster-whisper/ffmpeg (ADR-0008 B3.2 ASR-stall fix)."""
    ctx = inline_jobs
    _open(ctx, tmp_project)
    base = os.path.join(tmp_project.folder, "materials", "news_video", "n1")
    seen: dict[str, Any] = {}
    monkeypatch.setattr("core.subtitle_pipeline.run_asr_paths",
                        lambda **kw: (seen.update(kw), {"lang_iso": "en", "srt_path": "x", "segment_count": 0})[1])
    # Deliberately mixed: backslash base + forward-slash tail (what the JS model emits).
    call(ctx, "capability.asr", {
        "source_video_path": f"{base}\\source/video.mp4",
        "subtitles_dir": f"{base}\\subtitles",
    })
    assert _terminal(emit)["status"] == "succeeded"
    assert seen["source_video_path"] == os.path.normpath(f"{base}\\source/video.mp4")
    assert "/" not in os.path.relpath(seen["source_video_path"], tmp_project.folder) or os.sep == "/"


def test_translate_job(inline_jobs, tmp_project, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, tmp_project)
    subs = _subs_dir(tmp_project)
    monkeypatch.setattr(
        "core.subtitle_pipeline.run_translate_paths",
        lambda **kw: {"lang_iso": kw["target_lang_iso"], "srt_path": os.path.join(kw["subtitles_dir"], "zh.srt")},
    )
    call(ctx, "capability.translate", {"subtitles_dir": subs, "source_lang": "en", "target_lang": "zh"})
    assert _terminal(emit)["result"]["lang_iso"] == "zh"
    # validation
    assert "error" in call(ctx, "capability.translate", {"subtitles_dir": subs, "source_lang": "", "target_lang": "zh"})


def test_analyze_job(inline_jobs, tmp_project, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, tmp_project)
    subs = _subs_dir(tmp_project)
    srt = os.path.join(subs, "en.srt")
    _write(srt, _CLEAN_SRT)
    monkeypatch.setattr(
        "core.subtitle_analysis_runners.run",
        lambda kind, srt_path, subtitles_dir, lang, pcb, ct, context_block="": {
            "kind": kind, "lang": lang, "ctx": context_block,
        },
    )
    # context_block is built plugin-side and threaded through capability (ADR-0008).
    call(ctx, "capability.analyze",
         {"kind": "analysis", "srt_path": srt, "subtitles_dir": subs, "lang": "en",
          "context_block": "BG"})
    assert _terminal(emit)["result"] == {"kind": "analysis", "lang": "en", "ctx": "BG"}


def test_llm_extract_job(inline_jobs, tmp_project, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, tmp_project)
    captured: dict[str, Any] = {}

    def fake_complete(prompt, *, schema, task, cancel_token=None):
        captured.update(prompt=prompt, schema=schema, task=task)
        return {"host": "James Vance", "episode_topic": "Budget"}

    monkeypatch.setattr("core.ai.complete_json", fake_complete)
    schema = {"type": "object", "properties": {"host": {"type": "string"}}}
    call(ctx, "capability.llm_extract", {"prompt": "extract X", "schema": schema, "task": "news.realtime"})
    term = _terminal(emit)
    assert term["result"]["host"] == "James Vance"
    assert captured["task"] == "news.realtime" and captured["schema"] == schema
    # validation: empty prompt / non-dict schema rejected at the RPC boundary
    assert "error" in call(ctx, "capability.llm_extract", {"prompt": "", "schema": schema, "task": "t"})


def test_acquire_source_job(inline_jobs, tmp_project, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, tmp_project)
    video = os.path.join(tmp_project.folder, "materials", "news_video", "n1", "source", "video.mp4")
    meta = os.path.join(tmp_project.folder, "materials", "news_video", "n1", "source", "meta.json")

    monkeypatch.setattr(
        "core.source_acquire.acquire",
        lambda src, vp, mp, **kw: SimpleNamespace(title="Clip", duration_sec=12.5, width=1920, height=1080),
    )
    call(ctx, "capability.acquire_source",
         {"source": {"origin": "local", "imported_from": "/tmp/a.mp4"}, "video_path": video, "meta_path": meta})
    term = _terminal(emit)
    assert term["status"] == "succeeded"
    assert term["result"] == {"title": "Clip", "duration_sec": 12.5, "width": 1920, "height": 1080}


def test_acquire_source_failure_prefixes_category(inline_jobs, tmp_project, emit, monkeypatch):
    ctx = inline_jobs
    _open(ctx, tmp_project)
    video = os.path.join(tmp_project.folder, "materials", "news_video", "n1", "source", "video.mp4")
    from core import source_acquire

    def boom(src, vp, mp, **kw):
        raise source_acquire.AcquireError(source_acquire.ERR_URL_INVALID, "坏链接", "bad url")

    monkeypatch.setattr("core.source_acquire.acquire", boom)
    call(ctx, "capability.acquire_source",
         {"source": {"origin": "link", "url": "http://x"}, "video_path": video})
    term = _terminal(emit)
    assert term["status"] == "failed"
    assert term["error"].startswith(f"{source_acquire.ERR_URL_INVALID}:")


# ── Sync ops (real cores over fixtures) ──────────────────────────────────────

def test_subtitle_check_clean(ctx, tmp_project):
    _open(ctx, tmp_project)
    srt = os.path.join(_subs_dir(tmp_project), "en.srt")
    _write(srt, _CLEAN_SRT)
    res = call(ctx, "capability.subtitle_check", {"srt_path": srt, "expected_lang": "en"})["result"]
    assert res["cue_count"] == 2
    assert {"cue_count", "hard", "fixable", "advisory", "issues"} <= set(res)


def test_subtitle_quick_fix(ctx, tmp_project):
    _open(ctx, tmp_project)
    srt = os.path.join(_subs_dir(tmp_project), "en.srt")
    # Trailing-space / format residue the auto-fixer cleans; re-check returns counts.
    _write(srt, "1\n00:00:01,000 --> 00:00:03,000\nHello   \n")
    res = call(ctx, "capability.subtitle_quick_fix", {"srt_path": srt, "expected_lang": "en"})["result"]
    assert "cue_count" in res and isinstance(res["issues"], list)


def test_save_chapters_normalizes(ctx, tmp_project):
    _open(ctx, tmp_project)
    subs = _subs_dir(tmp_project)
    srt = os.path.join(subs, "en.srt")
    _write(srt, _CLEAN_SRT)
    analysis = os.path.join(subs, "en.analysis.json")
    # Out-of-order, no 00:00 start → server sorts + synthesizes the intro chapter.
    chapters = [{"start": "00:30", "title": "B"}, {"start": "00:10", "title": "A"}]
    env = call(ctx, "capability.save_chapters",
               {"analysis_path": analysis, "chapters": chapters, "srt_path": srt, "lang": "en"})["result"]
    assert isinstance(env.get("chapters"), list) and env["chapters"]
    assert os.path.isfile(analysis)
    saved = json.loads(open(analysis, encoding="utf-8").read())
    assert saved["chapters"][0].get("start") in ("00:00", "00:00:00", 0, "0")
