"""
operations.py - Operation Registry

将文件类型映射到可用操作。
- "quick" 操作：调用 core 层函数，在后台线程执行，进度反映到状态栏
- "tool"  操作：打开完整工具 Toplevel，可预填文件路径
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from core import srt_ops, video_ops


# ── Operation 定义 ────────────────────────────────────────────────────────────

@dataclass
class Operation:
    label: str
    handler: str                        # "quick" | "tool" | "common"
    file_types: list                    # 扩展名列表，["*"] 表示全部文件
    func: Optional[Callable] = None    # quick/common 模式：core 函数
    tool_key: Optional[str] = None     # tool 模式：TOOL_MAP key
    separator_before: bool = False     # 在此项前加分隔线


# ── 通用操作函数 ──────────────────────────────────────────────────────────────

def _show_in_explorer(file_path: str, **kwargs) -> str:
    """在资源管理器中高亮显示文件。"""
    subprocess.Popen(["explorer", "/select,", os.path.normpath(file_path)])
    return ""

def _copy_path(file_path: str, **kwargs) -> str:
    """复制文件路径到剪贴板。"""
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(file_path)
        r.update()
        r.after(500, r.destroy)
        r.mainloop()
    except Exception:
        pass
    return ""


# ── 注册表 ────────────────────────────────────────────────────────────────────

REGISTRY: list[Operation] = [
    # ── 视频文件 ──
    Operation("提取 MP3",
              "quick", [".mp4", ".mkv", ".avi", ".mov", ".webm"],
              func=video_ops.extract_mp3),
    Operation("调整音量...",
              "tool",  [".mp4", ".mkv", ".avi", ".mov", ".webm"],
              tool_key="adjust-volume"),
    Operation("语音转字幕...",
              "tool",  [".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav"],
              tool_key="speech2text"),
    Operation("分段工作台...",
              "tool",  [".mp4", ".mkv", ".avi", ".mov"],
              tool_key="split-workbench"),

    # ── SRT 文件 ──
    Operation("提取纯文本 (.txt)",
              "quick", [".srt"],
              func=srt_ops.extract_text),
    Operation("翻译字幕...",
              "tool",  [".srt"],
              tool_key="translate"),

    # ── 音频文件 ──
    Operation("语音转字幕...",
              "tool",  [".mp3", ".wav", ".aac", ".m4a"],
              tool_key="speech2text"),

    # ── 通用操作（所有文件） ──
    Operation("在资源管理器中显示",
              "common", ["*"],
              func=_show_in_explorer,
              separator_before=True),
    Operation("复制文件路径",
              "common", ["*"],
              func=_copy_path),
]


def get_operations(file_path: str) -> list[Operation]:
    """返回该文件适用的操作列表（不含 separator_before="*only" 的通用项）。"""
    ext = os.path.splitext(file_path)[1].lower()
    return [op for op in REGISTRY
            if "*" in op.file_types or ext in op.file_types]
