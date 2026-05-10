"""llama-cpp-python provider — in-process GGUF LLM (translation, JSON tasks).

Part of VideoCraft's "embedded AI" tier (see
docs/draft/tech-selection-embedded-ai.md). Loads a Qwen3 (or any chat-tuned
GGUF) model fully in-process. No Docker, no network, no API key. Model
files live under `<repo>/user_data/models/llama/<file>.gguf` via core.paths.

Exposes the same surface as openai_compat so router._call / _call_json can
dispatch by ptype="llama_cpp" with no further branching:

    call(model_id, prompt) -> str
    call_json(model_id, prompt, schema, *, cancel_token=None) -> dict
    list_models() -> list[str]   # *.gguf filenames present on disk

`model_id` is the GGUF filename (with .gguf suffix), e.g.
"Qwen3-1.7B-Q4_K_M.gguf". Tiers in providers.json map tier name → filename.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from core.ai.errors import AIError, Kind
from core.ai.providers._json_utils import parse_json_response
from core.paths import cache_subdir


# Loading a 1.7B Q4_K_M takes ~1.5s on CPU; bigger models take longer and
# also consume meaningful VRAM. We hold exactly one model resident, dropping
# the previous when a different (path, n_ctx) is requested. This matches
# §8 of the embedded-AI design doc (serial VRAM scheduling on 8GB cards).
_LOADED: dict[str, Any] = {"key": None, "llm": None}


def _models_root() -> str:
    return cache_subdir("llama")


def _resolve_model_path(model_id: str) -> str:
    """Resolve a `model_id` into an absolute .gguf path under <models>/llama/.

    Accepts either bare filename ("Qwen3-1.7B-Q4_K_M.gguf") or a path with
    the .gguf extension. Always anchors under cache_subdir("llama") to keep
    portable-data invariant (no escaping into system dirs).
    """
    name = (model_id or "").strip()
    if not name:
        raise AIError(
            Kind.MALFORMED, "llama_cpp",
            "No model selected. Pick a .gguf file in the AI Console "
            "(Provider Manager → LlamaCpp → Models)."
        )
    if not name.lower().endswith(".gguf"):
        name = name + ".gguf"
    # Treat any path-ish input as basename only — model files live in one
    # canonical dir; arbitrary paths would break the portable-data contract.
    name = os.path.basename(name)
    return os.path.join(_models_root(), name)


def _load(model_path: str, *, n_ctx: int, n_gpu_layers: int, n_threads: int):
    from llama_cpp import Llama

    key = f"{model_path}|ctx={n_ctx}|gpu={n_gpu_layers}|th={n_threads}"
    if _LOADED["key"] == key and _LOADED["llm"] is not None:
        return _LOADED["llm"]

    if not os.path.exists(model_path):
        raise AIError(
            Kind.MALFORMED, "llama_cpp",
            f"GGUF model file not found:\n  {model_path}\n"
            f"Drop a Qwen3 GGUF (e.g. Qwen3-1.7B-Q4_K_M.gguf) into:\n"
            f"  {_models_root()}\n"
            "Source: https://huggingface.co/Qwen (or ModelScope mirror)."
        )

    # Drop previous model first so peak RAM/VRAM doesn't double during reload.
    _LOADED["key"] = None
    _LOADED["llm"] = None

    try:
        llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            verbose=False,
        )
    except Exception as e:
        raise AIError(
            Kind.UNKNOWN, "llama_cpp",
            f"llama-cpp-python failed to load model: {e}", raw=e
        ) from e

    _LOADED["key"] = key
    _LOADED["llm"] = llm
    return llm


def _chat(llm, messages: list[dict], *,
          response_format: dict | None = None,
          cancel_token=None) -> str:
    """Run a chat completion. Cancel is coarse-grained (checked before/after);
    llama-cpp's C++ generation loop cannot be interrupted mid-call."""
    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "llama_cpp", "Cancelled by user")
    try:
        kwargs: dict[str, Any] = {"messages": messages, "temperature": 0.2}
        if response_format is not None:
            kwargs["response_format"] = response_format
        resp = llm.create_chat_completion(**kwargs)
    except Exception as e:
        raise AIError(
            Kind.UNKNOWN, "llama_cpp",
            f"llama-cpp-python generation failed: {e}", raw=e
        ) from e
    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "llama_cpp", "Cancelled by user")
    try:
        return (resp["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(
            Kind.MALFORMED, "llama_cpp",
            f"Unexpected llama-cpp response shape: {resp!r}", raw=e
        ) from e


def call(model_id: str, prompt: str, *,
         n_ctx: int = 8192,
         n_gpu_layers: int = 0,
         n_threads: int = 4,
         cancel_token=None) -> str:
    """Plain text chat completion via llama-cpp-python."""
    path = _resolve_model_path(model_id)
    llm = _load(path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, n_threads=n_threads)
    return _chat(
        llm,
        [{"role": "user", "content": prompt}],
        cancel_token=cancel_token,
    )


def call_json(model_id: str, prompt: str, schema: dict, *,
              n_ctx: int = 8192,
              n_gpu_layers: int = 0,
              n_threads: int = 4,
              cancel_token=None) -> dict:
    """Structured JSON completion. Schema is injected as a system hint and
    response_format=json_object asks llama.cpp's grammar-constrained JSON
    mode to keep output well-formed. Mirrors openai_compat.call_json."""
    path = _resolve_model_path(model_id)
    llm = _load(path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, n_threads=n_threads)
    schema_hint = (
        "You must respond with a single JSON object that strictly matches "
        "this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        "Return only the JSON object. No markdown fences. No prose. "
        "No explanations."
    )
    raw = _chat(
        llm,
        [
            {"role": "system", "content": schema_hint},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        cancel_token=cancel_token,
    )
    return parse_json_response(raw, provider_hint="llama_cpp")


def list_models() -> list[str]:
    """Return *.gguf filenames present in <models>/llama/, sorted.

    Empty list when the directory is empty (or absent) — UI surfaces this
    as "no embedded LLM installed yet". cache_subdir creates the dir on
    demand so first-call always succeeds.
    """
    root = _models_root()
    files = glob.glob(os.path.join(root, "*.gguf"))
    return sorted(os.path.basename(f) for f in files)
