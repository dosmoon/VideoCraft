"""Unit tests for src/core/io_utils.py."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from core.io_utils import atomic_write_json, atomic_write_text


def test_atomic_write_text_creates_file(tmp_path):
    path = tmp_path / "test.txt"
    atomic_write_text(str(path), "hello world")
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "hello world"


def test_atomic_write_text_creates_missing_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "test.txt"
    atomic_write_text(str(path), "nested content")
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "nested content"


def test_atomic_write_json_serializes_and_writes(tmp_path):
    path = tmp_path / "test.json"
    data = {"hello": "world", "number": 42}
    atomic_write_json(str(path), data)
    assert path.is_file()
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_atomic_write_text_permission_error_retry(tmp_path):
    """Verify that PermissionError on os.replace triggers retries,
    and succeeds if the lock is eventually released."""
    path = tmp_path / "test.txt"

    original_replace = os.replace
    call_count = 0

    def mock_replace(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise PermissionError("Mocked file lock error")
        return original_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        with patch("time.sleep") as mock_sleep:
            atomic_write_text(str(path), "retry text")
            # Verify it succeeded on the 3rd attempt
            assert call_count == 3
            # Verify it slept exactly 2 times (0.05 seconds each time)
            assert mock_sleep.call_count == 2
            mock_sleep.assert_called_with(0.05)

    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "retry text"


def test_atomic_write_text_permission_error_raises_after_10_attempts(tmp_path):
    """Verify that if the lock is never released, atomic_write_text eventually raises
    the PermissionError after 10 attempts."""
    path = tmp_path / "test.txt"

    def mock_replace_always_fail(src, dst):
        raise PermissionError("Mocked permanent lock error")

    with patch("os.replace", side_effect=mock_replace_always_fail):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(PermissionError):
                atomic_write_text(str(path), "failing text")
            assert mock_sleep.call_count == 9
