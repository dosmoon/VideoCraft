"""Gemini provider (type='gemini').

Uses the modern google-genai SDK (`from google import genai`). The legacy
`google-generativeai` SDK was deprecated by Google in 2024-09 and is no
longer used here.
"""

from core.ai.providers._json_utils import parse_json_response


def call(api_key: str, model_id: str, prompt: str) -> str:
    """Plain text completion via google-genai SDK."""
    from google import genai
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model_id, contents=prompt)
    return (response.text or "").strip()


def call_json(api_key: str, model_id: str, prompt: str, schema: dict) -> dict:
    """Structured JSON completion via Gemini's native response_schema flag."""
    from google import genai
    from google.genai.types import GenerateContentConfig
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    raw = (response.text or "").strip()
    return parse_json_response(raw, provider_hint="Gemini")


def list_models(api_key: str) -> list[str]:
    """Fetch the available generation-capable model IDs from Gemini.

    Returned IDs are stripped of the leading "models/" prefix (so they can
    be passed back into `call(model_id=...)` directly). Filtered to models
    that support generateContent (skips embedding-only / vision-only ones).
    """
    from google import genai
    client = genai.Client(api_key=api_key)
    out: list[str] = []
    for m in client.models.list():
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
