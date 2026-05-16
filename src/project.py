"""
project.py - VideoCraft Project model.

Project = a folder with metadata in `.videocraft/project.json` and a
symmetric pair of plugin containers (ADR-0005):

  <project>/
    .videocraft/project.json     ← serialized ProjectMeta
    .videocraft/background.json
    materials/<type>/<instance>/ ← N material instances (e.g. news_video/news-1/)
    creations/<type>/<instance>/ ← N creation instances (e.g. news_desk/default/)

The old `source/` and `subtitles/` direct-children layout is retired
(ADR-0005). All source video / SRT / analysis data now lives inside a
material instance's directory.

Filenames used inside instances are defined by the plugin
schemas (materials/news_video/schema.py defines what 'source/video.mp4'
and 'subtitles/<iso>.srt' mean for that material type). Project itself
is plugin-agnostic.
"""

import json
import os
from datetime import date

from core.project_schema import ProjectMeta, Source, ClipRange, now_iso

# Project-level (cross-instance) metadata filename only.
BACKGROUND_FILENAME = "background.json"


def _create_instance(inst_dir: str, instance_name: str,
                     initial_config: dict | None,
                     config_filename: str) -> str:
    """Shared instance-directory creation for materials + creations.

    Validates instance_name against filesystem rules. Raises
    FileExistsError if the directory already exists, ValueError on
    bad name. Returns the absolute path to the new instance folder.
    """
    if (not instance_name
            or instance_name != instance_name.strip()
            or any(c in instance_name for c in r'\/:*?"<>|')
            or instance_name.startswith(".")):
        raise ValueError(f"Invalid instance name: {instance_name!r}")
    if len(instance_name) > 64:
        raise ValueError(f"Instance name too long: {len(instance_name)} > 64")
    if os.path.exists(inst_dir):
        raise FileExistsError(f"Instance directory already exists: {inst_dir}")
    os.makedirs(inst_dir, exist_ok=True)
    if initial_config is not None:
        config_path = os.path.join(inst_dir, config_filename)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(initial_config, f, ensure_ascii=False, indent=2)
    return inst_dir

# ── 版本迁移 ──────────────────────────────────────────────────────────────────

CURRENT_VERSION = 1

MIGRATIONS = {
    # 示例：1: _migrate_v1_to_v2,
}

def _load_and_migrate(data: dict) -> dict:
    version = data.get("version", 1)
    while version < CURRENT_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
    data["version"] = CURRENT_VERSION
    return data


# ── 文件图标映射 ──────────────────────────────────────────────────────────────

_ICONS = {
    frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm"}): "🎬",
    frozenset({".srt", ".ass", ".vtt"}):                  "📄",
    frozenset({".mp3", ".wav", ".aac", ".m4a", ".flac"}): "🎵",
    frozenset({".json"}):                                  "⚙️",
}

def file_icon(name: str, is_dir: bool = False) -> str:
    if is_dir:
        return "📁"
    ext = os.path.splitext(name)[1].lower()
    for exts, icon in _ICONS.items():
        if ext in exts:
            return icon
    return "📎"

# ── Project 类 ────────────────────────────────────────────────────────────────

