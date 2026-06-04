"""Tests for env binary-source labelling (bundled vs system)."""

from core.env import detectors


def test_bin_source_bundled_when_under_vc_bundled_bin(tmp_path, monkeypatch):
    res = tmp_path / "resources"
    res.mkdir()
    ffmpeg = res / "ffmpeg.exe"
    ffmpeg.write_text("x")
    monkeypatch.setenv("VC_BUNDLED_BIN", str(res))
    assert detectors._bin_source(str(ffmpeg)) == "bundled"


def test_bin_source_system_when_outside(tmp_path, monkeypatch):
    res = tmp_path / "resources"
    res.mkdir()
    monkeypatch.setenv("VC_BUNDLED_BIN", str(res))
    outside = tmp_path / "elsewhere" / "ffmpeg.exe"
    outside.parent.mkdir()
    outside.write_text("x")
    assert detectors._bin_source(str(outside)) == "system"


def test_bin_source_system_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("VC_BUNDLED_BIN", raising=False)
    assert detectors._bin_source(str(tmp_path / "ffmpeg.exe")) == "system"
