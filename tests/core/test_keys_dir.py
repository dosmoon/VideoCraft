"""Regression: the models-dir override READER (core.paths) and WRITER
(core.ai.config) must resolve providers.json through the SAME keys dir.

They once drifted in frozen builds — the writer moved to ``user_data/keys`` while
the reader kept an ``__file__``-relative copy pointing at the sealed
``resources/keys`` — so a packaged "change models dir" wrote the override but
``models_dir()`` never read it back ("更改本地模型路径无效"). core.user_data.keys_dir
is now the single source for both.
"""

import json
import os
import sys


def test_frozen_reader_and_writer_share_one_keys_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("VC_USER_DATA", str(tmp_path))

    import core.paths as paths
    import core.user_data as ud
    from core.ai import config

    keys = ud.keys_dir()
    # Frozen → beside the exe (VC_USER_DATA), NOT a __file__-relative guess.
    assert keys == os.path.join(str(tmp_path), "keys")
    # Reader and writer both resolve through the same function.
    assert config.keys_dir() == keys
    assert paths._providers_json_path() == os.path.join(keys, "providers.json")

    # An override written to the writer's path must be visible to the reader.
    os.makedirs(keys, exist_ok=True)
    target = str(tmp_path / "external-models")
    with open(os.path.join(keys, "providers.json"), "w", encoding="utf-8") as f:
        json.dump({"models_dir": target}, f)
    assert paths.models_dir() == target


def test_dev_keys_dir_is_repo_top_level_keys(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("VC_USER_DATA", raising=False)

    import core.user_data as ud

    here = os.path.dirname(os.path.abspath(ud.__file__))
    # src/core -> src -> <repo root>/keys (NOT under user_data, by design).
    expected = os.path.normpath(os.path.join(here, "..", "..", "keys"))
    assert ud.keys_dir() == expected