class Project:
    MARKER_DIR  = ".videocraft"
    MARKER_FILE = "project.json"

    MATERIALS_DIR_NAME = "materials"
    CREATIONS_DIR_NAME = "creations"

    def __init__(self, folder: str, data: dict):
        self.folder = os.path.abspath(folder)
        self.data   = data

    # -- 工厂方法 ---------------------------------------------------------------

    @staticmethod
    def _marker_path(folder: str) -> str:
        return os.path.join(folder, Project.MARKER_DIR, Project.MARKER_FILE)

    @staticmethod
    def open(folder_path: str) -> "Project":
        """Open folder as a project. Creates .videocraft/project.json if absent."""
        folder = os.path.abspath(folder_path)
        new_path = Project._marker_path(folder)

        if os.path.exists(new_path):
            try:
                with open(new_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                data = _load_and_migrate(raw)
            except (json.JSONDecodeError, KeyError):
                data = Project._default_data()
        else:
            data = Project._default_data()

        project = Project(folder, data)
        project.save()   # ensure file written (new project or post-migration)
        return project

    @staticmethod
    def _default_data() -> dict:
        return {
            "version": CURRENT_VERSION,
            "created": date.today().isoformat(),
        }

    # -- New-model factory (2026-05-11) ----------------------------------------

    @staticmethod
    def new(parent_dir: str, name: str, source: Source | None = None) -> "Project":
        """Create a fresh new-model project under parent_dir/name.

        Builds the canonical directory skeleton and writes a ProjectMeta
        to .videocraft/project.json. Source defaults to an empty
        placeholder; the sidebar's Source row drives acquisition later
        and back-fills the meta. Caller may pass a populated Source if
        creating a project with a known source upfront.

        Raises FileExistsError if parent_dir/name already exists.
        Raises ValueError if name is empty or contains illegal chars.
        Raises OSError if parent_dir is not writable.
        """
        if source is None:
            source = Source()
        if not name or any(c in name for c in r'\/:*?"<>|') or name != name.strip():
            raise ValueError(f"Invalid project name: {name!r}")

        folder = os.path.join(os.path.abspath(parent_dir), name)
        if os.path.exists(folder):
            raise FileExistsError(f"Project folder already exists: {folder}")

        # Create skeleton dirs. Materials / creations subdirs are
        # created on demand when the first instance is registered.
        os.makedirs(os.path.join(folder, Project.MARKER_DIR), exist_ok=True)
        os.makedirs(os.path.join(folder, Project.MATERIALS_DIR_NAME), exist_ok=True)
        os.makedirs(os.path.join(folder, Project.CREATIONS_DIR_NAME), exist_ok=True)

        meta = ProjectMeta(name=name, created_at=now_iso(), source=source)

        # data dict keeps both old fields (for any legacy reader still around)
        # and new schema. Old `version` field stays as-is; new schema lives
        # under the dict produced by meta.to_dict() — we merge them so dict
        # access from old paths keeps working without breaking new readers.
        data = {**Project._default_data(), **meta.to_dict()}

        project = Project(folder, data)
        project.save()
        return project

    # -- New-model accessors ---------------------------------------------------

    @property
    def meta(self) -> ProjectMeta:
        """Parsed ProjectMeta view of self.data. Read-only snapshot —
        mutate via update_meta() so changes are persisted."""
        return ProjectMeta.from_dict(self.data)

    def update_meta(self, meta: ProjectMeta) -> None:
        """Replace project metadata and persist."""
        self.data = {**self.data, **meta.to_dict()}
        self.save()

    @property
    def videocraft_dir(self) -> str:
        return os.path.join(self.folder, Project.MARKER_DIR)

    @property
    def background_path(self) -> str:
        return os.path.join(self.videocraft_dir, BACKGROUND_FILENAME)

    # ── Materials (plugin instance container) ─────────────────────────────────

    @property
    def materials_dir(self) -> str:
        return os.path.join(self.folder, Project.MATERIALS_DIR_NAME)

    def material_type_dir(self, type_name: str) -> str:
        return os.path.join(self.materials_dir, type_name)

    def material_instance_dir(self, type_name: str, instance_name: str) -> str:
        """Returns <project>/materials/<type>/<instance>/, NOT created."""
        return os.path.join(self.materials_dir, type_name, instance_name)

    def list_material_types(self) -> list[str]:
        if not os.path.isdir(self.materials_dir):
            return []
        try:
            return sorted(
                n for n in os.listdir(self.materials_dir)
                if os.path.isdir(os.path.join(self.materials_dir, n))
            )
        except OSError:
            return []

    def list_material_instances(self, type_name: str) -> list[str]:
        type_dir = self.material_type_dir(type_name)
        if not os.path.isdir(type_dir):
            return []
        try:
            return sorted(
                n for n in os.listdir(type_dir)
                if os.path.isdir(os.path.join(type_dir, n))
            )
        except OSError:
            return []

    def list_materials(self) -> dict[str, list[str]]:
        return {t: self.list_material_instances(t) for t in self.list_material_types()}

    def create_material_instance(
        self,
        type_name: str,
        instance_name: str,
        initial_config: dict | None = None,
        config_filename: str = "instance.json",
    ) -> str:
        return _create_instance(
            self.material_instance_dir(type_name, instance_name),
            instance_name, initial_config, config_filename,
        )

    # ── Creations (plugin instance container; renamed from derivatives) ───────

    @property
    def creations_dir(self) -> str:
        return os.path.join(self.folder, Project.CREATIONS_DIR_NAME)

    def creation_type_dir(self, type_name: str) -> str:
        return os.path.join(self.creations_dir, type_name)

    def creation_instance_dir(self, type_name: str, instance_name: str) -> str:
        """Returns <project>/creations/<type>/<instance>/, NOT created."""
        return os.path.join(self.creations_dir, type_name, instance_name)

    def list_creation_types(self) -> list[str]:
        if not os.path.isdir(self.creations_dir):
            return []
        try:
            return sorted(
                n for n in os.listdir(self.creations_dir)
                if os.path.isdir(os.path.join(self.creations_dir, n))
            )
        except OSError:
            return []

    def list_creation_instances(self, type_name: str) -> list[str]:
        type_dir = self.creation_type_dir(type_name)
        if not os.path.isdir(type_dir):
            return []
        try:
            return sorted(
                n for n in os.listdir(type_dir)
                if os.path.isdir(os.path.join(type_dir, n))
            )
        except OSError:
            return []

    def list_creations(self) -> dict[str, list[str]]:
        return {t: self.list_creation_instances(t) for t in self.list_creation_types()}

    def create_creation_instance(
        self,
        type_name: str,
        instance_name: str,
        initial_config: dict | None = None,
        config_filename: str = "config.json",
    ) -> str:
        return _create_instance(
            self.creation_instance_dir(type_name, instance_name),
            instance_name, initial_config, config_filename,
        )

    # -- 文件列表 ---------------------------------------------------------------

    def get_files(self) -> list:
        """
        返回工程文件夹内的条目列表（单层，不递归）。
        格式：[{"name": str, "path": str, "ext": str, "icon": str, "is_dir": bool}]
        隐藏 `.videocraft/` 元数据目录（用户素材列表里看不到它）。
        """
        entries = []
        try:
            names = sorted(os.listdir(self.folder), key=lambda s: s.lower())
        except OSError:
            return []

        for name in names:
            if name == Project.MARKER_DIR:
                continue
            full = os.path.join(self.folder, name)
            is_dir = os.path.isdir(full)
            ext = "" if is_dir else os.path.splitext(name)[1].lower()
            entries.append({
                "name":   name,
                "path":   full,
                "ext":    ext,
                "icon":   file_icon(name, is_dir),
                "is_dir": is_dir,
            })

        # Directories first, then files, both alphabetical.
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return entries

    # -- 持久化 -----------------------------------------------------------------

    def save(self):
        """将 data 写回 .videocraft/project.json。"""
        path = Project._marker_path(self.folder)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # -- 便捷属性 ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return os.path.basename(self.folder)

# ── 最近工程 ──────────────────────────────────────────────────────────────────

_RECENT_MAX = 10

def _recent_path() -> str:
    from core import user_data
    return user_data.path("recent.json")

def get_recent_projects() -> list:
    """返回最近工程路径列表（最新在前）。"""
    path = _recent_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 过滤掉已不存在的文件夹
        return [p for p in data.get("recent", []) if os.path.isdir(p)]
    except (json.JSONDecodeError, OSError):
        return []

def add_recent_project(folder_path: str):
    """将 folder_path 加入最近列表（去重，保留最新，最多 _RECENT_MAX 条）。"""
    folder = os.path.abspath(folder_path)
    recents = get_recent_projects()
    recents = [p for p in recents if p != folder]   # 去重
    recents.insert(0, folder)
    recents = recents[:_RECENT_MAX]
    path = _recent_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"recent": recents}, f, ensure_ascii=False, indent=2)
