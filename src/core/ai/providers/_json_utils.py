"""Shared JSON parsing helpers used by provider adapters.

Handles markdown fences around JSON that some models add, and validates that
the result is a JSON object (not a bare array or scalar).
"""

import json


def strip_json_fence(raw: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences some models wrap JSON in.

    Returns the inner content trimmed. Non-fenced input is returned as-is.
    """
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_response(raw: str, *, provider_hint: str) -> dict:
    """Clean fences and json.loads. On failure, fall back to json_repair
    which handles common LLM JSON quirks (unescaped quotes inside string
    values, literal LF/CR/TAB inside strings, trailing commas, etc.).

    Phase 7 will likely re-raise these as AIError(Kind.MALFORMED) at the
    provider adapter layer so feature layer can decide to retry.
    """
    cleaned = strip_json_fence(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # LLM JSON output frequently violates the spec — unescaped " inside
        # Chinese strings, raw newlines, trailing commas. json_repair is a
        # purpose-built recovery layer designed exactly for this.
        try:
            from json_repair import repair_json
            repaired = repair_json(cleaned)
            parsed = json.loads(repaired)
        except Exception as e:
            snippet = cleaned[:300].replace("\n", "\\n")
            raise RuntimeError(
                f"{provider_hint} returned non-JSON output (even after "
                f"json_repair fallback): {e}. "
                f"Raw (first 300 chars): {snippet!r}"
            )
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"{provider_hint} returned non-object JSON "
            f"(type={type(parsed).__name__}): {str(parsed)[:200]!r}"
        )
    return parsed
