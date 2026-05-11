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
    target_subdir: str         # under models_dir(), e.g. "faster-whisper/faster-whisper-small"
    description: str
    repo: str                  # HF repo, e.g. "Systran/faster-whisper-small"
    revision: str              # usually "main"
    filenames: tuple[str, ...] # basenames inside the repo to install
                               # (ignored when download_all=True)
    notes: str = ""
    # Hardware target. UI surfaces this as a badge so the user picks the
    # right variant for their machine. Two specs may share target_subdir
    # (their on-disk filenames don't collide) — provider auto-selects at
    # load time. Values: "cpu" | "gpu" | "both".
    recommended_for: str = "both"
    # When True, the resolver fetches the full repo tree and downloads
    # every file (preserving subdirectory structure). Useful for repos
    # that ship many small assets (espeak-ng phonemes, jieba dicts, etc.)
    # alongside the main weights.
    download_all: bool = False

    def target_dir(self) -> str:
        return os.path.join(models_dir(), *self.target_subdir.split("/"))

    def file_path(self, relpath: str) -> str:
        # relpath may contain subdirectory separators ("espeak-ng-data/lang/...")
        # — os.path.join handles that fine.
        return os.path.join(self.target_dir(), relpath)


# ── Catalog ──────────────────────────────────────────────────────────────────
# Repos verified to exist 2026-05-10 via HF API. Update if upstream renames.

CATALOG: dict[str, ModelSpec] = {
    # ── ASR (faster-whisper / CTranslate2) ───────────────────────────────────
    # Each entry is a directory of (config.json, model.bin, tokenizer.json,
    # vocabulary.{txt,json}). The provider auto-picks float16 on CUDA and
    # int8 on CPU at runtime, so one model covers both devices.
    "faster-whisper-small": ModelSpec(
        id="faster-whisper-small",
        display_name="faster-whisper small (CT2, GPU+CPU)",
        capability=CAP_ASR,
        tier=TIER_FIRST,
        target_subdir="faster-whisper/faster-whisper-small",
        description=(
            "Fast multilingual ASR. ~480 MB. CTranslate2 backend with "
            "batched GPU decode — real 30× RTF on 4060 fp16. CPU users "
            "get int8 quantization at runtime, ~10× RTF."
        ),
        repo="Systran/faster-whisper-small",
        revision="main",
        filenames=("config.json", "model.bin", "tokenizer.json",
                   "vocabulary.txt"),
        recommended_for="both",
    ),

    "faster-whisper-large-v3-turbo": ModelSpec(
        id="faster-whisper-large-v3-turbo",
        display_name="faster-whisper large-v3-turbo (CT2)",
        capability=CAP_ASR,
        tier=TIER_RECOMMENDED,
        target_subdir="faster-whisper/faster-whisper-large-v3-turbo",
        description=(
            "Whisper large-v3-turbo distilled, CT2-converted by deepdml. "
            "~1.6 GB. Real-time on 4060 fp16; quality close to large-v3."
        ),
        repo="deepdml/faster-whisper-large-v3-turbo-ct2",
        revision="main",
        filenames=("config.json", "model.bin", "preprocessor_config.json",
                   "tokenizer.json", "vocabulary.json"),
        recommended_for="both",
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

    # VAD: faster-whisper bundles its own silero VAD weights (used via
    # vad_filter=True), so we no longer ship a separate VAD entry.
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
