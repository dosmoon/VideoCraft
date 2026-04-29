# VideoCraft Backlog

> 开发计划看板。优先级：🔴 P1 必须修 / 🟡 P2 重要增强 / 🟢 P3 体验提升
> 状态：`[ ]` 待开始 / `[~]` 进行中 / `[x]` 已完成

---

## 第一批：基础可用性（先修再上线）

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🔴 P1 | [ ] | PPT 视频生成管线 | Claude 对话产出 slide（md/html）→ PPT 插件渲染 → Claude 写备注讲稿 → TTS（Edge TTS 免费档 / Fish Audio 发布档）→ PPT 每页导出 PNG → ffmpeg 按音频时长拼接 + 字幕烧录 → MP4。完整管线草案见 [docs/draft/PPT2Videopipeline.md](docs/draft/PPT2Videopipeline.md) |
| 🟡 P2 | [ ] | extract-clip / auto-split 业务逻辑下沉到 core | [video_tools.py:127-193](src/tools/video/video_tools.py#L127-L193) 的 `get_keyframe_times / find_nearest_keyframe / auto_split_video(use_keyframes=...)` 仍在 UI 层自带 ffprobe/ffmpeg 实现，与 `core/video_split.split_one()` 能力重复。跟进项：切到统一 API，移除 UI 层的重复逻辑。菜单入口保留 |
| 🔴 P1 | [ ] | 字幕处理综合工作台 | 合并字幕菜单下 5 个独立窗口为一个工作台（对标 `split_workbench.py`），老入口保留平滑迁移。详见 [docs/draft/SubtitleWorkbench.md](docs/draft/SubtitleWorkbench.md) |
| 🔴 P1 | [ ] | 用户数据绿色化 | 当前持久化位置混乱：portable 部分 `keys/providers.json`（[ai_router.py:154](src/ai_router.py#L154)）在软件目录；**非 portable** 部分在 `~/.videocraft/`：layout.json（[hub_layout.py:14](src/hub_layout.py#L14) 窗口几何）、settings.json（[i18n.py:18](src/i18n.py#L18) 语言）、recent.json（[project.py:132](src/project.py#L132) 最近项目）、presets/（[subtitle/presets.py:15](src/tools/subtitle/presets.py#L15) 烧录 preset）。对一个"解压即用"的 portable 软件来说全走 `~/.videocraft/` 不合理：换电脑 / U 盘迁移就丢配置。目标：统一迁到 `<软件根>/user_data/`（或类似），同时保留迁移逻辑把老的 `~/.videocraft/` 自动搬过去一次。实施前需评估：是否保留"单用户 / 单机器"的默认选项切换（用户可能确实想在多个 portable 副本间共享配置） |
| 🔴 P1 | [ ] | yt-dlp JS runtime 修复 | YouTube 下载时 yt-dlp 因缺少 JavaScript 运行环境抛兼容性警告，部分格式解析失败导致清晰度缺失或直接下载失败。修复方案：(a) 升级 yt-dlp 到最新版本；(b) portable 包内置或检测系统的 Node.js；(c) 调用时显式传 `--js-runtimes node`。涉及 [tools/download/yt_dlp_tool.py](src/tools/download/yt_dlp_tool.py) 参数组装与打包脚本 |

---

## 第二批：免费层功能补齐（增强竞争力）

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🟡 P2 | [x] | 视频加水印（含无字幕场景） | 烧录功能已支持图片/文字/日期三类水印 + 无字幕场景（仅水印或纯重编码）。作为独立工具的提案不再追，新工作台烧录步骤已覆盖。 |
| 🟡 P2 | [ ] | SRT 时间轴整体偏移 | 字幕和视频对不上时，整体向前/向后偏移指定秒数 |
| 🟡 P2 | [ ] | SRT 格式转换 | SRT ↔ VTT / ASS，不同平台（B站/YouTube/剪映）格式要求不同（注：word_subtitle 可生成 ASS 卡拉OK效果，但非通用格式转换） |
| 🟡 P2 | [ ] | yt-dlp 下载时同步获取字幕 | yt-dlp 原生支持，加一个"同时下载字幕"选项，省去手动转录步骤 |
| 🟡 P2 | [ ] | 视频合并/拼接 | 多个视频片段按顺序合并为一个，自媒体剪辑常见需求 |
| 🟡 P2 | [ ] | AI 错误契约实施 (X1) | `core/ai/errors.py` 已定义 9 种 `AIError.Kind`（NETWORK/AUTH/QUOTA/RATE_LIMIT/REFUSED/MALFORMED/OVERFLOW/CANCELLED/UNKNOWN）但各 provider 仍直抛 RuntimeError。需要：(a) 给 5 个 provider 各写原生异常→Kind 映射表；(b) UI 加 Kind→恢复动作映射（AUTH→打开 AI 控制台、QUOTA→换 provider 等）。spec 见 [docs/design/04-ai-router.md](docs/design/04-ai-router.md) "错误契约（X1）" 章节 |
| 🟡 P2 | [ ] | AI 取消传播 wiring (X2) | `CancellationToken` 类已建但未真接入 — provider adapter 没注册 `abort_cb`、UI 没加取消按钮。长任务（翻译 2000 行 / TTS 多角色合成）目前没法中途停。需 wire 全链 + UI 加取消按钮。spec 见 [docs/design/04-ai-router.md](docs/design/04-ai-router.md) "取消传播（X2）" 章节 |
| 🟡 P2 | [ ] | TTS Voice ID 收藏 | Fish Audio TTS 当前每次合成都要手填 Voice ID（一串 32 位 hex）。AI 控制台加常用 voice 库下拉，或在 TTSApp 加最近用过的下拉 |

---

## 第三批：体验提升（用户留存）

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🟢 P3 | [ ] | 分割视频前显示分段预览 | 执行前列出解析出的分段列表，让用户确认再运行 |
| 🟢 P3 | [ ] | 各工具窗口风格统一 | 大小、配色、按钮样式统一；目前各工具窗口风格不一 |
| 🟢 P3 | [~] | 输出路径可自定义 | 🟡 yt-dlp / speech2text / video_tools / subtitle_tool 已支持；仅 translate_srt 仍硬编码输出到源文件目录 |
| 🟢 P3 | [~] | 操作参数持久化 | 🟡 subtitle_tool 已完成 preset 系统（~/.videocraft/presets/subtitle_burn.json，支持命名保存/切换/记忆 last_used）；其他工具待跟进 |
| 🟢 P3 | [ ] | AI 响应缓存 (X4) | 长 SRT 反复调优 prompt 浪费 tokens。需要：(a) **A 前缀缓存** — Anthropic `cache_control` / Gemini Context Cache / DeepSeek 自动；(b) **B 客户端 SHA256 缓存** — `user_data/ai_cache/`，LRU + 7 天 TTL + 100MB 上限。`core.ai.complete()` 已留 `cache_hint=` 参数位。spec 见 [docs/design/04-ai-router.md](docs/design/04-ai-router.md) "缓存 (X4)" |
| 🟢 P3 | [ ] | ASR / TTS Test 真实施 | AI 控制台 Lemonfox / Fish Audio 的 Test 按钮目前 disabled 占位。需要：(a) ASR — 在 `prompts/samples/silence-1s.wav` 塞 1 秒静音样本，Test 拿它打 Lemonfox；(b) TTS — provider 配置加 `test_voice_id` 字段，Test 调短文本合成 |
| 🟢 P3 | [ ] | per-(task, provider) prompt 变体 | `core.prompts.get(task)` 当前一 task 一 prompt。不同 provider 在同一任务上风格差异明显（DeepSeek 喜欢长解释、Gemini 偏简洁）。需要：扩展 prompts 文件命名为 `<task>.<provider>.md`，loader 优先匹配 (task, provider) 后 fallback 到 (task) |

---

## 已完成 ✅

| 完成时间 | 功能 | 备注 |
|---------|------|------|
| 2026-04 末 | 项目工作台 UX 收尾（Run All 反馈 + 按钮统一 + 段文件 resolver fix） | 三件事一起：(a) 状态条配色随状态变（idle/running 蓝、done 绿、failed 红）+ ✓/✗ glyph 前缀；(b) Run All 整链跟踪 `_chain_active` 标记，最后一步成功显示「✓ 全部运行完成 — 共 N 步」绿底 banner + `messagebox.showinfo` 弹窗强制 acknowledge；(c) 7 个 step 的 Run 按钮统一文案「运行 / Run」（卡片标题已经标明 step 干啥，按钮没必要再分化）；(d) `_resolve_segments_file` 跟进 `_pack-` rename，认 `-chapters.txt` 同时兜底老 `-segments.txt`；(e) step6 切片输出对齐文档约定挪到 `<basename>/output/splits/` |
| 2026-04 末 | 项目工作台 unit 目录结构 freeze | 每份 manifest = 1 个 processing unit，产物全落 `<project>/<basename>/` 子目录：顶层放原料 / canonical / mp3，`subtitles/` 装中间字幕，`output/` 装可交付物（烧录视频 / 章节切片 / titles / chapters / description / postprocess.json / 烧录用按规范换行的 split 字幕）。step5 文件名去掉 `_pack-` 前缀（titles/chapters/description/postprocess 自说明）；菜单英文标签 `Subtitle pack → Subtitle post-processing`。规则全文进 `docs/design/09-file-naming-convention.md`「项目工作台」章节。老 manifest 继续按 output[0] 字面值工作，重跑后自动迁移到新约定 |
| 2026-04 末 | 项目工作台 Hub 集成 | 工作台从独立 ToolFrame 折叠进 Hub 主布局：Hub 侧栏改 ttk.Notebook 双 tab（Resources 文件树 + Project manifest 列表）；New / Delete / Refresh 等 manifest 管理动作搬到 Hub 侧栏；侧栏选 manifest → 自动打开/聚焦工作台 tab + 调 `load_manifest()` 加载；菜单入口保留（首次菜单打开走空态）；持久化 `sidebar_tab` 字段记录上次选中页。`ProjectWorkbenchApp` 暴露 `set_project / load_manifest / current_basename / is_dirty / confirm_discard` 公共 API；删除内置左栏 + PanedWindow + 底部 status label。验证：手写 2 个 manifest 的项目 → 切换流畅，dirty 状态正确，i18n 双语对齐 |
| 2026-04 末 | 项目工作台 M1+：manifest 数据层 + 7-step 调度器 + 命名约定 freeze | (a) `Project` 加 manifest 助手（`.videocraft/manifests/<basename>.json`）+ 自动迁移老字段（`url→source`、顶层 `source` 折进 step1）；(b) 新工具 `tools/project/project_workbench.py`：左侧 manifest 树 + 右侧 7 个 step 卡（download / select / asr / translate / burn / pack / split），顶部状态栏带 `[Step N · Label]` 前缀；(c) step1 单字段 `source` 自动判 URL/本地（http(s) 走 yt-dlp，否则原地登记不复制）；step1→`<basename>_raw.mp4`，step2→canonical `<basename>.mp4`（项目根，约定**单输出**），多变体走多 manifest；(d) 自动接线 resolver：视频走最近 done step、字幕走 step3 译文优先 + step2 ASR 兜底，烧录字幕双轨智能路由（双语→上译下原；单语→落下轨）；(e) 烧录无字幕场景放行（仅水印/日期），ffmpeg 流式进度回写百分比；(f) UX：色带卡片头 + 强 section 分割、日期 today/clear 按钮、字段链路 hint、combobox/spinbox 隔离不再误滚表单。M2 待办：step2 多段拣选 UI（复用 `split_workbench` 播放器） |
| 2026-04 末 | Project 元数据迁入 `.videocraft/` 隐藏目录 | 仿 VSCode 的 `.vscode/` 范式，`videocraft.json` 改写到 `.videocraft/project.json`，避免和素材文件混在文件夹根。`Project.open()` 加一次性迁移：检测到旧根级 `videocraft.json` 则把内容搬入新位置并删除旧文件；`get_files()` 隐藏 `.videocraft/` 目录避免出现在 Sidebar。docs（02-project-model / 00-overview / 03-ui-hub / 05-use-cases）同步 |
| 2026-04 末 | 字幕一键 pack + AI Console 重做（两段式 + 模型 Picker）| 四件事打包：(a) 新增 `subtitle.pack` prompt + `core.srt_ops.generate_subtitle_pack()` + `write_subtitle_pack()`，一次 `ai.complete_json()` 调用产出 titles + segments + refined，落 1 份 JSON + 3 份 TXT（`-titles` / `-segments` / `-refined`），新菜单项「一键分段+精炼+标题（结构化）」；(b) Router task 合并：`subtitle.segments / refine / titles` 三条冗余 routing → 单一 `subtitle.post`，加迁移函数自动清理旧 providers.json 条目；(c) AI 控制台 Routing 标签从 (provider × model) × task 矩阵改为「上：Task Routing 4 行下拉 / 下：Providers 紧凑列表」两段式，同时修掉滚轮全局绑定渗透到 modal Edit 对话框的 bug；(d) LLM Edit 对话框模型部分由 textarea 改为「已启用模型 Listbox + 模型 Picker 对话框」——Picker 带搜索 + 复选 + 手动添加入口，无 key 或 list_models 失败时仍可手动加，解决 Gemini 一次刷新糊 20+ 模型的痛点。commits 813b7eb / f25614f / 9f1c939 |
| 2026-04-18 | subprocess 编码统一 | Windows 下 text-mode subprocess 默认走 GBK，ffmpeg/ffprobe 输出含非 ASCII UTF-8 字节（如 0xb4）时 `_readerthread` 抛 `UnicodeDecodeError`；异常死在线程里被吞掉，表面功能无感但 stdout/stderr 内容静默丢失，对依赖输出解析的调用（ffprobe 时长/JSON、分辨率探测、ffmpeg stderr 诊断）是未爆雷。统一 13 处 text-mode 调用点为 `encoding="utf-8", errors="replace"`，对齐 slidev_pipeline / video_concat 等新代码风格。commit 075a1cb |
| 2026-04 | Prompt 集中管理（L16 closed）| 4 个 prompt 抽离到 `prompts/*.md`：translate / subtitle.{segments,refine,titles}。新建 `core/prompts.py` 提供 get/set/reset/is_overridden API（DEFAULTS 内置作 Reset 兜底）。core/srt_ops.py 删 50+ 行硬编码常量；core/translate.py 改 hub 加载；TranslateApp UI 删 prompt Text 编辑框（架构原则 4 落实）。AI 控制台新增 Prompts tab：左 task 列表（被改的 ● 标记） + 右 Text 编辑器 + 占位符提示 + Save / Reset。i18n +11 keys（zh/en 882 对称）|
| 2026-04 | AI 架构重构：core/ai 门面 + AI 控制台 + 路由矩阵（L15 closed） | 三阶段交付：① M1~M5 把 LLM/ASR/TTS 全部 AI 调用收拢到 `core/ai/`（router + providers/* + facade），UI 层一律走 core feature 不直 import SDK；② M6 把旧 Toplevel `RouterManagerWindow` 改造为 Hub tab `AIConsoleApp`，引入「功能 × 档位」矩阵；③ 试用后 redesign：取消 tier 维度（数据 schema 压扁、TranslateApp 删高/中/低 radiobutton）、Keys+Matrix 合并单 tab、删 Enabled 勾子、加 Test 按钮（LLM）+「从 API 刷新」模型列表（Gemini / OpenAI-compat）。架构契约（AIError 9 种 Kind / CancellationToken / describe / cache / streaming / concurrency）暂留 stub，详见 [docs/design/04-ai-router.md](docs/design/04-ai-router.md) |
| 2026-04 | 视频分割后端统一 + splitvideo 旧入口清理 | 新建 `core/video_split.py`：`SplitMode` 枚举（fast / keyframe_snap / accurate）+ `probe_keyframes()` 带 (path, mtime) 缓存 + `split_one()` 统一入口；`core/video_concat.split_segments()` 加 `mode` 参数（默认 `KEYFRAME_SNAP`）；综合工作台 UI 新增"分割模式"下拉 + 悬停 tooltip + 探测关键帧状态提示；删除 `tools/video/split_video.py` 整文件 + Hub TOOL_MAP / 菜单 / 右键 Operation 的 splitvideo 引用；i18n 同步 zh/en 双语（删 19 键 + 增 8 键，仍保持 875 对 875 对称）。`extract-clip` / `auto-split` 两入口按用户决策保留，跟进项已转为 P2 |
| 2026-04 | AI Router JSON 结构化 + Claude Code provider | 新增 `complete_json(schema=...)` API；translate_srt 切 JSON 路径；新增 ClaudeCode subprocess provider（本地 `claude -p` CLI，无需 key，默认关闭）；删除 Groq。详见 [docs/design/04-ai-router.md](docs/design/04-ai-router.md) |
| 2026-04 | 视频分割综合管理工作台 | `tools/video/split_workbench.py`：加载视频 + `subs.txt`，Treeview 列表 review + 增删改 + 就地编辑起始时间/标题；嵌入 VLC 播放器，单击跳转、双击播放；分段导出（stream copy）与跨段合并导出（重编码 + concat demuxer）。核心抽出到 `core/segment_model.py` 与 `core/video_concat.py`；VLC 封装在 `ui/vlc_player.py`，缺失时优雅降级。旧 `splitvideo` / `extract-clip` / `auto-split` 入口保留不动 |
| 2026-04 | 中英双语 i18n 全链路（Phase 1-7） | `tr()` + `src/i18n/{zh,en}.json` 806 keys；File > Preferences > Language 切换（重启生效）；工厂默认 English；覆盖 Hub + 全部工具 UI |
| 2026-04 | 统一错误提示 | 所有工具 `except` 捕获后显示真实报错，不再静默失败或只说"操作失败" |
| 2026-04 | text2video TTS 重构（Fish Audio） | Fish Audio 集成、单/多角色对话、SRT 生成（字符比例时轴）、多章节视频合成+字幕烧录、分割逻辑抽离 core 层；探索方向（音效叠加/AI排版/CLI驱动）保留为 parked 项 |
| 2026-04 | 字幕烧录工具 Preset 系统 | 27 项参数命名保存/切换；Default 受保护；last_used 记忆；~/.videocraft/presets/subtitle_burn.json |
| 2026-04 | 字幕烧录工具输出路径自定义 | 新增输出文件行（Entry+浏览+自动开关）；默认 `Video_<lang>.mp4` 同视频目录；auto_output 随 preset 持久化 |
| 2026-04 | YouTube 发布模块 | OAuth 2.0 登录；标题/描述/标签/可见性/播放列表 支持；Resumable Upload；定时发布（需保持应用运行） |
| 2026-04 | 语音转字幕界面异步化 | `_transcribe_audio` 改 threading；按钮转录中禁用；后台 after(0) 回写日志 |
| 2026-04 | yt-dlp 下载列表改 Checkbutton | 替换 Listbox 蓝色高亮；Canvas 滚动框架；默认全选；Select All/Deselect All 同步 |
| 2026-04 | 每日要闻合成模块（DailyNewsApp） | PIL像素级自动换行、ffmpeg滚屏叠加、9:16/16:9分辨率选择、字幕背景透明度、可编辑水印 |
| 2026-04 | Speech2Text verbose_json 模式 | 同时保存 .json + .srt；自动检测语言；文件名附ISO语言码；语言不匹配时 Hub 警告 |
| 2026-04 | 统一文件命名规范 | 下载文件：`{short}_{date}[_{quality}].{ext}`；SRT：`_{lang}.srt`；烧录后：`_sub_{lang}.mp4` |
| 2026-04 | yt-dlp 文件名截断优化 | 原标题 >20 字符显示为「前10…后10」，左侧资源栏可读 |
| 2026-04 | yt-dlp 传入 project folder | Hub 打开 yt-dlp 工具时自动填入当前项目目录 |
| 2026-04 | SubtitleTool 单语字幕烧录 | 仅选中一条轨道也可正常烧录；修复 output_path 赋值顺序 bug |
| 2026-04 | SRT 编码自动识别 | `read_srt()` 回退链：utf-8-sig → utf-8 → gbk → gb2312 → big5 → latin-1，全工具统一 |
| 2026-04 | Hub 全屏启动 + 侧边栏加宽 | 启动即 zoomed 全屏；侧边栏 200→320px |
| 2026-04 | ASR 默认语言改为英文 | 原为中文，大多数转录场景为英文内容 |
| 2026-04 | 媒体格式模块设计规范 | `docs/design/10-media-format-modules.md`；每种节目形态一个独立 class |
| 2026-04 | GitHub Actions CI/CD 打包发布 | tag 触发自动构建，生成 portable zip |
| 2026-04 | README 重写（中文，面向用户） | 三部分：介绍 / 安装 / 功能 |
| 2026-04 | 产品战略设计文档 | `docs/design/08-product-strategy.md` |
| 2026-04 | VideoCraftHub 主界面 | VS Code 风格，Toplevel 多窗口架构 |
| 2026-04 | AI Router 统一路由层 | 支持 Gemini / DeepSeek / Custom(OpenAI 兼容) / ClaudeCode 自动切换（Groq 已删除，ClaudeCode 默认关闭） |

---

## 探索方向（记录，暂不实现）

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🟡 P2 | [ ] | 合成视频高级功能 | 音效叠加、多层视频叠加（类视频编辑工具），如背景音乐、B-roll 覆盖等 |
| 🟡 P2 | [ ] | AI 智能排版融合 | 将 AI 能力融入合成视频流程，如自动字幕排版、智能场景切换建议等 |
| 🟡 P2 | [ ] | CLI / AI 对话驱动视频合成 | 通过 AI 对话方式调用既有素材与工具合成视频，类 agent 驱动的视频生产线 |

---

## 需求池子（未评估，先记录）

| 需求 | 说明 |
|------|------|
| subprocess 编码规范持续观察 | 2026-04-18 统一修过 13 处 text-mode 调用点后，后续新增外部进程调用须显式传 `encoding="utf-8", errors="replace"`（或等价 `errors="ignore"`）。观察点：(a) 是否还冒出新的 `_readerthread UnicodeDecodeError` / `Thread-N` 报错；(b) 新贡献者是否漏加编码参数；(c) 若反复出问题，考虑抽 `core/shell.py` 统一 wrapper 强制默认值。当前刻意不做 wrapper，先观察几个版本 |
| 全工程中文注释英文化 | 将所有 .py 文件中的中文注释统一改为英文，提升代码可读性与国际化 |
| 开发规范文档整理 | 代码风格、文档规则、命名规范等，待产品稳定后统一整理 |
| 字幕文件命名规则优化 | ASR/翻译产出的中英文 SRT 文件名存在可读性或冲突问题，需要重新梳理命名规则（哪些后缀表示哪种语言/阶段、与烧录输出如何区分） |
| ~~综合视频分割工作台~~ | 已提升至 P1「视频分割综合管理页」，见第一批 |
| Tab 工具面板可滚动布局 | 字幕烧录等工具 UI 内容越来越多，在较低分辨率或日志面板被拖大时底部控件会被挤出；需要给每个 Tab 的 ToolFrame 提供一个纵向可滚动容器（Canvas+Scrollbar 或类似），工具布局保持原生 grid 即可，由框架负责滚动 |
| i18n Phase 8：en.json 翻译质量打磨 | 当前 en.json 为"够用即可"水准（Phase 1-7 手工 + 机译混合），待有真实英文用户反馈后再统一 review 用词、语气、术语一致性 |
| Buffer 多平台发布中转集成 | 通过 Buffer GraphQL API 把发布模块扩展到 X/Twitter、Instagram、LinkedIn、Threads、TikTok、Facebook、YouTube、Pinterest、Mastodon、Google Business、Bluesky 等 11 个平台；核心诉求是绕过 X 官方 API 的 17条/天硬上限（借 Buffer 平台级配额）。详见 [docs/draft/buffer-publishing-integration.md](docs/draft/buffer-publishing-integration.md) |

---

## 暂缓 / 不做

| 功能 | 原因 |
|------|------|
| 云化 / SaaS | 视频处理算力消耗大，并发/等待/成本三重问题 |
| Docker 分发 | 目标用户不具备 Docker 使用背景 |
| 跨平台（短期） | 先把 Windows 版做稳，Mac 需求出现时再考虑本地 Web 方案 |
| 批量处理 | 工作量大，先做单文件质量，后续再扩展 |
