"""AIError contract with 9 error kinds.

Phase 1 defines the contract; providers still raise plain RuntimeError as
before. Phase 7 will add provider-specific native-exception mapping so that
feature/UI layers can branch on `e.kind`.

UI mapping (see docs/design/04-ai-router.md): each Kind has a recommended
action button that dispatches to the right remediation (AUTH -> open Router
tab, QUOTA -> switch provider, etc.).
"""

from enum import Enum


class Kind(Enum):
    NETWORK    = "network"       # DNS / TCP / TLS / timeout — retryable (transport)
    AUTH       = "auth"          # invalid / expired / revoked key — fatal
    QUOTA      = "quota"         # daily / monthly quota exhausted — fatal until reset
    RATE_LIMIT = "rate_limit"    # per-minute throttle — retryable (respect Retry-After)
    REFUSED    = "refused"       # safety filter refusal — not retryable, semantic issue
    MALFORMED  = "malformed"     # JSON schema mismatch — retryable by feature layer
    OVERFLOW   = "overflow"      # input exceeds context window — fatal for this tier
    CANCELLED  = "cancelled"     # user cancelled — via CancellationToken
    UNKNOWN    = "unknown"       # unclassified — surface raw for logs


class AIError(Exception):
    """Structured AI call error.

    Args:
        kind: one of Kind enum values.
        provider: the provider that failed (e.g. "Gemini", "DeepSeek").
        message: human-readable text safe to show users.
        retry_after: seconds the provider suggested waiting (from Retry-After
                     header when RATE_LIMIT).
        raw: original exception for logging — not meant for user display.
    """

    def __init__(self, kind: Kind, provider: str, message: str,
                 retry_after: float | None = None,
                 raw: Exception | None = None):
        super().__init__(message)
        self.kind = kind
        self.provider = provider
        self.message = message
        self.retry_after = retry_after
        self.raw = raw

    def __str__(self) -> str:
        return f"[{self.kind.value}/{self.provider}] {self.message}"


# ── Provider exception mappers ───────────────────────────────────────────────
# Each provider has its own SDK exception taxonomy. These functions take a
# raw native exception and return a structured AIError. Callers wrap their
# SDK call in try/except Exception and pass the exception here. Keep the
# matching ladder loose — when in doubt, prefer UNKNOWN over a wrong Kind
# (UI shows raw text on UNKNOWN, which is at least correct, vs. "AUTH" on
# something that's actually a transient network blip would mislead users).


def _summarize(msg: str, max_chars: int = 240) -> str:
    msg = (msg or "").strip()
    return msg[:max_chars] + ("..." if len(msg) > max_chars else "")


def _parse_retry_after_seconds(resp) -> float | None:
    """Parse Retry-After from an httpx/requests response. None if absent."""
    if resp is None:
        return None
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    val = headers.get("Retry-After") or headers.get("retry-after")
    if not val:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def map_openai_exception(e: Exception, provider: str) -> AIError:
    """Map openai SDK exceptions (used by DeepSeek / Custom / OpenAI-compat).

    Inspects status codes and body keywords because the OpenAI exception
    taxonomy mostly mirrors HTTP semantics. Quota vs rate-limit is the
    trickiest split — both come back as 429; we look at body keywords to
    decide between QUOTA (fatal until reset) and RATE_LIMIT (retryable).
    """
    try:
        from openai import (
            AuthenticationError, PermissionDeniedError,
            RateLimitError, APIConnectionError, APITimeoutError,
            NotFoundError, BadRequestError, InternalServerError,
            APIError as OpenAIAPIError,
        )
    except ImportError:
        return AIError(Kind.UNKNOWN, provider, _summarize(str(e)), raw=e)

    msg = str(e)
    msg_low = msg.lower()
    resp = getattr(e, "response", None)

    if isinstance(e, AuthenticationError):
        return AIError(Kind.AUTH, provider,
                       "API key invalid or expired", raw=e)
    if isinstance(e, PermissionDeniedError):
        return AIError(Kind.AUTH, provider,
                       "Permission denied — key lacks access to this resource",
                       raw=e)
    if isinstance(e, RateLimitError):
        if any(k in msg_low for k in ("quota", "exceeded your", "billing",
                                       "insufficient", "credit")):
            return AIError(Kind.QUOTA, provider, _summarize(msg), raw=e)
        return AIError(Kind.RATE_LIMIT, provider, _summarize(msg),
                       retry_after=_parse_retry_after_seconds(resp), raw=e)
    if isinstance(e, (APIConnectionError, APITimeoutError)):
        return AIError(Kind.NETWORK, provider, _summarize(msg), raw=e)
    if isinstance(e, NotFoundError):
        return AIError(Kind.MALFORMED, provider,
                       f"Not found (model id wrong?): {_summarize(msg)}",
                       raw=e)
    if isinstance(e, BadRequestError):
        if any(k in msg_low for k in ("context length", "maximum context",
                                       "too long", "context window",
                                       "exceeds the maximum")):
            return AIError(Kind.OVERFLOW, provider, _summarize(msg), raw=e)
        if any(k in msg_low for k in ("safety", "blocked", "policy",
                                       "content_filter", "responsible_ai")):
            return AIError(Kind.REFUSED, provider, _summarize(msg), raw=e)
        return AIError(Kind.MALFORMED, provider, _summarize(msg), raw=e)
    if isinstance(e, InternalServerError):
        return AIError(Kind.NETWORK, provider,
                       "Provider server error (transient, retry helps)",
                       raw=e)
    if isinstance(e, OpenAIAPIError):
        return AIError(Kind.UNKNOWN, provider, _summarize(msg), raw=e)
    return AIError(Kind.UNKNOWN, provider, _summarize(msg), raw=e)


