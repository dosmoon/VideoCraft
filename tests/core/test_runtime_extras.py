"""core.runtime_extras — the py-extra install seam (P3 §5.3).

No real pip runs: pip_command is asserted by shape, install/uninstall are driven
against a fake py-extra populated by hand (dist-info + RECORD), mirroring what
pip --target writes.
"""

from __future__ import annotations

import os

import pytest

from core import runtime_extras as rx


@pytest.fixture(autouse=True)
def _isolated_user_data(tmp_path, monkeypatch):
    """Point py-extra at a tmp dir and reset the one-shot sys.path latch."""
    monkeypatch.setenv("VC_USER_DATA", str(tmp_path / "user_data"))
    monkeypatch.setattr(rx, "_ON_PATH", False)
    yield


def test_pip_command_dev_vs_frozen(monkeypatch):
    monkeypatch.setattr("sys.frozen", False, raising=False)
    monkeypatch.setattr("sys.executable", "C:/venv/python.exe", raising=False)
    assert rx.pip_command(["install", "x"]) == [
        "C:/venv/python.exe", "-m", "pip", "install", "x",
    ]

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", "C:/app/core_rpc.exe", raising=False)
    # Frozen: self-spawn with the --vc-pip sentinel the entry wrapper dispatches.
    assert rx.pip_command(["install", "x"]) == [
        "C:/app/core_rpc.exe", "--vc-pip", "install", "x",
    ]


def test_py_extra_dir_under_user_data(tmp_path):
    d = rx.py_extra_dir()
    assert os.path.isdir(d)
    assert d.replace("\\", "/").endswith("user_data/runtimes/py-extra")


def test_ensure_on_sys_path_idempotent(monkeypatch):
    import sys

    before = list(sys.path)
    rx.ensure_on_sys_path()
    d = rx.py_extra_dir()
    assert sys.path[0] == d
    # Second call is a no-op — no duplicate entry.
    rx.ensure_on_sys_path()
    assert sys.path.count(d) == 1
    monkeypatch.setattr("sys.path", before)


def test_install_builds_target_command(monkeypatch):
    captured = {}

    def fake_stream(cmd, on_line, cancel_token):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(rx, "_stream", fake_stream)
    monkeypatch.setattr("sys.frozen", False, raising=False)
    rc = rx.install(["faster-whisper==1.2.1"], extra_args=["--extra-index-url", "u"])
    assert rc == 0
    cmd = captured["cmd"]
    assert "--target" in cmd and rx.py_extra_dir() in cmd
    assert "--only-binary" in cmd and ":all:" in cmd
    assert "--extra-index-url" in cmd and "u" in cmd
    assert cmd[-1] == "faster-whisper==1.2.1"


def _make_dist(target: str, project: str, version: str, files: list[str]) -> None:
    """Write a fake --target install: the package files + a dist-info/RECORD."""
    for rel in files:
        p = os.path.join(target, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")
    info = os.path.join(target, f"{project.replace('-', '_')}-{version}.dist-info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "RECORD"), "w", encoding="utf-8") as f:
        for rel in files:
            f.write(f"{rel},,\n")


def test_is_installed_checks_py_extra_dist_info():
    target = rx.py_extra_dir()
    assert rx.is_installed(["nvidia-cublas-cu12"]) is False
    _make_dist(target, "nvidia-cublas-cu12", "12.0.0", ["nvidia/cublas/bin/x.dll"])
    # Name normalization: dotted/dashed forms map to the same dist-info stem.
    assert rx.is_installed(["nvidia-cublas-cu12"]) is True
    assert rx.is_installed(["nvidia_cublas_cu12"]) is True
    assert rx.is_installed(["nvidia-cublas-cu12", "missing-pkg"]) is False


def test_uninstall_removes_recorded_files():
    target = rx.py_extra_dir()
    _make_dist(target, "faster-whisper", "1.2.1",
               ["faster_whisper/__init__.py", "faster_whisper/audio.py"])
    assert rx.is_installed(["faster-whisper"]) is True

    rx.uninstall(["faster-whisper"])

    assert rx.is_installed(["faster-whisper"]) is False
    assert not os.path.exists(os.path.join(target, "faster_whisper", "__init__.py"))
    # The now-empty package dir is pruned too.
    assert not os.path.isdir(os.path.join(target, "faster_whisper"))
