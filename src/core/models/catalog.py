"""Declarative catalog of embedded-AI models.

Each ModelSpec is a thin pointer: (HF repo, revision, list of basenames).
**No sizes or hashes here** — those come from the HF tree API at runtime
via `core.models.hf_api.resolve_files`, cached on disk so offline use
keeps working. This is the discipline lesson from 2026-05-10: hardcoded
sizes / made-up filenames rot fast and are never right.

Adding a model: pick the real HF repo, list the actual basenames you
want copied locally, declare which capability/tier it serves. Done.

If you don't know the basenames, either look at the HF page or run:
    curl -s https://huggingface.co/api/models/<repo>/tree/main \\
      | python -c "import json,sys; [print(f['path']) for f in json.load(sys.stdin) if f['type']=='file']"
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from core.paths import models_dir


# ── Capability + tier constants ──────────────────────────────────────────────

CAP_ASR = "asr"
CAP_TTS = "tts"
CAP_LLM = "llm"
CAP_VAD = "vad"

TIER_FIRST       = "first"
TIER_RECOMMENDED = "recommended"
TIER_PREMIUM     = "premium"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display_name: str
    capability: str
    tier: str
    target_subdir: str         # under models_dir(), e.g. "sherpa/whisper-small"
    description: str
    repo: str                  # HF repo, e.g. "csukuangfj/sherpa-onnx-whisper-small"
    revision: str              # usually "main"
    filenames: tuple[str, ...] # basenames inside the repo to install
    notes: str = ""

    def target_dir(self) -> str:
        return os.path.join(models_dir(), *self.target_subdir.split("/"))

    def file_path(self, basename: str) -> str:
        return os.path.join(self.target_dir(), basename)


# ── Catalog ──────────────────────────────────────────────────────────────────
# Repos verified to exist 2026-05-10 via HF API. Update if upstream renames.

CATALOG: dict[str, ModelSpec] = {
    # ── ASR ──────────────────────────────────────────────────────────────────
    "sherpa-whisper-small": ModelSpec(
        id="sherpa-whisper-small",
        display_name="Whisper small (sherpa-onnx int8)",
        capability=CAP_ASR,
        tier=TIER_FIRST,
        target_subdir="sherpa/whisper-small",
        description=(
            "Multilingual ASR for the first-launch tier. ~360 MB total. "
            "Sentence-level timestamps; words[] empty (stock int8 export "
            "lacks cross-attention)."
        ),
        repo="csukuangfj/sherpa-onnx-whisper-small",
        revision="main",
        filenames=(
            "small-encoder.int8.onnx",
            "small-decoder.int8.onnx",
            "small-tokens.txt",
        ),
    ),

    "sherpa-whisper-turbo": ModelSpec(
        id="sherpa-whisper-turbo",
        display_name="Whisper turbo (sherpa-onnx int8)",
        capability=CAP_ASR,
        tier=TIER_RECOMMENDED,
        target_subdir="sherpa/whisper-turbo",
        description=(
            "Recommended-tier ASR. ~1.0 GB. Whisper large-v3-turbo distilled; "
            "near-real-time on 4060, quality close to large-v3."
        ),
        repo="csukuangfj/sherpa-onnx-whisper-turbo",
        revision="main",
        filenames=(
            "turbo-encoder.int8.onnx",
            "turbo-decoder.int8.onnx",
            "turbo-tokens.txt",
        ),
    ),

    # ── LLM (translation) ────────────────────────────────────────────────────
    # No official Qwen org GGUF for Qwen3; community ports are the source.
    # Unsloth's quants are widely used and tested.
    "qwen3-1.7b-q4_k_m": ModelSpec(
        id="qwen3-1.7b-q4_k_m",
        display_name="Qwen3 1.7B (Q4_K_M GGUF, unsloth)",
        capability=CAP_LLM,
        tier=TIER_FIRST,
        target_subdir="llama",
        description=(
            "First-launch translation LLM. ~1.1 GB. Quality good enough "
            "for everyday subtitle translation; ~30+ tok/s on CPU."
        ),
        repo="unsloth/Qwen3-1.7B-GGUF",
        revision="main",
        filenames=("Qwen3-1.7B-Q4_K_M.gguf",),
        notes=(
            "After download, in AI Console pick LlamaCpp → Refresh Models "
            "and select Qwen3-1.7B-Q4_K_M.gguf."
        ),
    ),

    "qwen3-8b-q4_k_m": ModelSpec(
        id="qwen3-8b-q4_k_m",
        display_name="Qwen3 8B (Q4_K_M GGUF, unsloth)",
        capability=CAP_LLM,
        tier=TIER_RECOMMENDED,
        target_subdir="llama",
        description=(
            "Recommended-tier translation LLM. ~5 GB. Markedly better "
            "quality; needs ~6 GB VRAM with GPU offload, ~5 tok/s on CPU."
        ),
        repo="unsloth/Qwen3-8B-GGUF",
        revision="main",
        filenames=("Qwen3-8B-Q4_K_M.gguf",),
    ),

    # ── VAD ──────────────────────────────────────────────────────────────────
    # snakers4/silero-vad on HF is gated — use deepghs's mirror of the .onnx.
    "silero-vad": ModelSpec(
        id="silero-vad",
        display_name="Silero VAD",
        capability=CAP_VAD,
        tier=TIER_FIRST,
        target_subdir="sherpa/silero-vad",
        description=(
            "Voice-activity detection. ~2 MB. Trims silence and suppresses "
            "Whisper hallucinations on long inputs."
        ),
        repo="deepghs/silero-vad-onnx",
        revision="main",
        filenames=("silero_vad.onnx",),
    ),
}


# ── Lookup helpers ───────────────────────────────────────────────────────────

def get(model_id: str) -> ModelSpec:
    return CATALOG[model_id]


def by_capability(cap: str) -> list[ModelSpec]:
    order = {TIER_FIRST: 0, TIER_RECOMMENDED: 1, TIER_PREMIUM: 2}
    items = [s for s in CATALOG.values() if s.capability == cap]
    items.sort(key=lambda s: (order.get(s.tier, 99), s.display_name))
    return items


def by_tier(tier: str) -> list[ModelSpec]:
    cap_order = {CAP_VAD: 0, CAP_ASR: 1, CAP_TTS: 2, CAP_LLM: 3}
    items = [s for s in CATALOG.values() if s.tier == tier]
    items.sort(key=lambda s: (cap_order.get(s.capability, 99), s.display_name))
    return items