def map_gemini_exception(e: Exception, provider: str = "Gemini") -> AIError:
    """Map google.genai exceptions.

    The new SDK uses ClientError (4xx) / ServerError (5xx) hierarchies;
    we look at the .code attribute when present, then fall back to body
    keyword sniffing. Connection-layer failures arrive as raw httpx
    exceptions and get classified as NETWORK by default.
    """
    msg = str(e)
    msg_low = msg.lower()
    code = getattr(e, "code", None) or getattr(e, "status_code", None)

    try:
        from google.genai import errors as gerr
        client_err = getattr(gerr, "ClientError", ())
        server_err = getattr(gerr, "ServerError", ())
    except ImportError:
        client_err = ()
        server_err = ()

    if isinstance(e, server_err) if server_err else False:
        return AIError(Kind.NETWORK, provider,
                       "Provider server error (transient, retry helps)",
                       raw=e)
    if isinstance(e, client_err) if client_err else False:
        if code == 401 or "api key" in msg_low or "unauthorized" in msg_low:
            return AIError(Kind.AUTH, provider, "API key invalid", raw=e)
        if code == 403:
            return AIError(Kind.AUTH, provider,
                           "Permission denied (key lacks access)", raw=e)
        if code == 429:
            if "quota" in msg_low:
                return AIError(Kind.QUOTA, provider,
                               "Quota exceeded", raw=e)
            return AIError(Kind.RATE_LIMIT, provider, _summarize(msg), raw=e)
        if code == 400 or code == 422:
            if "context" in msg_low or "token" in msg_low:
                return AIError(Kind.OVERFLOW, provider, _summarize(msg), raw=e)
            if "safety" in msg_low or "blocked" in msg_low:
                return AIError(Kind.REFUSED, provider, _summarize(msg), raw=e)
            return AIError(Kind.MALFORMED, provider, _summarize(msg), raw=e)
        return AIError(Kind.UNKNOWN, provider, _summarize(msg), raw=e)

    # Unknown exception type — sniff message anyway as a last resort
    if "api key" in msg_low or "api_key" in msg_low:
        return AIError(Kind.AUTH, provider, _summarize(msg), raw=e)
    if "quota" in msg_low:
        return AIError(Kind.QUOTA, provider, _summarize(msg), raw=e)
    if "rate" in msg_low and "limit" in msg_low:
        return AIError(Kind.RATE_LIMIT, provider, _summarize(msg), raw=e)
    if any(t in msg_low for t in ("timeout", "timed out", "connection")):
        return AIError(Kind.NETWORK, provider, _summarize(msg), raw=e)
    return AIError(Kind.UNKNOWN, provider, _summarize(msg), raw=e)


def map_subprocess_exception(e: Exception, provider: str, *,
                              executable: str = "",
                              timeout_sec: int | None = None) -> AIError:
    """Map subprocess-based provider exceptions (ClaudeCode CLI)."""
    import subprocess
    if isinstance(e, FileNotFoundError):
        return AIError(Kind.AUTH, provider,
                       f"CLI not found: {executable!r} — install or set "
                       "an absolute path in the AI Console", raw=e)
    if isinstance(e, subprocess.TimeoutExpired):
        return AIError(Kind.NETWORK, provider,
                       f"CLI timed out after {timeout_sec}s", raw=e)
    return AIError(Kind.UNKNOWN, provider, _summarize(str(e)), raw=e)


def map_http_status_to_kind(status_code: int, body: str = "") -> Kind:
    """Generic HTTP status → Kind mapping, used by Lemonfox / Fish Audio
    where the SDK doesn't expose a typed exception hierarchy. body hints
    distinguish QUOTA from RATE_LIMIT etc."""
    body_low = (body or "").lower()
    if status_code == 401:
        return Kind.AUTH
    if status_code == 403:
        return Kind.AUTH
    if status_code == 429:
        if any(k in body_low for k in ("quota", "exceeded", "billing")):
            return Kind.QUOTA
        return Kind.RATE_LIMIT
    if status_code == 404:
        return Kind.MALFORMED
    if status_code == 400:
        if any(k in body_low for k in ("context", "too long", "maximum")):
            return Kind.OVERFLOW
        if any(k in body_low for k in ("safety", "blocked", "policy")):
            return Kind.REFUSED
        return Kind.MALFORMED
    if 500 <= status_code < 600:
        return Kind.NETWORK
    return Kind.UNKNOWN
