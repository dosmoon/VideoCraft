"""Shared test fixtures.

`tmp_project` builds a fresh Project under a pytest tmp_path so tests
get an isolated filesystem with `.videocraft/`, `materials/`, and
`creations/` skeleton dirs. Tests can then call
`project.create_material_instance(...)` to populate as needed.
"""

from __future__ import annotations

import pytest
from project import Project


@pytest.fixture
def tmp_project(tmp_path):
    """A clean Project rooted under pytest's tmp_path."""
    p = Project.new(str(tmp_path), "test_project")
    return p
