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


def test_parse_version_token_strips_node_v_prefix():
    # `node --version` prints "v22.11.0"; display should drop the leading 'v'
    # so it matches the ffmpeg/ffprobe/claude detectors (which all parse).
    assert detectors._parse_version_token("v22.11.0") == "22.11.0"


def test_parse_version_token_ffmpeg_style():
    # ffmpeg prints "ffmpeg version 7.1.1-full_build ..." → token after 'version'.
    assert detectors._parse_version_token("ffmpeg version 7.1.1-full_build copyright") == "7.1.1-full_build"
