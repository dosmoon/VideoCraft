"""OpenAI-compatible provider (type='openai_compatible').

Covers DeepSeek and the user-defined Custom provider — any endpoint that
speaks the OpenAI chat.completions protocol.

Phase 1: extracted verbatim from ai_router.py; exceptions still bubble as
RuntimeError. Phase 7 will wrap openai.APIError / openai.RateLimitError /
openai.AuthenticationError into AIError with the appropriate Kind.
"""

import json
import time
import urllib.error
import urllib.request

from core.ai import call_log
from core.ai.errors import AIError, Kind, map_openai_exception
from core.ai.providers._json_utils import parse_json_response


def _extract_response_extras(response) -> dict:
    """Return {citations, usage, content_preview} from an OpenAI chat response.

    Citations are an xAI extension carried as a top-level field (not in
    OpenAI's standard schema) — we pull them out via model_dump() for
    log surfacing. Returns an empty/None-filled dict when unavailable.
    """
    out: dict = {"citations": None, "usage": None}
    try:
        dumped = response.model_dump()
    except Exception:
        dumped = {}
    citations = dumped.get("citations")
    if citations is None:
        # Some providers nest under choices[0].message.citations.
        try:
            citations = dumped["choices"][0]["message"].get("citations")
        except Exception:
            citations = None
    if citations:
        out["citations"] = citations
    usage = dumped.get("usage")
    if usage:
        out["usage"] = usage
    return out


def _provider_label(base_url: str) -> str:
    """Best-effort name to surface in errors. DeepSeek vs Custom is a routing
    distinction the user picks; we hint with the host so they can tell which
    config blew up when multiple openai-compat providers coexist."""
    if "deepseek" in (base_url or "").lower():
        return "DeepSeek"
    if "x.ai" in (base_url or "").lower():
        return "xAI"
    return f"OpenAI-compat ({base_url})"


# Tasks that need search-grounded answers. When such a task hits an xAI
# endpoint, the provider injects the built-in web_search tool — without
# this, Grok answers only from training data and grossly mis-handles
# current events (source-context extraction is the canonical example).
_SEARCH_REQUIRED_TASKS = {"news.realtime"}


def _xai_uses_responses_api(task: str, base_url: str) -> bool:
    """Whether to detour to xAI's /v1/responses endpoint instead of chat
    completions. Required for search-grounded tasks: chat.completions
    `search_parameters` and tool variants `web_search`/`live_search` are
    all dead ends on xAI as of 2026-05 (410 / 422). The Responses API
    is the only working path for built-in web search.
    """
    return task in _SEARCH_REQUIRED_TASKS and "x.ai" in (base_url or "").lower()


def _responses_url(base_url: str) -> str:
    """Derive the /v1/responses URL from a /v1 base_url."""
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1"):
        return base + "/responses"
    return base + "/v1/responses"


