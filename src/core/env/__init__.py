"""Environment component registry.

Public API for the Settings "Environment Health" dashboard. Each external
dependency (binaries, Python packages, runtimes) is modeled as an
EnvComponent and registered in components.py. UI code calls list_components()
to enumerate, detect_one(id) to refresh status, install_one(id, on_log) to
trigger an install/upgrade.
"""

from core.env.types import DetectResult, EnvComponent
from core.env.components import (
    list_components,
    detect_one,
    install_one,
)

__all__ = [
    "DetectResult",
    "EnvComponent",
    "list_components",
    "detect_one",
    "install_one",
]
