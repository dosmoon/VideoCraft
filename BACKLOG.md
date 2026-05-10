# VideoCraft Backlog

> 开发计划看板。优先级：🔴 P1 必须修 / 🟡 P2 重要增强 / 🟢 P3 体验提升
> 状态：`[ ]` 待开始 / `[~]` 进行中 / `[x]` 已完成

---

## 第一批：基础可用性（先修再上线）

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🔴 P1 | [ ] | 项目工作台 UX + 健壮性深度优化（延后） | 现状：M1+ + 字幕集成 Phase 2 跑通了"能用"基线，但 UI 反人类（7 步表单密度过大、字段名跟用户心智不对齐、cross-step 状态不可见、错误恢复路径不明）+ 健壮性差（resolver 多处分叉各走各的；step1/2/3 有 manual SRT 时 enable/disable 心智模型靠注释而非 UI；mid-session 切换字段不触发卡片重渲；validator 报错信息只对开发者友好）。下一轮要做：(a) 重画卡片信息层级 — 隐藏运行时只读字段；(b) cross-step affordance — 哪条 SRT 进哪一步、哪个被覆盖一目了然；(c) resolver 统一收口（burn vs translate vs pack 别再各走各的）；(d) validator 错误信息走 i18n + 对应可点击的修复入口；(e) 工作台首屏空态/快速开始引导。先把 backlog 其它高价值项消化掉再回头深做 |
| 🟡 P2 | [ ] | extract-clip / auto-split 业务逻辑下沉到 core | [video_tools.py:127-193](src/tools/video/video_tools.py#L127-L193) 的 `get_keyframe_times / find_nearest_keyframe / auto_split_video(use_keyframes=...)` 仍在 UI 层自带 ffprobe/ffmpeg 实现，与 `core/video_split.split_one()` 能力重复。跟进项：切到统一 API，移除 UI 层的重复逻辑。菜单入口保留 |
| 🟢 P3 | [ ] | requirements.txt → uv + lockfile | 当前 requirements.txt 已全量 pin 到精确版本，可重现构建已解决；下一步引入 `uv` + `requirements.in/.lock` 双文件机制，升级一键化 + 装得快。改动面：build_portable.py 切到 `uv pip install`，CI 加 uv 安装步骤 |

---

## 第二批：体验提升（用户留存）

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🟢 P3 | [ ] | 各工具窗口风格统一 | 大小、配色、按钮样式统一；目前各工具窗口风格不一 |
| 🟢 P3 | [~] | 输出路径可自定义 | 🟡 yt-dlp / speech2text / video_tools / subtitle_tool 已支持；仅 translate_srt 仍硬编码输出到源文件目录 |
| 🟢 P3 | [~] | 操作参数持久化 | 🟡 subtitle_tool 已完成 preset 系统（user_data/presets/subtitle_burn.json，支持命名保存/切换/记忆 last_used）；其他工具待跟进 |
| 🟢 P3 | [ ] | ASR / TTS Test 真实施 | AI 控制台 Lemonfox / Fish Audio 的 Test 按钮目前 disabled 占位。需要：(a) ASR — 在 `prompts/samples/silence-1s.wav` 塞 1 秒静音样本，Test 拿它打 Lemonfox；(b) TTS — provider 配置加 `test_voice_id` 字段，Test 调短文本合成 |
| 🟢 P3 | [ ] | per-(task, provider) prompt 变体 | `core.prompts.get(task)` 当前一 task 一 prompt。不同 provider 在同一任务上风格差异明显（DeepSeek 喜欢长解释、Gemini 偏简洁）。需要：扩展 prompts 文件命名为 `<task>.<provider>.md`，loader 优先匹配 (task, provider) 后 fallback 到 (task) |
| 🟢 P3 | [ ] | TTS Voice ID 收藏 | Fish Audio TTS 当前每次合成都要手填 Voice ID（一串 32 位 hex）。AI 控制台加常用 voice 库下拉，或在 TTSApp 加最近用过的下拉 |

---

## 🧠 内嵌 AI（Embedded AI Tier）

> 让 VideoCraft 自身进程内置 ASR / TTS / 翻译，普通用户点开 exe 不配置任何外部服务即可端到端跑通。
> aistack 网关、云 API 是另外两条平行产品线。详细设计：[docs/draft/tech-selection-embedded-ai.md](docs/draft/tech-selection-embedded-ai.md)

| 优先级 | 状态 | 子任务 | 说明 |
|--------|------|------|------|
| 🔴 P1 | [x] | sherpa-onnx Whisper ASR provider（CPU） | 2026-05-10 落地 (d455f9c) — `core/ai/providers/sherpa.py` in-process Whisper int8；segments[] 句子级时间戳；首启档 ASR 通路就绪 |
| 🔴 P1 | [ ] | sherpa-onnx Kokoro TTS（synthesize 加进 sherpa.py） | 多语言版默认；目标解锁"零依赖配音" |
| 🔴 P1 | [x] | llama-cpp-python Qwen3 翻译 provider | 2026-05-10 落地 — `core/ai/providers/llama_cpp.py` (call/call_json/list_models)；新 ptype `llama_cpp` 接进 router；模型放 `<models>/llama/*.gguf` 用户自取；CPU 默认（n_gpu_layers 在 cfg 可调）。pip install 必须用 abetlen 预编译索引（见 requirements.txt 注释） |
| 🟡 P2 | [ ] | GPU 加速升级（sherpa-onnx-cuda + onnxruntime-gpu） | 4060 Laptop 基线下 large-v3-turbo + Qwen3-8B 才能流畅。先 CPU 跑通契约（已完成）再换 GPU |
| 🔴 P1 | [x] | 模型分发系统 | 2026-05-10 落地 — `core/models/{catalog,downloader,registry,manager}.py` + `tools/models/manager_window.py`（菜单 AI → 模型管理）。Range 续传 + 多源 fallback (ModelScope/hf-mirror/HF) + sha256（可选）+ 磁盘预检 + 队列 UI + 删除 + reveal in explorer + 改 models_dir。catalog 内置 5 项（whisper-small/turbo + qwen3-1.7b/8b + silero-vad）。**未做**：sha256 hash 实际填充（先 size 校验）/ 版本归档 / 并发下载 / aria2c 多连接 |
| 🟡 P2 | [ ] | 首启 / 升档 UI | 首启可跳过下载向导（强引导非强制）；推荐档升档对话框；设置 → 模型管理 |

---

## 📺 节目生成（Program Generation）

> 从源视频生成"节目稿子" + 据稿子合成视频。本期只立**稿子层**，视频层另立。
> 稿子 = 结构化文本，描述"节目讲什么、谁讲、按什么顺序讲"，可被视频生成层消费。

### 节目稿子生成（Program Script Generation）

通用架构：
- 输入：源视频 + 字幕（manual SRT / ASR / translated）
- AI 层：复用 `core/ai` LLM facade，新增 `core/program/` 模块
- 输出：结构化稿子（Markdown + YAML frontmatter，待 MVP 时敲定）

**5 种形态（按优先级）**：

| 优先级 | 状态 | 形态 | 说明 |
|--------|------|------|------|
| 🔴 P1 | [ ] | 切片稿（Clip Script） | 长视频 → AI/用户选段 → N 条独立短视频脚本（hook + 原片片段 + outro + title + hashtags）。对标 OpusClip。MVP 走「用户手动框选 + AI 生成首尾文案」，避开"病毒性预测"难关。复用 split_workbench 选段能力 |
| 🟡 P2 | [ ] | 摘要稿（Summary Script） | 长视频字幕 → 浓缩文本 + 关键时间戳。最简单形态，几乎纯 LLM 任务。建议作为整体架构的 hello-world 验证 |
| 🟡 P2 | [ ] | 解读稿（Commentary Script） | 原片字幕 + AI 分析 → 单解说员独白脚本，引用原片片段。用户原话场景（"解读鲍威尔发布会"）。Prompt 工程要引导客观分析而非编造观点 |
| 🟢 P3 | [ ] | 对话稿（Dialogue Script） | 原片字幕 → 多角色台词（A 问 B 答 / 主播+嘉宾）。为多角色 TTS 铺路，需要角色人设 + 对话节奏 |
| 🟢 P3 | [ ] | 剧场稿（Theater Script） | 原片信息内核 → 改写成相声/脱口秀/沙雕短剧等娱乐形态。创造性最高，prompt 设计最难，市场最差异化 |

**共通设计决策（落地时再敲定）**：
- 稿子格式：自由文本 vs 结构化（建议 Markdown + YAML frontmatter）
- 是否内嵌视频指令（`[切到原片 12:34-12:50]` 等）—— 决定与视频层耦合度
- AI 一把生成 vs 人机协作迭代 —— 决定要不要做编辑器
- 5 种形态共享 schema 还是各自独立 —— 架构岔口

**MVP 建议**：不要 5 种一起做。从 P2 摘要稿打通 `core/program/` 整体架构（最简单），再跳 P1 切片稿做主推商业价值。P3-P5 按需排。

### 节目视频生成（Program Video Synthesis）—— 占位

从稿子合成视频：多角色 TTS 编排、原片切片插入、字幕烧录、转场。等稿子层 MVP 跑通后另立 plan。

---

## 已完成 ✅

历史完成项请查 `git log -- BACKLOG.md` 或对应设计文档：
- AI 架构 / 路由 / 取消 / 错误契约 → [docs/design/04-ai-router.md](docs/design/04-ai-router.md)
- 文件命名 / unit 目录 → [docs/design/09-file-naming-convention.md](docs/design/09-file-naming-convention.md)
- 媒体格式模块 → [docs/design/10-media-format-modules.md](docs/design/10-media-format-modules.md)
- 项目工作台 / Hub → [docs/design/02-project-model.md](docs/design/02-project-model.md) + [03-ui-hub.md](docs/design/03-ui-hub.md)
- 产品战略 → [docs/design/08-product-strategy.md](docs/design/08-product-strategy.md)

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
| PPT / Slidev 转视频 | 受众与现有"视频创作者"主线错位（教育 / 培训 vs 自媒体），与 text2video 重叠 65%+；AI-PPT-to-video 工作流尚未被市场验证。如未来要做应另起新软件，不容纳进本 repo。2026-04-30 删除 ppt2video / slidev_pipeline / pptx_pipeline / node_env 全部相关代码 |
| 字幕处理综合工作台 | 草案写完后世界变了：`subtitle.pack` 一键管线已覆盖 95% 流水线场景（一次 AI 调用产 titles+segments+refined），项目工作台 step5_pack 也包揽了「项目流程」中的字幕后处理。剩余 5% 的"手工 review/编辑"场景，用户用文本编辑器改 .txt 即可，不值得专做工作台。2026-04-30 决定取消，保留 5 个老菜单项作单步调试 fallback；菜单顺序调整把 pack 提到顶部 |
| SRT 时间轴整体偏移 | 服务的痛点是"用户拿外部字幕烧录对不齐"，但实际场景里 VideoCraft 自家的 ASR + 翻译 + pack 流程产出的字幕都是对齐的，外部字幕导入烧录是边缘场景。等真有用户反馈再做。2026-04-30 取消 |
| SRT 格式转换（SRT↔VTT/ASS） | 服务的痛点是"用户做完视频要传 B 站 / 嵌网页"，但目标用户群（自媒体视频创作者）多数全程 SRT 走完，且烧录是终态产物（视频里就有字幕），不需要外发字幕文件。word_subtitle 已能生成 ASS 卡拉 OK 效果。等真有用户反馈再做。2026-04-30 取消 |
| AI 响应缓存 (X4) | 当前所有 AI 入口（translate / ASR / pack / TTS）都是单次性操作 —— 跑完产物落盘，没有「同一份输入反复跑同一份 prompt」的 loop 场景。缓存现在做反而会让用户改 prompt 后困惑「为什么还是老结果」。`cache_hint=` API 位先留着不动。等将来开发 agent 类功能（自循环调用、多轮工具调用 / 反思 loop）时再补。2026-05-01 决定暂不做 |