def _call_xai_responses_json(api_key: str, base_url: str, model_id: str,
                              prompt: str, schema: dict,
                              *, task: str, cancel_token=None) -> dict:
    """POST to xAI's /v1/responses with the built-in web_search tool.

    Response shape (verified empirically against grok-4-fast on
    2026-05-14):
        {
          "output": [
            {"type": "web_search_call", "action": {"query": "..."}},
            {"type": "message", "content": [{
                "type": "output_text",
                "text": "<the model's reply>",
                "annotations": [{"type":"url_citation","url":"..."}]
            }]}
          ],
          "usage": {"input_tokens", "output_tokens", "total_tokens",
                    "server_side_tool_usage_details": {"web_search_calls"}}
        }

    We extract message text + url_citation annotations + search queries,
    log them via call_log, then parse the JSON content per schema.
    """
    schema_hint = (
        "You must respond with a single JSON object that strictly matches "
        "this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        "Return only the JSON object. No markdown fences. No prose."
    )
    body = {
        "model": model_id,
        "input": [
            {"role": "system", "content": schema_hint},
            {"role": "user",   "content": prompt},
        ],
        "tools": [{"type": "web_search"}],
    }
    started = time.perf_counter()
    req = urllib.request.Request(
        _responses_url(base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    if cancel_token is not None:
        cancel_token.register_abort(lambda: None)  # urllib has no graceful abort
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:600]
        except Exception:
            pass
        call_log.append({
            "kind":      "llm.complete_json",
            "provider":  "xAI",
            "base_url":  base_url,
            "model":     model_id,
            "task":      task,
            "endpoint":  "responses",
            "error":     f"HTTP {e.code}: {err_body}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "xAI",
                          "Cancelled by user", raw=e) from e
        raise RuntimeError(f"xAI Responses API {e.code}: {err_body}") from e
    except Exception as e:
        call_log.append({
            "kind":      "llm.complete_json",
            "provider":  "xAI",
            "base_url":  base_url,
            "model":     model_id,
            "task":      task,
            "endpoint":  "responses",
            "error":     str(e)[:500],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "xAI",
                          "Cancelled by user", raw=e) from e
        raise

    text, citations, queries = _extract_responses_content(data)
    usage = data.get("usage") or {}
    call_log.append({
        "kind":      "llm.complete_json",
        "provider":  "xAI",
        "base_url":  base_url,
        "model":     model_id,
        "task":      task,
        "endpoint":  "responses",
        "request":   {
            "prompt_chars":    len(prompt),
            "schema_required": schema.get("required") or [],
            "tools":           [{"type": "web_search"}],
        },
        "response":  {
            "content_chars":     len(text),
            "content_preview":   text[:500],
            "citations":         citations,
            "search_queries":    queries,
            "usage":             usage,
        },
        "latency_ms": int((time.perf_counter() - started) * 1000),
    })
    return parse_json_response(text, provider_hint="xAI Responses")


def _extract_responses_content(data: dict) -> tuple[str, list[str], list[str]]:
    """Pull (message_text, citation_urls, search_queries) from a Responses
    API payload. Robust to extra item types we don't care about (reasoning
    blocks, file_search_call, etc.)."""
    text_parts: list[str] = []
    citations: list[str] = []
    queries: list[str] = []
    for item in data.get("output") or []:
        kind = item.get("type")
        if kind == "message":
            for c in item.get("content") or []:
                t = c.get("text") or ""
                if t:
                    text_parts.append(t)
                for ann in c.get("annotations") or []:
                    if ann.get("type") == "url_citation":
                        u = ann.get("url")
                        if u:
                            citations.append(u)
        elif kind == "web_search_call":
            q = (item.get("action") or {}).get("query")
            if q:
                queries.append(q)
    return ("".join(text_parts), citations, queries)


def call(api_key: str, base_url: str, model_id: str, prompt: str,
         *, task: str = "", cancel_token=None) -> str:
    """Plain text completion via OpenAI-compatible chat.completions."""
    from openai import OpenAI
    provider = _provider_label(base_url)
    client = OpenAI(api_key=api_key, base_url=base_url)
    if cancel_token is not None:
        cancel_token.register_abort(lambda c=client: _safe_close(c))
    # Plain-text complete() has no search-grounded use case in
    # VideoCraft today — all news.realtime usage goes through
    # complete_json which detours to xAI's /v1/responses.
    started = time.perf_counter()
    try:
        kwargs: dict = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content.strip()
        extras = _extract_response_extras(response)
        call_log.append({
            "kind":      "llm.complete",
            "provider":  provider,
            "base_url":  base_url,
            "model":     model_id,
            "task":      task,
            "request":   {
                "prompt_chars": len(prompt),
            },
            "response":  {
                "content_chars":   len(content),
                "content_preview": content[:500],
                "citations":       extras["citations"],
                "usage":           extras["usage"],
            },
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
        return content
    except AIError:
        raise
    except Exception as e:
        call_log.append({
            "kind":      "llm.complete",
            "provider":  provider,
            "base_url":  base_url,
            "model":     model_id,
            "task":      task,
            "error":     str(e)[:500],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
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
              prompt: str, schema: dict, *,
              task: str = "", cancel_token=None) -> dict:
    """Structured JSON completion.

    OpenAI-compat endpoints accept `response_format={"type":"json_object"}`
    but do NOT accept a schema directly — we inject the schema as a system
    hint to steer the model, then validate by parsing.

    cancel_token: when supplied, the underlying httpx client is registered
    for abort on cancel. Closing the OpenAI() client tears down its
    connection pool, which surfaces as APIConnectionError in the blocked
    .create() call → mapped to Kind.NETWORK and re-raised as CANCELLED
    when token.cancelled is set."""
    # xAI + search-required tasks bypass chat.completions entirely:
    # /v1/responses is the only endpoint with working web search.
    if _xai_uses_responses_api(task, base_url):
        return _call_xai_responses_json(api_key, base_url, model_id,
                                          prompt, schema, task=task,
                                          cancel_token=cancel_token)

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
    started = time.perf_counter()
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
        extras = _extract_response_extras(response)
        call_log.append({
            "kind":      "llm.complete_json",
            "provider":  provider,
            "base_url":  base_url,
            "model":     model_id,
            "task":      task,
            "request":   {
                "prompt_chars":    len(prompt),
                "schema_required": schema.get("required") or [],
            },
            "response":  {
                "content_chars":   len(raw),
                "content_preview": raw[:500],
                "citations":       extras["citations"],
                "usage":           extras["usage"],
            },
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
    except AIError:
        raise
    except Exception as e:
        call_log.append({
            "kind":      "llm.complete_json",
            "provider":  provider,
            "base_url":  base_url,
            "model":     model_id,
            "task":      task,
            "error":     str(e)[:500],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
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
