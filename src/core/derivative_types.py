"""Registry of supported derivative types.

A derivative = one downstream artifact produced from the project's
source video. Each type has its own workbench tool and its own folder
under <project>/derivatives/<type>/<instance>/.

Single source of truth for:
  - human-readable display name (Chinese + English)
  - which Hub tool to open for it
  - default instance name + auto-increment naming pattern
  - single-instance vs multi-instance UX hint

Adding a new type (e.g. summary / commentary / dialogue / theater)
means appending one entry here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivativeType:
    type_name: str           # folder name under derivatives/, code identifier
    i18n_key: str            # tr() key for the display label
    tool_key: str            # TOOL_MAP entry used to open its workbench
    default_basename: str    # base for auto-increment ("default", "cut", "v")
    single_instance: bool    # True ⇒ menu offers [open existing] vs [new]
    description_zh: str      # subtitle under the type in selection dialog
    description_en: str


# Order matters — used as the canonical display order in dialogs and sidebar.
# AI Clip is intentionally NOT registered during the subtitle-video milestone
# (P4); its workbench code is preserved untouched but unsurfaced. Re-register
# when AI Clip undergoes its own simplification pass.
REGISTRY: list[DerivativeType] = [
    DerivativeType(
        type_name="bilingual_video",
        i18n_key="derivative.subtitle_video",
        tool_key="subtitle",
        default_basename="default",
        single_instance=True,
        description_zh="把源视频和字幕烧录成成片(单语或双语)",
        description_en="Render the source video with burned-in subtitles",
    ),
]

_BY_NAME: dict[str, DerivativeType] = {t.type_name: t for t in REGISTRY}


def get(type_name: str) -> DerivativeType | None:
    """Lookup by type_name. Returns None on unknown."""
    return _BY_NAME.get(type_name)


def all_types() -> list[DerivativeType]:
    """All registered types in display order."""
    return list(REGISTRY)


def display_name(type_name: str) -> str:
    """Translate type_name to its display label via i18n. Falls back to
    the raw type_name if unknown."""
    t = get(type_name)
    if t is None:
        return type_name
    from i18n import tr
    return tr(t.i18n_key)


def suggest_instance_name(type_name: str, existing: list[str]) -> str:
    """Suggest the next instance name given the existing ones.

    For single_instance types: 'default' if free, else 'v2', 'v3', ...
    For multi-instance types:  '<basename>-1', '<basename>-2', ... (the
        first unused number).
    """
    t = get(type_name)
    if t is None:
        # Unknown type — generic counter
        return _next_numbered("v", existing)

    existing_set = set(existing)
    if t.single_instance:
        if "default" not in existing_set:
            return "default"
        return _next_numbered("v", existing)
    return _next_numbered(t.default_basename, existing, sep="-")


def _next_numbered(stem: str, existing: list[str], sep: str = "") -> str:
    """Return f'{stem}{sep}{n}' for the smallest n>=1 not in existing."""
    s = set(existing)
    n = 1
    while True:
        candidate = f"{stem}{sep}{n}" if sep else f"{stem}{n}"
        if candidate not in s:
            return candidate
        n += 1


if __name__ == "__main__":
    # Smoke
    assert suggest_instance_name("bilingual_video", []) == "default"
    assert suggest_instance_name("bilingual_video", ["default"]) == "v1"
    assert suggest_instance_name("bilingual_video", ["default", "v1"]) == "v2"
    assert get("bilingual_video") is not None
    assert get("ai_clip") is None  # not registered during P4 milestone
    assert get("nonexistent") is None
    print("derivative_types smoke OK")
