"""AI extraction of SourceContext from a project's source URL + metadata.

Calls task `news.realtime` (cloud LLM with web-search grounding —
xAI Grok by default) to fill the 10 AI-owned fields of context.json.
The 5 anchor fields in basic_info.json are passed in as authoritative
seed: their values MUST be reflected in the AI's reasoning (so it
matches the model's understanding to the user-known truth) but are
never written back here — basic_info.json stays manual-only.
"""

from __future__ import annotations

import json

from core import ai, prompts
from materials.news_video.schema import (
    SourceBasicInfo, SourceContext,
    read_basic_info, read_context, read_platform_metadata,
)


_FIELDS = (
    # Anchor fields (AI-verified canonical version of user's basic_info)
    "host", "host_bio", "event_date", "event_location", "episode_topic",
    # AI-derived extras
    "host_affiliation", "guests",
    "event_time",
    "show_type", "event_summary", "key_points",
    "background",
    "audience", "platform_tone", "notes",
)

_SCHEMA = {
    "type": "object",
    "properties": {f: {"type": "string"} for f in _FIELDS},
    "required": list(_FIELDS),
    "additionalProperties": False,
}


def extract(source_dir: str,
            subtitles_dir: str | None = None,
            cancel_token=None) -> SourceContext:
    """Run the realtime-news AI task and return a fresh SourceContext
    (15 fields: 5 verified anchors + 10 derived). Caller writes the
    result to context.json.

    basic_info.json is read as a HINT — possibly misspelled / incomplete /
    out-of-date. AI must verify each anchor field via web search and
    emit the canonical version (e.g. user types "Vance" → AI emits
    "James David Vance"). basic_info.json itself is NOT modified.

    Replacement semantics (not merge): the returned SourceContext is
    the AI's fresh output. Any prior context.json content is discarded
    so the user can recover from a bad earlier run by clicking again.

    Raises core.ai.AIError when no provider is configured for
    task=news.realtime or the API call fails.
    """
    del subtitles_dir  # accepted for API stability; subtitles unused
    basic = read_basic_info(source_dir)
    platform = read_platform_metadata(source_dir)

    tags = platform.get("tags") or []
    tags_str = ", ".join(str(t) for t in tags[:20]) if isinstance(tags, list) else ""

    url = (platform.get("webpage_url")
           or platform.get("original_url")
           or platform.get("url") or "").strip()

    # Seed: basic_info anchors as user-provided HINTS. AI verifies them
    # via web search and emits the corrected canonical version in its
    # output. Past context.json content intentionally NOT fed back in.
    template = prompts.get("news.source_context")
    filled = template.format(
        url=url or "—",
        uploader=(platform.get("uploader") or "").strip() or "—",
        description=(platform.get("description") or "").strip() or "—",
        tags=tags_str or "—",
        existing_filled=json.dumps(basic.to_dict(), ensure_ascii=False, indent=2),
    )

    raw = ai.complete_json(
        filled, schema=_SCHEMA, task="news.realtime",
        cancel_token=cancel_token,
    )
    return SourceContext.from_dict(raw if isinstance(raw, dict) else {})
