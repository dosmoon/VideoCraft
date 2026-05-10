"""Declarative catalog of embedded-AI models.

Each ModelSpec is a single user-installable bundle (one or more files
that together make a usable model). Sources are ranked by preference:
ModelScope first (China-friendly), then hf-mirror, then HuggingFace
official. The downloader walks the list on failure.

Adding a new model: append to CATALOG below. No JSON, no schema —
strong typing keeps consumers honest. See tech-selection-embedded-ai.md
§6 for tier rationale.

sha256 is optional per file. When present the downloader verifies
streaming and re-downloads on mismatch. When None, size-only check is
the integrity bar (acceptable for v1; tightening later just means
filling in hashes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os

from core.paths import models_dir


# ── Capability + tier constants ──────────────────────────────────────────────

CAP_ASR = "asr"
CAP_TTS = "tts"
CAP_LLM = "llm"
CAP_VAD = "vad"

TIER_FIRST       = "first"        # First-launch — minimum to demo end-to-end
TIER_RECOMMENDED = "recommended"  # 4060 Laptop baseline
TIER_PREMIUM     = "premium"      # User opts in for top quality


@dataclass(frozen=True)
class ModelFile:
    """One file inside a model bundle."""
    relpath: str               # path relative to spec.target_subdir
    size_bytes: int            # approximate; used for progress + disk preflight
    sources: tuple[str, ...]   # full URLs in preference order
    sha256: str | None = None  # optional integrity check


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display_name: str
    capability: str            # CAP_*
    tier: str                  # TIER_*
    target_subdir: str         # under models_dir(), e.g. "sherpa/whisper-small"
    description: str
    files: tuple[ModelFile, ...]
    notes: str = ""            # shown in UI tooltip

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)

    def target_dir(self) -> str:
        return os.path.join(models_dir(), *self.target_subdir.split("/"))

    def file_path(self, relpath: str) -> str:
        return os.path.join(self.target_dir(), relpath)


# ── URL helpers ──────────────────────────────────────────────────────────────

def _hf(repo: str, file: str, *, revision: str = "main") -> tuple[str, str, str]:
    """Return (HF, hf-mirror, ModelScope-best-effort) URL trio.

    HF official is the source of truth. hf-mirror.com is a same-scheme
    drop-in (just hostname swap). ModelScope mirrors many but not all HF
    repos; when the slug matches we point there too — failure just falls
    through to HF.
    """
    # HF official
    hf = f"https://huggingface.co/{repo}/resolve/{revision}/{file}"
    # hf-mirror — identical path
    mirror = f"https://hf-mirror.com/{repo}/resolve/{revision}/{file}"
    # ModelScope best-effort (same org/repo slug; will 404 if not mirrored)
    ms_rev = "master" if revision == "main" else revision
    ms = (f"https://modelscope.cn/api/v1/models/{repo}/repo"
          f"?Revision={ms_rev}&FilePath={file}")
    # ModelScope first (faster in CN), mirror, HF official last.
    return (ms, mirror, hf)


# ── Catalog ──────────────────────────────────────────────────────────────────
# Sizes are approximate (rounded MB); used only for progress display + disk
# preflight buffer. Slight drift vs actual file size is fine.

CATALOG: dict[str, ModelSpec] = {
    # ── ASR ──────────────────────────────────────────────────────────────────
    "sherpa-whisper-small": ModelSpec(
        id="sherpa-whisper-small",
        display_name="Whisper small (sherpa-onnx int8)",
        capability=CAP_ASR,
        tier=TIER_FIRST,
        target_subdir="sherpa/whisper-small",
        description=(
            "Multilingual ASR for the first-launch tier. ~480 MB total. "
            "Sentence-level timestamps; words[] empty (stock int8 export "
            "lacks cross-attention)."
        ),
        files=(
            # Sizes match the int8 export under csukuangfj's HF repo as of
            # 2026-05; update if upstream re-quantizes. Loose 50%-of-expected
            # check tolerates minor drift without forcing a refetch.
            ModelFile(
                "small-encoder.int8.onnx", 112_000_000,
                _hf("csukuangfj/sherpa-onnx-whisper-small",
                    "small-encoder.int8.onnx"),
            ),
            ModelFile(
                "small-decoder.int8.onnx", 262_000_000,
                _hf("csukuangfj/sherpa-onnx-whisper-small",
                    "small-decoder.int8.onnx"),
            ),
            ModelFile(
                "small-tokens.txt", 800_000,
                _hf("csukuangfj/sherpa-onnx-whisper-small",
                    "small-tokens.txt"),
            ),
        ),
    ),

    "sherpa-whisper-large-v3-turbo": ModelSpec(
        id="sherpa-whisper-large-v3-turbo",
        display_name="Whisper large-v3-turbo (sherpa-onnx int8)",
        capability=CAP_ASR,
        tier=TIER_RECOMMENDED,
        target_subdir="sherpa/whisper-large-v3-turbo",
        description=(
            "Recommended-tier ASR. ~1.6 GB. Near-real-time on 4060; quality "
            "close to large-v3 with much smaller compute footprint."
        ),
        files=(
            ModelFile(
                "large-v3-turbo-encoder.int8.onnx", 1_100_000_000,
                _hf("csukuangfj/sherpa-onnx-whisper-large-v3-turbo",
                    "large-v3-turbo-encoder.int8.onnx"),
            ),
            ModelFile(
                "large-v3-turbo-decoder.int8.onnx", 480_000_000,
                _hf("csukuangfj/sherpa-onnx-whisper-large-v3-turbo",
                    "large-v3-turbo-decoder.int8.onnx"),
            ),
            ModelFile(
                "large-v3-turbo-tokens.txt", 800_000,
                _hf("csukuangfj/sherpa-onnx-whisper-large-v3-turbo",
                    "large-v3-turbo-tokens.txt"),
            ),
        ),
    ),

    # ── LLM (translation) ────────────────────────────────────────────────────
    "qwen3-1.7b-q4_k_m": ModelSpec(
        id="qwen3-1.7b-q4_k_m",
        display_name="Qwen3 1.7B Instruct (Q4_K_M GGUF)",
        capability=CAP_LLM,
        tier=TIER_FIRST,
        target_subdir="llama",
        description=(
            "First-launch translation LLM. ~1.2 GB. Quality good enough "
            "for everyday subtitle translation; ~30+ tok/s on CPU."
        ),
        files=(
            ModelFile(
                "Qwen3-1.7B-Q4_K_M.gguf", 1_200_000_000,
                _hf("Qwen/Qwen3-1.7B-Instruct-GGUF",
                    "qwen3-1.7b-instruct-q4_k_m.gguf"),
            ),
        ),
        notes=(
            "If the upstream filename changes, edit the URL in catalog.py. "
            "After download, in AI Console pick LlamaCpp → Refresh Models "
            "and select Qwen3-1.7B-Q4_K_M.gguf."
        ),
    ),

    "qwen3-8b-q4_k_m": ModelSpec(
        id="qwen3-8b-q4_k_m",
        display_name="Qwen3 8B Instruct (Q4_K_M GGUF)",
        capability=CAP_LLM,
        tier=TIER_RECOMMENDED,
        target_subdir="llama",
        description=(
            "Recommended-tier translation LLM. ~5 GB. Markedly better "
            "translation quality; needs ~6 GB VRAM with GPU layers, runs "
            "on CPU at ~5 tok/s."
        ),
        files=(
            ModelFile(
                "Qwen3-8B-Q4_K_M.gguf", 4_900_000_000,
                _hf("Qwen/Qwen3-8B-Instruct-GGUF",
                    "qwen3-8b-instruct-q4_k_m.gguf"),
            ),
        ),
    ),

    # ── VAD ──────────────────────────────────────────────────────────────────
    "silero-vad": ModelSpec(
        id="silero-vad",
        display_name="Silero VAD",
        capability=CAP_VAD,
        tier=TIER_FIRST,
        target_subdir="sherpa/silero-vad",
        description=(
            "Voice-activity detection. ~2 MB. Used to trim silence and "
            "suppress Whisper hallucinations on long inputs."
        ),
        files=(
            ModelFile(
                "silero_vad.onnx", 2_300_000,
                _hf("snakers4/silero-vad",
                    "src/silero_vad/data/silero_vad.onnx"),
            ),
        ),
    ),
}


# ── Lookup helpers ───────────────────────────────────────────────────────────

def get(model_id: str) -> ModelSpec:
    """Look up a spec by id. Raises KeyError on miss (intentional — UI
    code asking for an unknown id is a bug, not a runtime condition)."""
    return CATALOG[model_id]


def by_capability(cap: str) -> list[ModelSpec]:
    """All specs for a given capability (CAP_*), sorted: first → recommended → premium."""
    order = {TIER_FIRST: 0, TIER_RECOMMENDED: 1, TIER_PREMIUM: 2}
    items = [s for s in CATALOG.values() if s.capability == cap]
    items.sort(key=lambda s: (order.get(s.tier, 99), s.display_name))
    return items


def by_tier(tier: str) -> list[ModelSpec]:
    """All specs for a given tier (TIER_*), sorted by capability then name."""
    cap_order = {CAP_VAD: 0, CAP_ASR: 1, CAP_TTS: 2, CAP_LLM: 3}
    items = [s for s in CATALOG.values() if s.tier == tier]
    items.sort(key=lambda s: (cap_order.get(s.capability, 99), s.display_name))
    return items
