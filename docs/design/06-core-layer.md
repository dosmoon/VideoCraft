# core 层设计：逻辑/UI 分离

## 设计动机

原有工具文件（VideoTools、SubtitleTool 等）将业务逻辑与 Tkinter UI 混在一起，
无法从 Sidebar 右键直接调用，也无法在不打开完整工具窗口的情况下执行操作。`core/` 层把纯逻辑抽出来供 UI 层和（未来的）Pipeline 层复用。

## 目录结构

```
src/core/
├── __init__.py
├── ai/                   ← AI Router 子包（providers / errors / cancellation / facade）
│                           详见 04-ai-router.md
├── env/                  ← Environment Component Registry（ffmpeg/node/yt-dlp 等组件
│                           检测 + Setup/Install/Upgrade 动作）
├── prompts.py            ← Prompt 集中管理（get/set/reset/is_overridden + DEFAULTS）
├── user_data.py          ← 便携用户数据入口（user_data_dir / path），包含一次性
│                           ~/.videocraft → <repo>/user_data/ 迁移
│
├── youtube_download.py   ← yt-dlp 唯一封口：extract_info / download_video /
│                           NETWORK_PRESETS / list_available_subtitles /
│                           summarize_subtitles / summarize_formats /
│                           jsruntime_status_line
├── srt_ops.py            ← SRT 字幕处理（统计 / 分段 / YouTube chapters / AI 精炼 +
│                           generate_subtitle_pack 一键产 titles+segments+refined+paragraphs）
├── srt_quality.py        ← SRT 质量指纹（纯结构性指标，无评分）
├── srt_from_text.py      ← 文本→SRT 时间轴生成（按字符比例分配）
├── subtitle_ops.py       ← 字幕烧录相关（分割 / 样式构建 / ffmpeg 路径 escape）
├── lang_names.py         ← BCP47 → (中, 英) 映射 ~50 条 + 搜索匹配
├── burn_presets.py       ← 字幕烧录 preset 持久化
├── burn_subs.py          ← 烧录主流程（核心 ffmpeg 调用）
│
├── video_ops.py          ← FFmpeg 视频/音频基础工具函数
├── video_concat.py       ← 分段切割 / 跨段合并（ffmpeg concat demuxer）
├── video_split.py        ← 视频分割统一入口（SplitMode + probe_keyframes + split_one）
├── video_compose.py      ← 视频合成（DailyNews/text2video 共用）
├── segment_model.py      ← Segment dataclass + 加载/保存 subs.txt + 校验
├── composer_model.py     ← text2video composer 数据模型
│
├── translate.py          ← SRT 翻译（走 ai facade）
├── asr.py                ← ASR 入口（走 ai facade，对应 Lemonfox 等）
└── tts.py                ← TTS 入口（走 ai facade，对应 Fish Audio 等）
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
| `core/youtube_download.py` | ✅ yt-dlp 唯一封口（之前 5 处直调散在 yt_dlp_tool + project_workbench 两边一直漏 JS runtime opts）。统一 extract/download，自动注入 `js_runtimes={"node":...}` + `remote_components=["ejs:github"]`（Node 检测走 core/env），HLS 格式不再丢。2026-04-30 起加 `list_available_subtitles` / `summarize_subtitles`，下载支持 `subtitle_langs` / `auto_caption_langs` / `skip_video`。NETWORK_PRESETS 砍到只剩 throttled（fast/medium 是性能反优化已删除）|
| `core/srt_ops.py` | ✅ SRT 解析、统计、YouTube 分段、AI 精炼、标题生成；`generate_subtitle_pack()` + `write_subtitle_pack()` + `SUBTITLE_PACK_SCHEMA` 一次 `ai.complete_json()` 产出 titles + segments + refined + paragraphs 的 JSON（2026-04-30 起 paragraphs 也合并入 pack 输出）|
| `core/srt_quality.py` | ✅ 2026-04-30 新增。SRT 结构性指纹（cue 数 / 平均时长 / 字符宽 / cps / 标点 % / ALL-CAPS % / speaker tags / sound fx / 晚开场标记）。无评分、零依赖。yt-dlp 工具下载完调用 `format_fingerprint(fp)` 写一行日志 |
| `core/lang_names.py` | ✅ 2026-04-30 新增。~50 条 BCP47 → (中, 英) 表 + `friendly_name` / `display_label` / `matches_search`（支持 code/中/英三路匹配）。避免引 `langcodes` 依赖 |
| `core/subtitle_ops.py` | ✅ `split_srt_to_file`、`build_subtitle_style`、`escape_ffmpeg_path`、`hex_color_to_ass` 等 |
| `core/burn_subs.py` / `core/burn_presets.py` | ✅ 烧录主流程 + preset 持久化（落 `<repo>/user_data/presets/subtitle_burn.json`）|
| `core/video_split.py` | ✅ `SplitMode` 枚举（fast / keyframe_snap / accurate）+ `probe_keyframes()` 带 (path, mtime) 缓存 + `split_one()` 统一入口 |
| `core/video_concat.py` | ✅ `concat_videos` = ffmpeg concat demuxer；`split_segments` = stream copy 切片（支持 `mode` 参数，默认 KEYFRAME_SNAP）；`merge_segments` = 重编码 + concat 支持跨段跳跃合并 |
| `core/video_ops.py` | ⚠️ 部分抽取——主要 ffmpeg utilities 仍在 [tools/video/video_tools.py](../../src/tools/video/video_tools.py) 顶部（`extract_audio_to_mp3` 等），与 UI 类同文件但已是无 tkinter 依赖的纯函数。BACKLOG P2 跟进迁移 |
| `core/segment_model.py` | ✅ `Segment` dataclass、parse/format timestamp、load/save subs.txt、validate、safe_filename。为分段综合工作台服务 |
| `core/translate.py` / `core/asr.py` / `core/tts.py` | ✅ 各自走 `core.ai` facade，UI 不直接 import provider |
| `core/prompts.py` | ✅ get/set/reset/is_overridden + DEFAULTS 兜底；4 个 prompt 文件落 `prompts/*.md` |
| `core/user_data.py` | ✅ `user_data_dir()` / `path(*parts)` 统一入口，import 时跑一次幂等的 `~/.videocraft → <repo>/user_data/` 迁移（不删旧目录，平行安装/回滚仍可用）|
| `core/env/` | ✅ EnvComponent 注册表 + 9 个可见组件（ffmpeg/ffprobe/node/vlc/claude_cli/yt-dlp/fish-audio-sdk/openai/Pillow）+ 1 隐藏（google-genai）。Node 走 user_data/runtimes/node/ managed 模式 |
| `core/ai/` | ✅ Router + providers + errors + facade，详见 [04-ai-router.md](04-ai-router.md) |

## 与 core/ 并列的共享基础设施

以下模块住在 `src/` 根下（不进 `core/`，因为它们要么依赖 tkinter，要么面向进程级状态）：

| 文件 | 职责 |
|------|------|
| [hub_logger.py](../../src/hub_logger.py) | 线程安全全局 logger 单例，Hub 启动时注册底部日志面板回调 |
| [hub_layout.py](../../src/hub_layout.py) | Hub 主窗口布局持久化（`<repo>/user_data/layout.json`，便携迁移后落 user_data/），见 [11-hub-layout-persistence.md](11-hub-layout-persistence.md) |
| [i18n.py](../../src/i18n.py) | 本地化入口，`tr(key, **kwargs)` 带 fallback 链，见 [12-i18n.md](12-i18n.md) |
| [project.py](../../src/project.py) | Project 模型 + recent.json 管理 |
| [operations.py](../../src/operations.py) | Operation Registry（Sidebar 右键菜单） |
| [tools/base.py](../../src/tools/base.py) | `ToolBase` mixin：`set_busy/done/error/warning` 统一入口 |
