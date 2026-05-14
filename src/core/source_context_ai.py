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
from core.source_context import (
    SourceBasicInfo, SourceContext,
    read_basic_info, read_context, read_platform_metadata,
)


_FIELDS = (
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
    (10 AI-owned fields). Caller is expected to write_context() the result.

    basic_info.json is read but NOT modified — its 5 anchor fields are
    fed into the prompt as authoritative seed; AI must respect them.

    Replacement semantics (not merge): the returned SourceContext is
    the AI's fresh output. Any prior context.json content is discarded.
    Manual user tweaks belong in basic_info.json (preserved by design)
    or should be redone after AI Fill via the manual-edit dialog.

    Rationale: a previous merge-preserve rule caused a wedged state
    where bad content (e.g. from a failed-fallback DeepSeek hallucination)
    was kept across subsequent AI Fill attempts, so the user could not
    recover by clicking AI Fill again. Replace semantics make the
    button do what its label says: fill the archive afresh.

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

    # Seed: only basic_info anchor fields. These are the user's
    # ground-truth knowledge; the AI must reflect them and not contradict.
    # Past context.json content is intentionally NOT fed back in.
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
