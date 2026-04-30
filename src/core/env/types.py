"""Data classes for the environment component registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DetectResult:
    available: bool
    version: Optional[str] = None    # e.g. "7.1" or "v22.11.0"
    source: Optional[str] = None     # 'system' | 'managed' | 'pip' | None
    path: Optional[str] = None       # absolute path to binary, or None


# install signature: takes an on_log callback (str -> None), returns None,
# raises on failure. None means the component is not auto-installable.
InstallFn = Callable[[Callable[[str], None]], None]


@dataclass
class EnvComponent:
    id: str                          # 'ffmpeg' / 'node' / 'yt-dlp'
    label_key: str                   # i18n key for display name
    category: str                    # 'binary' | 'python'
    detect: Callable[[], DetectResult]
    install: Optional[InstallFn] = None
    info_url: Optional[str] = None   # download/install guide URL
    visible: bool = True             # hide from UI but keep detectable
