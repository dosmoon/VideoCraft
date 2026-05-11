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
                               # (ignored when download_all=True)
    notes: str = ""
    # Hardware target. UI surfaces this as a badge so the user picks the
    # right variant for their machine. Two specs may share target_subdir
    # (their on-disk filenames don't collide) — provider auto-selects at
    # load time. Values: "cpu" | "gpu" | "both".
    recommended_for: str = "both"
    # When True, the resolver fetches the full repo tree and downloads
    # every file (preserving subdirectory structure). Used for models
    # like sherpa Kokoro TTS that ship hundreds of small espeak-ng /
    # jieba dict files alongside the ONNX weights — listing them
    # individually in `filenames` would be tedious and brittle.
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
    # ── ASR ──────────────────────────────────────────────────────────────────
    # Each Whisper size ships in two variants in the same upstream repo:
    #   int8 — quantized, ~3× smaller, fast on CPU. ONNX Runtime CUDA EP
    #          has only partial int8 op coverage so GPU users see most ops
    #          fall back to CPU silently → don't pick this for GPU.
    #   fp32 — full precision. Bigger download, but full GPU acceleration.
    # Both variants share target_subdir; their filenames don't collide so
    # both can sit on disk and the sherpa provider auto-picks at load time.
    "sherpa-whisper-small-int8": ModelSpec(
        id="sherpa-whisper-small-int8",
        display_name="Whisper small — int8 (CPU)",
        capability=CAP_ASR,
        tier=TIER_FIRST,
        target_subdir="sherpa/whisper-small",
        description=(
            "Multilingual ASR for first launch. ~360 MB. Quantized int8 "
            "for CPU inference; sentence-level timestamps; words[] empty."
        ),
        repo="csukuangfj/sherpa-onnx-whisper-small",
        revision="main",
        filenames=(
            "small-encoder.int8.onnx",
            "small-decoder.int8.onnx",
            "small-tokens.txt",
        ),
        recommended_for="cpu",
    ),

    "sherpa-whisper-small-fp32": ModelSpec(
        id="sherpa-whisper-small-fp32",
        display_name="Whisper small — fp32 (GPU)",
        capability=CAP_ASR,
        tier=TIER_FIRST,
        target_subdir="sherpa/whisper-small",
        description=(
            "Same model, full precision. ~970 MB. Required for real GPU "
            "speed-up — the int8 variant runs ~half on CPU even with "
            "CUDA EP loaded due to partial op coverage."
        ),
        repo="csukuangfj/sherpa-onnx-whisper-small",
        revision="main",
        filenames=(
            "small-encoder.onnx",
            "small-decoder.onnx",
            "small-tokens.txt",
        ),
        recommended_for="gpu",
    ),

    "sherpa-whisper-turbo-int8": ModelSpec(
        id="sherpa-whisper-turbo-int8",
        display_name="Whisper turbo — int8 (CPU)",
        capability=CAP_ASR,
        tier=TIER_RECOMMENDED,
        target_subdir="sherpa/whisper-turbo",
        description=(
            "Whisper large-v3-turbo distilled, int8 quantized. ~1.0 GB. "
            "Near-real-time on CPU; choose fp32 variant if you have GPU."
        ),
        repo="csukuangfj/sherpa-onnx-whisper-turbo",
        revision="main",
        filenames=(
            "turbo-encoder.int8.onnx",
            "turbo-decoder.int8.onnx",
            "turbo-tokens.txt",
        ),
        recommended_for="cpu",
    ),

    # ── faster-whisper (CTranslate2) — preferred for GPU users ───────────────
    # 30-40× RTF on a 4060 vs sherpa-onnx Whisper's ~10× ceiling. Each
    # entry is a directory of (config.json, model.bin, tokenizer.json,
    # vocabulary.{txt,json}). The provider auto-picks float16 on CUDA
    # and int8 on CPU at runtime, so one model covers both devices.
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

    "sherpa-whisper-turbo-fp32": ModelSpec(
        id="sherpa-whisper-turbo-fp32",
        display_name="Whisper turbo — fp32 (GPU)",
        capability=CAP_ASR,
        tier=TIER_RECOMMENDED,
        target_subdir="sherpa/whisper-turbo",
        description=(
            "Whisper large-v3-turbo distilled, full precision. ~3 GB. "
            "Real GPU speedup; quality close to large-v3."
        ),
        repo="csukuangfj/sherpa-onnx-whisper-turbo",
        revision="main",
        filenames=(
            "turbo-encoder.onnx",
            "turbo-decoder.onnx",
            "turbo-tokens.txt",
        ),
        recommended_for="gpu",
    ),

    # ── TTS ──────────────────────────────────────────────────────────────────
    # Kokoro (sherpa-onnx) ships hundreds of small espeak-ng phoneme files +
    # jieba dict alongside the ONNX weights. download_all=True pulls the
    # full repo tree instead of listing each file in `filenames`.
    "kokoro-int8-multi-lang-v1_0": ModelSpec(
        id="kokoro-int8-multi-lang-v1_0",
        display_name="Kokoro multi-lang v1.0 — int8 (sherpa-onnx)",
        capability=CAP_TTS,
        tier=TIER_FIRST,
        target_subdir="sherpa-tts/kokoro-int8-multi-lang-v1_0",
        description=(
            "First-launch TTS. ~180 MB. Quantized int8; ~50 voices; "
            "multilingual (English / Chinese / Japanese / Korean / Spanish / "
            "French / Italian / Portuguese / Hindi). CPU-friendly; works on "
            "GPU too via the same wheel."
        ),
        repo="csukuangfj/kokoro-int8-multi-lang-v1_0",
        revision="main",
        filenames=(),               # ignored — download_all=True
        download_all=True,
        recommended_for="both",
    ),

    "kokoro-multi-lang-v1_0": ModelSpec(
        id="kokoro-multi-lang-v1_0",
        display_name="Kokoro multi-lang v1.0 — fp32 (sherpa-onnx)",
        capability=CAP_TTS,
        tier=TIER_RECOMMENDED,
        target_subdir="sherpa-tts/kokoro-multi-lang-v1_0",
        description=(
            "Full-precision Kokoro. ~380 MB. Same voices and languages as "
            "the int8 variant; better quality on GPU at the cost of disk."
        ),
        repo="csukuangfj/kokoro-multi-lang-v1_0",
        revision="main",
        filenames=(),               # ignored — download_all=True
        download_all=True,
        recommended_for="gpu",
    ),

    # MeloTTS (MyShell, MIT) ported to sherpa-onnx by k2-fsa. Higher
    # subjective quality than Kokoro for Chinese; single-speaker. Supports
    # mixed Chinese + English in the same input. Bundled jieba dict +
    # date/number FSTs do prosody-aware text normalization.
    "vits-melo-tts-zh_en": ModelSpec(
        id="vits-melo-tts-zh_en",
        display_name="MeloTTS Chinese+English (VITS, sherpa-onnx)",
        capability=CAP_TTS,
        tier=TIER_FIRST,
        target_subdir="sherpa-tts/vits-melo-tts-zh_en",
        description=(
            "MyShell MeloTTS Chinese+English, ~233 MB. Single Chinese voice "
            "with mixed-language support. Best Chinese TTS quality available "
            "via the no-torch sherpa-onnx pipeline."
        ),
        repo="csukuangfj/vits-melo-tts-zh_en",
        revision="main",
        filenames=(),               # ignored — download_all=True
        download_all=True,
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
