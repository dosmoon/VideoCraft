# VideoCraft 设计总览

## 项目定位

面向内容创作者的视频生产工具集，核心流程：
**YouTube 下载 → 语音转字幕 → 翻译 → 字幕烧录**

技术栈：Python + Tkinter GUI + FFmpeg + AI（Gemini / Groq / DeepSeek）

---

## 三阶段重构路线

### Phase 1：AI Router ✅ 已完成
统一 AI 调用层，支持多 Provider 按档位路由。
详见 [04-ai-router.md](04-ai-router.md)

### Phase 2：VS Code 风格主界面 ✅ 已完成
Menu + Sidebar + Tab 嵌入式工具架构；底部可拖拽日志面板；5 色 Tab 状态指示；窗口布局跨会话持久化。
详见 [03-ui-hub.md](03-ui-hub.md)、[11-hub-layout-persistence.md](11-hub-layout-persistence.md)

### Phase 2.5：原子化重构 ✅ 基本完成
纯逻辑抽到 `src/core/`，工具统一用 `ToolBase` 提供的 `set_busy/set_done/set_error/set_warning` 接入 Hub 状态系统；文件结构按工具类别分包（`src/tools/{download,speech,translate,subtitle,video,text2video,publish,preferences}/`）。
详见 [06-core-layer.md](06-core-layer.md)、[07-operations-registry.md](07-operations-registry.md)

### Phase 3：国际化 & 产品化 🚧 进行中
- ✅ i18n 框架（`src/i18n.py` + zh/en locale 表）、File > Preferences 语言切换
- 🚧 全工具字符串抽取（Hub + translate 已完成，其它工具分阶段）
- ⏳ 跨工具 Pipeline 自动化（下载→转字幕→翻译→烧录一键流转）

---

## 核心设计原则

1. **Project = 文件夹**，任意文件夹均可打开，自动生成 `.videocraft/project.json` 作为标识（旧版本根级 `videocraft.json` 在 open 时一次性迁入）
2. **功能原子独立**，每个工具仍可单独运行（双模式：嵌入 Hub Tab / 独立 Tk）
3. **单进程 + 嵌入 Tab**，工具以 Tab 形式嵌入 Hub 内容区，共享 AI Router 统计和状态
4. **增量演进**，不做大爆炸重构，每步完成即可验证
5. **足够简单**，避免过度工程化
6. **中英双语一键切换**，面向中文创作者和国际开源用户。所有 UI 字符串走 `tr('key')`，locale 表在 [src/i18n/](../../src/i18n/)，用户偏好持久化到 `~/.videocraft/settings.json`。详见 [12-i18n.md](12-i18n.md)

---

## 文件结构

```
src/
├── VideoCraftHub.py              # 主入口（Menu + Sidebar + Tab + 底部日志）
├── project.py                    # Project 模型，文件夹 + .videocraft/project.json
├── hub_layout.py                 # Hub 布局持久化（geometry/sash/zoom）
├── hub_logger.py                 # 线程安全全局 logger（底部日志面板消费者）
├── i18n.py                       # tr(key) 本地化入口
├── i18n/
│   ├── zh.json                   # 中文 locale
│   └── en.json                   # 英文 locale（factory default）
├── ai_router.py                  # AI Router 统一路由层
├── router_manager.py             # Router 管理 UI
├── operations.py                 # Operation Registry（文件类型 → 右键操作）
│
├── core/                         # 纯逻辑层（无 tkinter 依赖）
│   ├── srt_ops.py
│   ├── video_ops.py
│   ├── subtitle_ops.py
│   ├── segment_model.py          # 分段模型（解析/保存 subs.txt + 校验）
│   └── video_concat.py           # 分段切割 + 跨段合并（concat demuxer）
│
├── ui/                           # 可复用 UI 组件（跨工具共享）
│   └── vlc_player.py             # 嵌入式 VLC 播放器 Frame（缺失时优雅降级）
│
└── tools/                        # UI 层，按类别分包
    ├── base.py                   # ToolBase mixin：set_busy/done/error/warning
    ├── download/    yt_dlp_tool.py
    ├── speech/      speech2text.py
    ├── translate/   translate_srt.py
    ├── subtitle/    subtitle_tool.py, word_subtitle.py, srt_tools.py,
    │                split_subtitles.py, presets.py
    ├── video/       video_tools.py, split_video.py, split_workbench.py
    ├── text2video/  text2video.py            # TTS/SRT/AudioVideo/DailyNews
    ├── publish/     youtube_publish.py, tiktok_publish.py
    └── preferences/ preferences.py           # 首选项面板（Tab 工具）

keys/
├── providers.json                # AI Provider 配置 + 档位路由
└── *.key                         # 各 Provider API Key

~/.videocraft/                    # 用户配置目录（跨会话状态）
├── recent.json                   # 最近打开的工程
├── layout.json                   # Hub 窗口布局
├── settings.json                 # 用户偏好（目前只有 language）
└── presets/
    └── subtitle_burn.json        # 字幕烧录工具预设

docs/design/                      # 本设计文档
```

---

## 文档导航

| 文件 | 内容 |
|------|------|
| [01-architecture.md](01-architecture.md) | 架构决策与约束 |
| [02-project-model.md](02-project-model.md) | Project 模型与 JSON 版本策略 |
| [03-ui-hub.md](03-ui-hub.md) | 主界面 Hub 设计（Menu + Sidebar + Tab + 日志面板） |
| [04-ai-router.md](04-ai-router.md) | AI Router 设计（Phase 1） |
| [05-use-cases.md](05-use-cases.md) | 用例集 |
| [06-core-layer.md](06-core-layer.md) | core 层设计：逻辑/UI 分离 |
| [07-operations-registry.md](07-operations-registry.md) | Operation Registry：文件类型→右键操作映射 |
| [08-product-strategy.md](08-product-strategy.md) | 产品战略与用户画像 |
| [09-file-naming-convention.md](09-file-naming-convention.md) | 文件命名规范 |
| [10-media-format-modules.md](10-media-format-modules.md) | 自媒体节目形态模块规范 |
| [11-hub-layout-persistence.md](11-hub-layout-persistence.md) | Hub 窗口布局持久化 |
| [12-i18n.md](12-i18n.md) | 本地化（i18n）架构与 phase 计划 |
