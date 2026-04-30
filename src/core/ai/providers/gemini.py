"""Gemini provider (type='gemini').

Uses the modern google-genai SDK (`from google import genai`). The legacy
`google-generativeai` SDK was deprecated by Google in 2024-09 and is no
longer used here.
"""

from core.ai.errors import AIError, map_gemini_exception
from core.ai.providers._json_utils import parse_json_response


def call(api_key: str, model_id: str, prompt: str, *, cancel_token=None) -> str:
    """Plain text completion via google-genai SDK."""
    from google import genai
    client = genai.Client(api_key=api_key)
    if cancel_token is not None:
        cancel_token.register_abort(lambda c=client: _safe_close(c))
    try:
        response = client.models.generate_content(model=model_id, contents=prompt)
        return (response.text or "").strip()
    except AIError:
        raise
    except Exception as e:
        if cancel_token is not None and cancel_token.cancelled:
            from core.ai.errors import Kind
            raise AIError(Kind.CANCELLED, "Gemini",
                          "Cancelled by user", raw=e) from e
        raise map_gemini_exception(e) from e


def call_json(api_key: str, model_id: str, prompt: str, schema: dict,
              *, cancel_token=None) -> dict:
    """Structured JSON completion via Gemini's native response_schema flag."""
    from google import genai
    from google.genai.types import GenerateContentConfig
    client = genai.Client(api_key=api_key)
    if cancel_token is not None:
        cancel_token.register_abort(lambda c=client: _safe_close(c))
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        raw = (response.text or "").strip()
    except AIError:
        raise
    except Exception as e:
        if cancel_token is not None and cancel_token.cancelled:
            from core.ai.errors import Kind
            raise AIError(Kind.CANCELLED, "Gemini",
                          "Cancelled by user", raw=e) from e
        raise map_gemini_exception(e) from e
    return parse_json_response(raw, provider_hint="Gemini")


def _safe_close(client) -> None:
    """Best-effort google-genai client teardown — never raise from abort.

    The new google-genai SDK keeps an httpx client on _api_client; close it
    to interrupt any in-flight call. Schema differs across SDK versions so
    we try a couple of paths; failures are swallowed."""
    try:
        for path in ("close", "_api_client", "_client"):
            target = getattr(client, path, None)
            if target is None:
                continue
            close = getattr(target, "close", None) if path != "close" else target
            if callable(close):
                close()
                return
    except Exception:
        pass


def list_models(api_key: str) -> list[str]:
    """Fetch the available generation-capable model IDs from Gemini.

    Returned IDs are stripped of the leading "models/" prefix (so they can
    be passed back into `call(model_id=...)` directly). Filtered to models
    that support generateContent (skips embedding-only / vision-only ones).
    """
    from google import genai
    try:
        client = genai.Client(api_key=api_key)
        models = list(client.models.list())
    except Exception as e:
        raise map_gemini_exception(e) from e
    out: list[str] = []
    for m in models:
        actions = list(m.supported_actions or [])
        if "generateContent" not in actions:
            continue
        name = (m.name or "")
        if name.startswith("models/"):
            name = name[len("models/"):]
        if name:
            out.append(name)
    out.sort()
    return out
