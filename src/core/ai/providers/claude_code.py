"""Claude Code subprocess provider (type='claude_code').

Invokes the local `claude -p` CLI headless; no API key — the CLI handles its
own auth via claude.com login. The prompt is piped over stdin to avoid
Windows' ~32KB command-line length ceiling.

--permission-mode bypassPermissions is safe here because we never ask the
model to use Write/Edit; we only consume its text output.

For search-grounded tasks (e.g. news.realtime), call_json detours through
a separate path that enables the built-in WebSearch tool. --json-schema
is mutually exclusive with WebSearch (verified empirically: web_search_requests
drops to 0 when --json-schema is set), so the search path uses plain
prompt-injected schema enforcement instead. Citations are extracted from
markdown URL links in the result text (Claude's CLI does not expose a
structured citations array).
"""

import json
import re
import shutil
import subprocess
import time

from core.ai import call_log
from core.ai.errors import AIError, Kind, map_subprocess_exception
from core.ai.providers._json_utils import parse_json_response


# Tasks that need search-grounded answers — same set openai_compat uses
# for xAI. Both providers must support news.realtime so VideoCraft isn't
# single-vendor-locked on the news context feature.
_SEARCH_REQUIRED_TASKS = {"news.realtime"}


def call(cfg: dict, model_id: str, prompt: str,
         *, task: str = "", cancel_token=None) -> str:
    """Plain text completion."""
    cmd = _cmd(cfg, model_id, output_format="text")
    return _run(cmd, cfg, prompt, cancel_token=cancel_token)


def call_json(cfg: dict, model_id: str, prompt: str, schema: dict,
              *, task: str = "", cancel_token=None) -> dict:
    """Structured JSON completion. For search-grounded tasks (news.realtime
    et al.), enables the built-in WebSearch tool. Otherwise uses the plain
    JSON output mode."""
    if task in _SEARCH_REQUIRED_TASKS:
        return _call_json_with_search(cfg, model_id, prompt, schema,
                                       task=task, cancel_token=cancel_token)
    return _call_json_plain(cfg, model_id, prompt, schema,
                              task=task, cancel_token=cancel_token)


def _call_json_plain(cfg: dict, model_id: str, prompt: str, schema: dict,
                      *, task: str, cancel_token=None) -> dict:
    """Uses --output-format json, which wraps the model's text in a result
    envelope: {"type":"result","subtype":"success","result":"...","cost_usd":...}.
    The envelope's `result` field is the model's raw text; since we ask the
    model to emit JSON, we parse that string a second time.
    """
    cmd = _cmd(cfg, model_id, output_format="json")
    full_prompt = (
        f"{prompt}\n\n"
        "Respond with ONLY a single JSON object that strictly matches "
        "this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        "No prose. No markdown. No code fences. Just the JSON object."
    )
    started = time.perf_counter()
    try:
        envelope_raw = _run(cmd, cfg, full_prompt, cancel_token=cancel_token)
        envelope = json.loads(envelope_raw)
    except json.JSONDecodeError:
        call_log.append(_log_entry(model_id, task, "claude_plain",
                                     started, error="CLI returned non-JSON"))
        raise AIError(Kind.MALFORMED, "ClaudeCode",
                      "CLI returned non-JSON stdout")
    except Exception as e:
        call_log.append(_log_entry(model_id, task, "claude_plain",
                                     started, error=str(e)[:500]))
        raise

    inner_text = envelope.get("result", "")
    if not inner_text:
        call_log.append(_log_entry(model_id, task, "claude_plain",
                                     started, error="missing 'result' field"))
        raise AIError(Kind.MALFORMED, "ClaudeCode",
                      f"Result envelope missing 'result' field")

    usage = envelope.get("usage") or {}
    call_log.append(_log_entry(model_id, task, "claude_plain", started,
        content_chars=len(inner_text),
        content_preview=inner_text[:500],
        usage={
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "total_cost_usd": envelope.get("total_cost_usd"),
        }))
    return parse_json_response(inner_text, provider_hint="ClaudeCode")


def _call_json_with_search(cfg: dict, model_id: str, prompt: str,
                            schema: dict, *, task: str,
                            cancel_token=None) -> dict:
    """Like _call_json_plain but adds `--tools WebSearch`. Citations are
    extracted from the trailing markdown links in the result text.

    Caveat: --json-schema CLI flag is INTENTIONALLY not used here — it
    suppresses WebSearch tool invocation (verified: web_search_requests
    drops to 0 when both are set). Schema enforcement falls back to the
    in-prompt hint.
    """
    cmd = _cmd(cfg, model_id, output_format="json", tools=["WebSearch"])
    full_prompt = (
        f"{prompt}\n\n"
        "Respond with a single JSON object that strictly matches this "
        "JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        "After the JSON, optionally list the URLs you searched as "
        "bullet-point markdown links (`- [Title](url)`) for verification."
    )
    started = time.perf_counter()
    try:
        envelope_raw = _run(cmd, cfg, full_prompt, cancel_token=cancel_token)
        envelope = json.loads(envelope_raw)
    except json.JSONDecodeError:
        call_log.append(_log_entry(model_id, task, "claude_websearch",
                                     started, error="CLI returned non-JSON"))
        raise AIError(Kind.MALFORMED, "ClaudeCode",
                      "CLI returned non-JSON stdout")
    except Exception as e:
        call_log.append(_log_entry(model_id, task, "claude_websearch",
                                     started, error=str(e)[:500]))
        raise

    result_text = envelope.get("result", "") or ""
    if not result_text:
        call_log.append(_log_entry(model_id, task, "claude_websearch",
                                     started, error="missing 'result' field"))
        raise AIError(Kind.MALFORMED, "ClaudeCode",
                      "Result envelope missing 'result' field")

    json_text = _extract_json_block(result_text)
    citations = _extract_citations(result_text)
    usage = envelope.get("usage") or {}
    server_tool = usage.get("server_tool_use") or {}

    call_log.append(_log_entry(model_id, task, "claude_websearch", started,
        content_chars=len(result_text),
        content_preview=result_text[:500],
        citations=citations,
        usage={
            "input_tokens":             usage.get("input_tokens"),
            "output_tokens":            usage.get("output_tokens"),
            "cache_read_input_tokens":  usage.get("cache_read_input_tokens"),
            "web_search_requests":      server_tool.get("web_search_requests"),
            "total_cost_usd":           envelope.get("total_cost_usd"),
        }))
    return parse_json_response(json_text, provider_hint="ClaudeCode")


