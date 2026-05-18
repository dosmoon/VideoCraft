"""Hotclips data layer for the clip workbench.

Pure IO — no Tk, no widget state. The repo owns the per-instance
snapshot of upstream hotclips + SRT (per the snapshot principle, see
[[project_snapshot_principle]]) and exposes the read APIs the
workbench needs:

  - list_available_langs()       : which languages can the user pick
  - ensure_snapshot(lang)        : copy upstream → instance dir on first
                                    access, return the hotclips snapshot
                                    path (None when upstream is missing)
  - load_hotclips(lang)          : parsed JSON dict for that language
  - resolve_source_srt(lang)     : the snapshot SRT path, falling back
                                    to upstream when no snapshot yet

The workbench keeps Tk orchestration (the list widget, the language
combo, candidate-row rendering); this module only handles the
filesystem side and can be unit-tested in isolation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Optional


_SNAPSHOT_RE = re.compile(r"^source-hotclips\.([^.]+)\.json$")


class HotclipsRepo:
    """Per-instance hotclips + SRT snapshot repository.

    Construct with the instance directory and the bound NewsVideoModel.
    All upstream access funnels through the model (see
    [[feedback_material_via_model_only]])."""

    def __init__(self, instance_dir: str, material_model) -> None:
        self._instance_dir = instance_dir
        self._model = material_model

    # ── snapshot paths ────────────────────────────────────────────────────

    def hotclips_snapshot_path(self, lang: str) -> str:
        return os.path.join(
            self._instance_dir, f"source-hotclips.{lang}.json")

    def srt_snapshot_path(self, lang: str) -> str:
        return os.path.join(
            self._instance_dir, f"source-subtitles.{lang}.srt")

    # ── snapshot copy-on-first-access ─────────────────────────────────────

    def ensure_snapshot(self, lang: str) -> Optional[str]:
        """Snapshot upstream hotclips + SRT into the instance dir if not
        yet present. Returns the hotclips snapshot path, or None if
        upstream hotclips is missing AND no prior snapshot exists.

        SRT snapshot is best-effort: missing upstream SRT is fine
        (subtitles are optional for burn). Once snapshotted, the
        instance reads ONLY from the snapshot — upstream regeneration
        cannot corrupt this instance's renders.
        """
        os.makedirs(self._instance_dir, exist_ok=True)

        hot_snap = self.hotclips_snapshot_path(lang)
        if not os.path.isfile(hot_snap):
            upstream = os.path.join(
                self._model.subtitles_dir, f"{lang}.hotclips.json")
            if not os.path.isfile(upstream):
                return None
            try:
                shutil.copy2(upstream, hot_snap)
            except OSError:
                return None

        srt_snap = self.srt_snapshot_path(lang)
        if not os.path.isfile(srt_snap):
            upstream_srt = os.path.join(
                self._model.subtitles_dir, f"{lang}.srt")
            if os.path.isfile(upstream_srt):
                try:
                    shutil.copy2(upstream_srt, srt_snap)
                except OSError:
                    pass
        return hot_snap

    # ── reads ─────────────────────────────────────────────────────────────

    def list_available_langs(self) -> list[str]:
        """Languages with hotclips available — union of instance
        snapshots and upstream subtitles. Snapshotted langs are listed
        even when upstream was deleted; not-yet-snapshotted upstream
        langs are listed and snapshotted on first selection."""
        langs: set[str] = set()
        try:
            for name in os.listdir(self._instance_dir):
                m = _SNAPSHOT_RE.match(name)
                if m:
                    langs.add(m.group(1))
        except OSError:
            pass
        try:
            for name in os.listdir(self._model.subtitles_dir):
                if name.endswith(".hotclips.json"):
                    langs.add(name[:-len(".hotclips.json")])
        except OSError:
            pass
        return sorted(langs)

    def list_subtitle_langs(self) -> list[str]:
        """Languages with an SRT available — union of instance SRT
        snapshots and upstream `.srt` files in subtitles_dir. Broader
        than list_available_langs(): no hotclips JSON required, so any
        SRT the material has can be picked as a subtitle burn source."""
        langs: set[str] = set()
        try:
            for name in os.listdir(self._instance_dir):
                if (name.startswith("source-subtitles.")
                        and name.endswith(".srt")):
                    langs.add(name[len("source-subtitles."):-len(".srt")])
        except OSError:
            pass
        try:
            for name in os.listdir(self._model.subtitles_dir):
                if name.endswith(".srt"):
                    langs.add(name[:-len(".srt")])
        except OSError:
            pass
        return sorted(langs)

    def load_hotclips(self, lang: str) -> Optional[dict]:
        """Parse the snapshot hotclips JSON. Returns the dict or None
        when the snapshot is missing or malformed (caller decides how
        to surface that to the user)."""
        path = self.ensure_snapshot(lang)
        if path is None:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def resolve_source_srt(self, lang: str) -> Optional[str]:
        """Return the instance's SRT snapshot path. Falls back to
        upstream only when the snapshot hasn't been taken yet (legacy
        instances from before the snapshot principle); that case should
        be rare because ensure_snapshot fires on every language load."""
        if not lang:
            return None
        snap = self.srt_snapshot_path(lang)
        if os.path.isfile(snap):
            return snap
        upstream = os.path.join(self._model.subtitles_dir, f"{lang}.srt")
        return upstream if os.path.isfile(upstream) else None
