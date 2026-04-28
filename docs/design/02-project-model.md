# Project 模型

## 核心概念

**Project = 文件夹**，与 VS Code 相同：
- 打开任意文件夹即为打开工程
- 元数据写入隐藏子目录 `.videocraft/project.json`（仿 VSCode 的 `.vscode/`），首次打开自动生成
- 若仍存在旧版本的根级 `videocraft.json`，`Project.open()` 会一次性把内容搬入 `.videocraft/project.json` 并删除旧文件
- 文件夹内其他文件由 Sidebar 浏览（`.videocraft/` 在 Sidebar 中隐藏）
- 拷贝文件夹 = 转移整个工程

---

## .videocraft/project.json 结构

### 当前版本（v1）

最小结构，只作标识：

```json
{
  "version": 1,
  "created": "2026-04-03"
}
```

### 未来扩展方向（不强制，按需添加）

```json
{
  "version": 2,
  "created": "2026-04-03",
  "last_opened": "2026-04-10",
  "source": "source.mp4",
  "language": { "from": "en", "to": "zh" },
  "tier": "standard"
}
```

---

## 版本升级策略

**原则：只加字段，不删字段**（向前兼容）

```python
CURRENT_VERSION = 1

MIGRATIONS = {
    # 1: migrate_v1_to_v2,   # 未来添加
}

def load_and_migrate(data: dict) -> dict:
    version = data.get("version", 1)
    while version < CURRENT_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
    data["version"] = CURRENT_VERSION
    return data
```

**读取时**：缺字段用 `.get(key, default)`，从不因字段缺失报错。

---

## project.py API

```python
class Project:
    folder: str          # 文件夹绝对路径
    data: dict           # .videocraft/project.json 内容

    MARKER_DIR    = ".videocraft"
    MARKER_FILE   = "project.json"
    LEGACY_MARKER = "videocraft.json"   # pre-2026-04-末 layout

    @staticmethod
    def open(folder_path: str) -> "Project"
    # 打开文件夹：迁移遗留的根级 videocraft.json（如有）→ 读
    # .videocraft/project.json（不存在则自动创建 v1 最小内容）

    def get_files(self) -> list[dict]
    # 返回文件夹内文件列表（隐藏 .videocraft/ 目录），格式：
    # [{"name": "video.mp4", "path": "...", "ext": ".mp4"}, ...]

    def save(self)
    # 写回 .videocraft/project.json（自动 mkdir -p）

# 最近工程（存 ~/.videocraft/recent.json，最多保留 10 条）
def get_recent_projects() -> list[str]
def add_recent_project(path: str)
```

---

## Sidebar 文件图标映射

| 扩展名 | 显示前缀 |
|--------|---------|
| .mp4 .mkv .avi .mov | 🎬 |
| .srt .ass .vtt | 📄 |
| .mp3 .wav .aac .m4a | 🎵 |
| .json | ⚙️ |
| 文件夹 | 📁 |
| 其他 | 📎 |
