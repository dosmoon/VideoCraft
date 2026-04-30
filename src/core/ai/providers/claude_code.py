"""Claude Code subprocess provider (type='claude_code').

Invokes the local `claude -p` CLI headless; no API key — the CLI handles its
own auth via claude.com login. The prompt is piped over stdin to avoid
Windows' ~32KB command-line length ceiling.

--permission-mode bypassPermissions is safe here because we never ask the
model to use Write/Edit; we only consume its text output.

Phase 1: extracted verbatim from ai_router.py. Phase 7 will map subprocess
errors (FileNotFoundError, TimeoutExpired, non-zero exit) to AIError kinds.
"""

import json
import shutil
import subprocess

from core.ai.errors import AIError, Kind, map_subprocess_exception
from core.ai.providers._json_utils import parse_json_response


def call(cfg: dict, model_id: str, prompt: str, *, cancel_token=None) -> str:
    """Plain text completion."""
    cmd = _cmd(cfg, model_id, output_format="text")
    return _run(cmd, cfg, prompt, cancel_token=cancel_token)


def call_json(cfg: dict, model_id: str, prompt: str, schema: dict,
              *, cancel_token=None) -> dict:
    """Structured JSON completion.

    Uses --output-format json, which wraps the model's text in a result
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
    envelope_raw = _run(cmd, cfg, full_prompt, cancel_token=cancel_token)

    try:
        envelope = json.loads(envelope_raw)
    except json.JSONDecodeError:
        raise AIError(
            Kind.MALFORMED, "ClaudeCode",
            f"CLI returned non-JSON stdout: {envelope_raw[:200]!r}",
        )
    inner_text = envelope.get("result", "")
    if not inner_text:
        raise AIError(
            Kind.MALFORMED, "ClaudeCode",
            f"Result envelope missing 'result' field: {str(envelope)[:200]!r}",
        )
    return parse_json_response(inner_text, provider_hint="ClaudeCode")


def _cmd(cfg: dict, model_id: str, *, output_format: str) -> list:
    """Build the argv list for a headless `claude -p` invocation."""
    executable = cfg.get("executable") or "claude"
    cmd = [
        executable, "-p",
        "--output-format", output_format,
        "--permission-mode", "bypassPermissions",
    ]
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
