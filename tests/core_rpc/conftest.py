"""Fixtures for the core_rpc sidecar tests.

These tests drive the transport-free dispatch core (dispatch_message) with
plain dicts and assert on the dicts/notifications it produces — the headless
equivalent of talking to the sidecar over stdio, minus the pipe.
"""

from __future__ import annotations

from typing import Any

import pytest

from core_rpc.jobs import JobRegistry
from core_rpc.registry import Context
from core_rpc.session import Session

# Importing the methods package registers every handler (system/project/material).
import core_rpc.methods  # noqa: F401,E402


@pytest.fixture(autouse=True)
def _isolate_user_data(tmp_path, monkeypatch):
    """Redirect <repo>/user_data → a tmp dir so project.open's recent-list
    write (add_recent_project) never pollutes the real user_data/recent.json."""
    data_dir = tmp_path / "user_data"
    data_dir.mkdir()
    monkeypatch.setattr("core.user_data.user_data_dir", lambda: str(data_dir))
    yield


class EmitCollector:
    """Captures server→client notifications as (method, params) tuples."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def __call__(self, method: str, params: Any) -> None:
        self.events.append((method, params))

    def methods(self) -> list[str]:
        return [m for m, _ in self.events]

    def of(self, method: str) -> list[Any]:
        return [p for m, p in self.events if m == method]


@pytest.fixture
def emit() -> EmitCollector:
    return EmitCollector()


@pytest.fixture
def ctx(emit) -> Context:
    """A fresh Context: empty Session, collecting emit, real JobRegistry."""
    session = Session()
    jobs = JobRegistry(emit)
    return Context(session=session, emit=emit, jobs=jobs)
