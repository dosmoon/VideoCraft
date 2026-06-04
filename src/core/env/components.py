"""Global registry of environment components."""

from __future__ import annotations

from typing import Callable

from core.env.types import DetectResult, EnvComponent
from core.env import detectors as _d
from core.env.pip_installer import install_pip, upgrade_pip
from core.env.node_manager import install_managed_node


# Registry. Insertion order is the display order in the Settings UI.
_COMPONENTS: list[EnvComponent] = [
    # ── Binaries ────────────────────────────────────────────
    EnvComponent(
        id="ffmpeg", label_key="env.label.ffmpeg", category="binary",
        detect=_d.detect_ffmpeg, install=None,
        info_url="https://www.gyan.dev/ffmpeg/builds/",
    ),
    EnvComponent(
        id="ffprobe", label_key="env.label.ffprobe", category="binary",
        detect=_d.detect_ffprobe, install=None,
        info_url="https://www.gyan.dev/ffmpeg/builds/",
    ),
    EnvComponent(
        id="node", label_key="env.label.node", category="binary",
        detect=_d.detect_node, install=install_managed_node,
        info_url="https://nodejs.org/",
    ),
    EnvComponent(
        id="vlc", label_key="env.label.vlc", category="binary",
        detect=_d.detect_vlc, install=None,
        info_url="https://www.videolan.org/vlc/",
    ),
    EnvComponent(
        id="claude_cli", label_key="env.label.claude_cli", category="binary",
        detect=_d.detect_claude_cli, install=None,
        info_url="https://docs.claude.com/en/docs/claude-code/overview",
    ),

    # ── Python packages ─────────────────────────────────────
    EnvComponent(
        id="yt-dlp", label_key="env.label.ytdlp", category="python",
        detect=_d.detect_pip("yt-dlp", "yt_dlp"), install=upgrade_pip("yt-dlp"),
    ),
    EnvComponent(
        id="fish-audio-sdk", label_key="env.label.fish_sdk", category="python",
        detect=_d.detect_pip("fish-audio-sdk", "fish_audio_sdk"), install=install_pip("fish-audio-sdk"),
    ),
    EnvComponent(
        id="openai", label_key="env.label.openai_sdk", category="python",
        detect=_d.detect_pip("openai", "openai"), install=upgrade_pip("openai"),
    ),
    EnvComponent(
        id="Pillow", label_key="env.label.pillow", category="python",
        detect=_d.detect_pip("Pillow", "PIL"), install=upgrade_pip("Pillow"),
    ),
    # google-genai is a hidden detection — used by AI Console internally,
    # not surfaced as a top-level "tool" the user manages.
    EnvComponent(
        id="google-genai", label_key="env.label.google_genai", category="python",
        detect=_d.detect_pip("google-genai", "google.genai"), install=upgrade_pip("google-genai"),
        visible=False,
    ),
]


_BY_ID = {c.id: c for c in _COMPONENTS}


def list_components(visible_only: bool = True) -> list[EnvComponent]:
    """Return registered components. By default hides the ones with visible=False."""
    if visible_only:
        return [c for c in _COMPONENTS if c.visible]
    return list(_COMPONENTS)


def detect_one(component_id: str) -> DetectResult:
    """Detect a single component by id. Raises KeyError on unknown id."""
    return _BY_ID[component_id].detect()


def install_one(component_id: str, on_log: Callable[[str], None]) -> None:
    """Install / upgrade a single component. Raises KeyError on unknown id,
    NotImplementedError if the component has no installer."""
    comp = _BY_ID[component_id]
    if comp.install is None:
        raise NotImplementedError(f"Component {component_id!r} is not auto-installable")
    comp.install(on_log)
