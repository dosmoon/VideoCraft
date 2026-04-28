"""
project.py - VideoCraft Project 模型

Project = 文件夹。打开任意文件夹即为打开工程，元数据写入隐藏子目录
`.videocraft/project.json`（仿 VSCode 的 `.vscode/`，避免与素材文件混在一起）。
旧版本的 `<folder>/videocraft.json` 在 open() 时自动迁入新位置并删除。
"""

import json
import os
from datetime import date

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
    # New layout: <folder>/.videocraft/project.json (hidden, like VSCode's .vscode/)
    MARKER_DIR  = ".videocraft"
    MARKER_FILE = "project.json"
    # Pre-2026-04 layout: <folder>/videocraft.json. open() migrates if found.
    LEGACY_MARKER = "videocraft.json"

    def __init__(self, folder: str, data: dict):
        self.folder = os.path.abspath(folder)
        self.data   = data

    # -- 工厂方法 ---------------------------------------------------------------

    @staticmethod
    def _marker_path(folder: str) -> str:
        return os.path.join(folder, Project.MARKER_DIR, Project.MARKER_FILE)

    @staticmethod
    def open(folder_path: str) -> "Project":
        """打开文件夹作为工程。若无 .videocraft/project.json，自动创建。
        遗留的根级 videocraft.json 会被一次性搬入 .videocraft/project.json。
        """
        folder = os.path.abspath(folder_path)
        new_path = Project._marker_path(folder)
        legacy_path = os.path.join(folder, Project.LEGACY_MARKER)

        # One-shot migration from the old root-level layout
        if os.path.exists(legacy_path) and not os.path.exists(new_path):
            try:
                with open(legacy_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                with open(new_path, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
                os.remove(legacy_path)
            except (json.JSONDecodeError, OSError):
                # Best-effort: fall through to normal load/default-create.
                pass

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
    config_dir = os.path.join(os.path.expanduser("~"), ".videocraft")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "recent.json")

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
