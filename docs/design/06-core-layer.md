# core 层设计：逻辑/UI 分离

## 设计动机

原有工具文件（VideoTools、SubtitleTool 等）将业务逻辑与 Tkinter UI 混在一起，
无法从 Sidebar 右键直接调用，也无法在不打开完整工具窗口的情况下执行操作。`core/` 层把纯逻辑抽出来供 UI 层和（未来的）Pipeline 层复用。

## 目录结构

```
src/core/
├── __init__.py
├── srt_ops.py        ← SRT 字幕处理（统计 / 分段 / YouTube chapters / AI 精炼）
├── subtitle_ops.py   ← 字幕烧录相关（分割 / 样式构建 / ffmpeg 路径 escape）
├── video_ops.py      ← FFmpeg 视频/音频操作（基础工具函数）
├── segment_model.py  ← 分段模型：Segment dataclass + 加载/保存 subs.txt + 校验
└── video_concat.py   ← 分段切割 / 跨段合并（ffmpeg concat demuxer）
```

## 设计原则

- **无 UI 依赖**：不 import tkinter，不调用 messagebox
- **失败时 raise**：不静默记日志——主路径失败一律抛异常，UI 层 try/except + `self.set_error(msg)`
- **进度通过 callback**：`progress_callback: Callable[[float], None] = None`（百分比 0-100）
- **输出路径可选**：默认在输入文件同目录自动命名

### 错误传播约定（重要）

`core/` 层的工具函数（例如 [video_ops.py](../../src/tools/video/video_tools.py) 里的 `extract_audio_to_mp3` / `adjust_volume` / `convert_mp3_bitrate` / `extract_video_clip`）在 ffmpeg 进程返回非零退出码时统一 **`raise RuntimeError(...)`**。UI 层的调用端负责捕获并通过 `self.set_error()` 翻 Tab 点为红色 + 写底部日志。

```python
# core 层：失败就抛
def extract_audio_to_mp3(...):
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg exit {process.returncode} while extracting...")
    progress_callback(100)
    logger.info(f"提取 MP3 完成 → {os.path.basename(output_mp3)}")

# UI 层：统一捕获并上报
def _work():
    try:
        extract_audio_to_mp3(src, dst, bitrate, _progress_cb)
    except Exception as e:
        self.set_error(f"提取 MP3 失败: {e}")
        return
    self.set_done()
```

旧的 "logger.error 但不 raise" 模式（UI 层无法知道是否失败，Tab 点永远绿）已全部清理。

## 现状

| 模块 | 状态 |
|------|------|
| `core/srt_ops.py` | ✅ 已完成（SRT 解析、统计、YouTube 分段、段落提取、AI 精炼、标题生成；2026-04 末新增 `generate_subtitle_pack()` + `write_subtitle_pack()` + `SUBTITLE_PACK_SCHEMA`，一次 `ai.complete_json()` 产出 titles + segments + refined 的 JSON） |
| `core/subtitle_ops.py` | ✅ 已完成（`split_srt_to_file`、`build_subtitle_style`、`escape_ffmpeg_path`、`hex_color_to_ass` 等） |
| `core/video_ops.py` | ⚠️ 部分抽取——主要的 ffmpeg utilities 目前仍定义在 [tools/video/video_tools.py](../../src/tools/video/video_tools.py) 顶部（`extract_audio_to_mp3` 等），与 UI 类同文件但已是无 tkinter 依赖的纯函数。未来可能迁到 `core/video_ops.py` |
| `core/segment_model.py` | ✅ 已完成（`Segment` dataclass、`parse_timestamp`/`format_timestamp`、`load_from_file`/`save_to_file`、`end_of`/`duration_of`、`validate`、`safe_filename`）。为分段综合工作台服务，兼容 AI 生成的 `subs.txt` 格式 |
| `core/video_concat.py` | ✅ 已完成（`concat_videos` = ffmpeg concat demuxer；`split_segments` = 按选中行 stream copy 切片；`merge_segments` = 重编码每段到临时文件再 concat，支持跨段跳跃合并）。进度通过 `progress_cb(done, total)` 上报 |

## 与 core/ 并列的共享基础设施

以下模块住在 `src/` 根下（不进 `core/`，因为它们要么依赖 tkinter，要么面向进程级状态）：

| 文件 | 职责 |
|------|------|
| [hub_logger.py](../../src/hub_logger.py) | 线程安全全局 logger 单例，Hub 启动时注册底部日志面板回调 |
| [hub_layout.py](../../src/hub_layout.py) | Hub 主窗口布局持久化 (`~/.videocraft/layout.json`)，见 [11-hub-layout-persistence.md](11-hub-layout-persistence.md) |
| [i18n.py](../../src/i18n.py) | 本地化入口，`tr(key, **kwargs)` 带 fallback 链，见 [12-i18n.md](12-i18n.md) |
| [project.py](../../src/project.py) | Project 模型 + recent.json 管理 |
| [operations.py](../../src/operations.py) | Operation Registry（Sidebar 右键菜单） |
| [tools/base.py](../../src/tools/base.py) | `ToolBase` mixin：`set_busy/done/error/warning` 统一入口 |
