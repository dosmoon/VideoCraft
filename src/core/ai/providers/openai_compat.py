"""OpenAI-compatible provider (type='openai_compatible').

Covers DeepSeek and the user-defined Custom provider — any endpoint that
speaks the OpenAI chat.completions protocol.

Phase 1: extracted verbatim from ai_router.py; exceptions still bubble as
RuntimeError. Phase 7 will wrap openai.APIError / openai.RateLimitError /
openai.AuthenticationError into AIError with the appropriate Kind.
"""

import json

from core.ai.errors import AIError, map_openai_exception
from core.ai.providers._json_utils import parse_json_response


def _provider_label(base_url: str) -> str:
    """Best-effort name to surface in errors. DeepSeek vs Custom is a routing
    distinction the user picks; we hint with the host so they can tell which
    config blew up when multiple openai-compat providers coexist."""
    if "deepseek" in (base_url or "").lower():
        return "DeepSeek"
    return f"OpenAI-compat ({base_url})"


def call(api_key: str, base_url: str, model_id: str, prompt: str,
         *, cancel_token=None) -> str:
    """Plain text completion via OpenAI-compatible chat.completions."""
    from openai import OpenAI
    provider = _provider_label(base_url)
    client = OpenAI(api_key=api_key, base_url=base_url)
    if cancel_token is not None:
        cancel_token.register_abort(lambda c=client: _safe_close(c))
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()
    except AIError:
        raise
    except Exception as e:
        if cancel_token is not None and cancel_token.cancelled:
            from core.ai.errors import Kind
            raise AIError(Kind.CANCELLED, provider,
                          "Cancelled by user", raw=e) from e
        raise map_openai_exception(e, provider) from e


def list_models(api_key: str, base_url: str) -> list[str]:
    """Fetch model IDs from an OpenAI-compatible endpoint's GET /models.

    Returns a sorted list of model IDs the key has access to.
    """
    from openai import OpenAI
    provider = _provider_label(base_url)
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.models.list()
    except Exception as e:
        raise map_openai_exception(e, provider) from e
    ids = []
    for m in response.data:
        mid = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
        if mid:
            ids.append(mid)
    ids.sort()
    return ids


def call_json(api_key: str, base_url: str, model_id: str,
              prompt: str, schema: dict, *, cancel_token=None) -> dict:
    """Structured JSON completion.

    OpenAI-compat endpoints accept `response_format={"type":"json_object"}`
    but do NOT accept a schema directly — we inject the schema as a system
    hint to steer the model, then validate by parsing.

    cancel_token: when supplied, the underlying httpx client is registered
    for abort on cancel. Closing the OpenAI() client tears down its
    connection pool, which surfaces as APIConnectionError in the blocked
    .create() call → mapped to Kind.NETWORK and re-raised as CANCELLED
    when token.cancelled is set."""
    from openai import OpenAI
    provider = _provider_label(base_url)
    schema_hint = (
        "You must respond with a single JSON object that strictly matches "
        "this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        "Return only the JSON object. No markdown fences. No prose. No explanations."
    )
    client = OpenAI(api_key=api_key, base_url=base_url)
    if cancel_token is not None:
        cancel_token.register_abort(lambda c=client: _safe_close(c))
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": schema_hint},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
    except AIError:
        raise
    except Exception as e:
        if cancel_token is not None and cancel_token.cancelled:
            from core.ai.errors import Kind
            raise AIError(Kind.CANCELLED, provider,
                          "Cancelled by user", raw=e) from e
        raise map_openai_exception(e, provider) from e
    return parse_json_response(raw, provider_hint="OpenAI-compatible")


def _safe_close(client) -> None:
    """Best-effort client close — never raise from an abort callback."""
    try:
        client.close()
    except Exception:
        pass