def _extract_json_block(text: str) -> str:
    """Pull the JSON object out of a `result` text that may have markdown
    fences and trailing markdown citations. Tries ```json fence first,
    then falls back to first '{' .. matching last '}'.
    """
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]
    return text


def _extract_citations(text: str) -> list[str]:
    """Extract every http(s) URL from markdown-link form `(http...)` in the
    result text. Dedupes while preserving order. False positives (URLs
    inside JSON string values) are tolerated — they're still real refs."""
    seen: dict[str, None] = {}
    for u in re.findall(r"\((https?://[^\s)]+)\)", text):
        seen.setdefault(u, None)
    return list(seen.keys())


def _log_entry(model_id: str, task: str, endpoint: str,
                started: float, *,
                content_chars: int = 0,
                content_preview: str = "",
                citations: list | None = None,
                usage: dict | None = None,
                error: str | None = None) -> dict:
    """Build a call_log entry dict for ClaudeCode invocations."""
    entry = {
        "kind":      "llm.complete_json",
        "provider":  "ClaudeCode",
        "model":     model_id,
        "task":      task,
        "endpoint":  endpoint,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    if error is not None:
        entry["error"] = error
    else:
        entry["response"] = {
            "content_chars":   content_chars,
            "content_preview": content_preview,
            "citations":       citations or [],
            "usage":           usage or {},
        }
    return entry


def _cmd(cfg: dict, model_id: str, *,
         output_format: str,
         tools: list[str] | None = None) -> list:
    """Build the argv list for a headless `claude -p` invocation.

    `tools`: optional list of built-in tool names to enable. The CLI
    defaults to all tools when --tools is omitted; passing an explicit
    list restricts to that subset, which we use to enable WebSearch
    only when news.realtime calls in.
    """
    executable = cfg.get("executable") or "claude"
    cmd = [
        executable, "-p",
        "--output-format", output_format,
        "--permission-mode", "bypassPermissions",
    ]
    if tools is not None:
        cmd += ["--tools", ",".join(tools)]
    if model_id:
        cmd += ["--model", model_id]
    extra = cfg.get("extra_args") or []
    if extra:
        cmd += list(extra)
    return cmd


def _run(cmd: list, cfg: dict, prompt: str, *, cancel_token=None) -> str:
    """Spawn the Claude CLI subprocess with prompt on stdin, return stdout.
    Raises AIError on missing binary, timeout, or non-zero exit."""
    executable = cmd[0] if cmd else "claude"

    # On Windows, npm-installed CLIs land as `claude.cmd` (or .bat). Plain
    # subprocess.run() only matches `.exe` unless shell=True. shutil.which()
    # honors PATHEXT and resolves to the actual `.cmd` so we can pass an
    # absolute path that subprocess can launch directly. No-op on POSIX
    # (just returns the same path).
    resolved = shutil.which(executable)
    if resolved:
        cmd = [resolved] + list(cmd[1:])

    timeout_sec = int(cfg.get("timeout_sec", 600))
    # Manual Popen so we can register an abort that terminates the child.
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise map_subprocess_exception(
            e, "ClaudeCode",
            executable=executable, timeout_sec=timeout_sec) from e

    if cancel_token is not None:
        cancel_token.register_abort(lambda p=proc: _safe_terminate(p))

    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        try:
            proc.communicate()
        except Exception:
            pass
        raise map_subprocess_exception(
            e, "ClaudeCode",
            executable=executable, timeout_sec=timeout_sec) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "ClaudeCode", "Cancelled by user")

    class _R:  # adapter so the rest of _run code reads as before
        pass
    result = _R()
    result.returncode = proc.returncode
    result.stdout = stdout or ""
    result.stderr = stderr or ""
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-10:]
        joined = " | ".join(tail).lower()
        # Sniff the CLI's stderr for known failure modes; default to UNKNOWN.
        kind = Kind.UNKNOWN
        if "not authorized" in joined or "not logged in" in joined:
            kind = Kind.AUTH
        elif "rate limit" in joined or "429" in joined:
            kind = Kind.RATE_LIMIT
        elif "context" in joined and "exceed" in joined:
            kind = Kind.OVERFLOW
        raise AIError(kind, "ClaudeCode",
                      "CLI failed: " + (" | ".join(tail) or "<no stderr>"))
    return (result.stdout or "").strip()


def _safe_terminate(proc) -> None:
    """Best-effort terminate of a Popen process — never raise from abort."""
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass
