"""creations/clip/candidates.py — HotclipsRepo data layer."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from creations.clip.candidates import HotclipsRepo


@dataclass
class _FakeModel:
    """Minimal NewsVideoModel stand-in for repo tests — only the field
    HotclipsRepo touches (subtitles_dir)."""
    subtitles_dir: str


def _make_repo(tmp_path):
    upstream = tmp_path / "upstream_subs"
    upstream.mkdir()
    instance = tmp_path / "instance"
    instance.mkdir()
    repo = HotclipsRepo(str(instance), _FakeModel(subtitles_dir=str(upstream)))
    return repo, upstream, instance


# ── path helpers ────────────────────────────────────────────────────────────

def test_hotclips_snapshot_path(tmp_path):
    repo, _, instance = _make_repo(tmp_path)
    assert repo.hotclips_snapshot_path("en") == os.path.join(
        str(instance), "source-hotclips.en.json")


def test_srt_snapshot_path(tmp_path):
    repo, _, instance = _make_repo(tmp_path)
    assert repo.srt_snapshot_path("zh") == os.path.join(
        str(instance), "source-subtitles.zh.srt")


# ── ensure_snapshot ─────────────────────────────────────────────────────────

def test_ensure_snapshot_missing_upstream_returns_none(tmp_path):
    repo, _, _ = _make_repo(tmp_path)
    assert repo.ensure_snapshot("en") is None


def test_ensure_snapshot_copies_hotclips_first_time(tmp_path):
    repo, upstream, instance = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text(
        json.dumps({"clips": [{"start": "00:00", "end": "00:10"}]}),
        encoding="utf-8")
    path = repo.ensure_snapshot("en")
    assert path is not None
    assert os.path.isfile(path)
    snap_data = json.loads(open(path, encoding="utf-8").read())
    assert snap_data["clips"][0]["start"] == "00:00"


def test_ensure_snapshot_copies_srt_best_effort(tmp_path):
    repo, upstream, _ = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text(
        json.dumps({"clips": []}), encoding="utf-8")
    (upstream / "en.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    repo.ensure_snapshot("en")
    assert os.path.isfile(repo.srt_snapshot_path("en"))


def test_ensure_snapshot_idempotent_does_not_clobber(tmp_path):
    repo, upstream, _ = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text(
        json.dumps({"clips": [{"id": "v1"}]}), encoding="utf-8")
    repo.ensure_snapshot("en")
    # Mutate upstream — should NOT reflect in second call (snapshot wins)
    (upstream / "en.hotclips.json").write_text(
        json.dumps({"clips": [{"id": "v2"}]}), encoding="utf-8")
    path = repo.ensure_snapshot("en")
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["clips"][0]["id"] == "v1", (
        "snapshot was clobbered by second ensure call")


def test_ensure_snapshot_survives_upstream_deletion(tmp_path):
    repo, upstream, _ = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text(
        json.dumps({"clips": []}), encoding="utf-8")
    repo.ensure_snapshot("en")
    (upstream / "en.hotclips.json").unlink()
    # Should still resolve via the existing snapshot
    assert repo.ensure_snapshot("en") is not None


# ── list_available_langs ────────────────────────────────────────────────────

def test_list_available_langs_unions_upstream_and_snapshots(tmp_path):
    repo, upstream, instance = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text("{}", encoding="utf-8")
    (upstream / "zh.hotclips.json").write_text("{}", encoding="utf-8")
    (instance / "source-hotclips.ja.json").write_text("{}", encoding="utf-8")
    assert repo.list_available_langs() == ["en", "ja", "zh"]


def test_list_available_langs_handles_missing_dirs(tmp_path):
    repo = HotclipsRepo(
        str(tmp_path / "nope"), _FakeModel(subtitles_dir=str(tmp_path / "nada")))
    assert repo.list_available_langs() == []


# ── load_hotclips ───────────────────────────────────────────────────────────

def test_load_hotclips_returns_parsed_dict(tmp_path):
    repo, upstream, _ = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text(
        json.dumps({"clips": [{"k": "v"}]}), encoding="utf-8")
    data = repo.load_hotclips("en")
    assert data == {"clips": [{"k": "v"}]}


def test_load_hotclips_returns_none_on_missing(tmp_path):
    repo, _, _ = _make_repo(tmp_path)
    assert repo.load_hotclips("en") is None


def test_load_hotclips_returns_none_on_malformed_json(tmp_path):
    repo, upstream, _ = _make_repo(tmp_path)
    (upstream / "en.hotclips.json").write_text("{ not json", encoding="utf-8")
    assert repo.load_hotclips("en") is None


# ── resolve_source_srt ──────────────────────────────────────────────────────

def test_resolve_source_srt_prefers_snapshot(tmp_path):
    repo, upstream, instance = _make_repo(tmp_path)
    (upstream / "en.srt").write_text("upstream", encoding="utf-8")
    (instance / "source-subtitles.en.srt").write_text(
        "snapshot", encoding="utf-8")
    resolved = repo.resolve_source_srt("en")
    assert resolved == str(instance / "source-subtitles.en.srt")
    assert open(resolved, encoding="utf-8").read() == "snapshot"


def test_resolve_source_srt_falls_back_to_upstream(tmp_path):
    repo, upstream, _ = _make_repo(tmp_path)
    (upstream / "en.srt").write_text("upstream", encoding="utf-8")
    resolved = repo.resolve_source_srt("en")
    assert resolved == str(upstream / "en.srt")


def test_resolve_source_srt_empty_lang_returns_none(tmp_path):
    repo, _, _ = _make_repo(tmp_path)
    assert repo.resolve_source_srt("") is None


def test_resolve_source_srt_missing_everywhere_returns_none(tmp_path):
    repo, _, _ = _make_repo(tmp_path)
    assert repo.resolve_source_srt("en") is None
