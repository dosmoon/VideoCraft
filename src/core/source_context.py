"""DEPRECATED location — schema moved to materials/news_video/schema.py.

This thin re-export shim exists so consumers that have not yet been
migrated keep working:

  - core/subtitle_analysis_runners.py — base SRT analysis injects the
    news context as a prompt prefix; cleanest fix is to parameterize
    the runner so callers (who know the material type) inject the
    block. Tracked as ADR-0004 known wart.
  - src/ui/source_*_dialog.py + news_context_pane.py + source_preview_pane.py
    — these UI files migrate to materials/news_video/ui/ in slice G;
    their import paths flip there.

This shim is the only place where core/ imports from materials/ — a
deliberate, documented exception. Delete this file after slice G
plus the runner parameterization (or a 2nd material type making the
abstraction concrete).
"""

from __future__ import annotations

from materials.news_video.schema import (  # noqa: F401
    SOURCE_BASIC_INFO_FILENAME,
    SOURCE_CONTEXT_FILENAME,
    SourceBasicInfo,
    SourceContext,
    basic_info_path,
    context_path,
    read_basic_info,
    write_basic_info,
    read_context,
    write_context,
    read_platform_metadata,
    combined_dict,
    combined_prompt_block,
)
