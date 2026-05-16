"""News-video material sidebar — the structured tree this material type
exposes inside the 素材 tab.

Per ADR-0004, a material plugin owns its sidebar rendering. This module
defines `NewsVideoSidebar`, the panel that paints the news_video
material's slots (source video / news context / subtitles / ...).

Slice K.1 (this commit) lands the architectural seam: the class takes
a hub reference and currently delegates section construction back to
hub's existing builder methods. The plugin owns the lifecycle entry
(MaterialType.sidebar_renderer points here), so the contract is
honest from the outside.

Slice K.2 follow-up: cut the section builder / refresh / handler
bodies out of VideoCraftHub.py and into this class — pure refactor,
no behavior change.
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from VideoCraftHub import VideoCraftHub


class NewsVideoSidebar:
    """One news_video material's panel inside the 素材 tab.

    Owns: section frames + their refresh state. Currently delegates
    construction to hub methods (slice K.1); slice K.2 moves the
    bodies here.
    """

    def __init__(self, parent: tk.Frame, hub: "VideoCraftHub") -> None:
        self.hub = hub
        self.parent = parent
        # Delegate to existing Hub builder. Slice K.2 inlines the bodies.
        self.hub._build_materials_tab_legacy(parent)

    def refresh(self) -> None:
        """Refresh all sections. Delegates to hub for now."""
        self.hub._refresh_materials_tab_legacy()


def render(parent: tk.Frame, hub: "VideoCraftHub") -> NewsVideoSidebar:
    """MaterialType.sidebar_renderer entry point.

    Builds the news_video panel under `parent` and returns it so the
    hub can hold a reference for refresh dispatch.
    """
    return NewsVideoSidebar(parent, hub)
