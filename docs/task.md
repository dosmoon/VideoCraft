# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。每个任务结束后清空或归档。

---

## 当前任务

**节目形态 #3：新闻编导（news_desk derivative）的基础设施**

源自 docs/draft/architecture-vision.md 里的 5 种节目形态规划。clip 和
bilingual_video 已落地，news_desk 是第三种。

### 已完成（2026-05-14 那次会话）

新闻视频的**事件档案数据底座 + AI 联网生成能力**已就绪：

1. **源视频内容上下文数据分离**：
   - `source/basic_info.json` — `SourceBasicInfo` 5 字段，人工填写
     （host / host_bio / event_date / event_location / episode_topic）
   - `source/context.json` — `SourceContext` 10 AI 字段
     （host_affiliation / guests / event_time / show_type /
     event_summary / key_points / background / audience /
     platform_tone / notes）
   - 字段集 disjoint，归属明确，下游用 `combined_prompt_block()`
   - 旧版 15 字段 context.json 自动迁移（首次读时抽出 5 anchor）

2. **AI 联网生成事件档案**：
   - 新 task `news.realtime`（LLM 类别），位于 `core/ai/config.py::TASKS`
   - 两路 provider 都可用，无单点依赖：
     - **xAI Grok**：走 `/v1/responses` API + `tools=[{type:"web_search"}]`，
       ~$0.02/call，~24s，citations 结构化数组
     - **ClaudeCode**：`claude -p --tools WebSearch`，~$0.21/call，~60s，
       citations 从 markdown 链接 regex 抽取
   - `core/source_context_ai.extract()` 调度，basic_info 作种子，
     replace（非 merge）写 context.json

3. **UI 双面板分离**：
   - source preview pane：5 anchor 字段 inline 只读 + `[✎ 编辑]`
     按钮 → `source_basic_info_dialog`（轻量 5 字段模态）
   - news_context pane：sidebar 同级条目，10 AI 字段分组显示 +
     `[✨ AI 填充]`（线程后台跑）+ `[✎ 手工编辑]`

4. **AI router 行为修复**：用户在 Provider 路由选了具体 provider 时
   绝对不静默 fallback。只有显式选 Auto 才走 candidate 池。

5. **基础设施改进**：
   - `core/ai/call_log.py` — 所有 LLM API 调用记 JSONL 到
     `user_data/logs/ai-calls.jsonl`（gitignored），含 citations /
     usage / latency / endpoint，可观测
   - `_json_utils.parse_json_response` fallback 到 `json_repair`，
     LLM 输出未转义引号/换行的 JSON 自救
   - xAI provider 注册到 `_DEFAULT_PROVIDERS`（用户需自行配 xAI.key）

### 已完成（2026-05-14 第二轮：news_desk overlay 渲染管线）

设计决策：命名跟齐广播业标准 —— `LowerThirdOverlay`（业内硬通货词）+
`TopicStripOverlay`（替代之前的 ChapterRibbon，更贴 topic-bar / chapter-
marker-strip 业内叫法）。Q1-Q4 决策见 docs/draft/news-desk-derivative.md。

落地清单 1-7 + 10 已完成（UI 工作台壳 8-9 留下次会话）：

1. **`core/composition/overlays.py`** — 加 `LowerThirdOverlay` /
   `TopicStripOverlay` dataclass + `overlay_to_dict` / `overlay_from_dict`
   round-trip helper + `TYPED_OVERLAY_KINDS` 元组
2. **`core/composition/style.py`** — 加 `LowerThirdStyle` /
   `TopicStripStyle` + `OVERLAY_STYLE_CLASSES` 注册表 +
   `resolve_overlay_style()` 查找器 + `default_overlay_styles()` seed
3. **`core/composition/news_desk_overlays.py`** — 新文件，所有
   news_desk 类型 overlay 合并成单个 .ass 文件（PlayResX/Y = target_w/h，
   ASS 坐标=像素），通过单个 `subtitles=` filter 链入；`build_news_desk_ass()`
   纯函数 + `_renderer_news_desk_ass` 注册器
4. **`core/composition/render.py`** — `_named_overlay_jobs` 把
   typed news_desk overlays 路由成单个 `kind="news_desk_ass"` 合并 job；
   底部 import news_desk_overlays 触发注册
5. **`core/composition/preview.py`** — `style_to_web_dict` 加
   overlay_styles 字段；新增 `set_overlays(list)` API
6. **`ui/composition_preview.html`** — 加 `setOverlays` /
   `drawNewsDeskOverlays` / `_drawLowerThird` / `_drawTopicStrip`，pct→pixel
   换算与 Python 端一致
7. **`core/composition/presets.py`** — 加 `news_desk` 预设 store
   （passthrough + 双语字幕底 + overlay_styles seed）+ 完整 CRUD API
8. **`core/derivative_types.py`** — 注册 `news_desk` type
   （tool_key="news-desk", single_instance=False, basename="news"）

**Smoke test 通过**：
- Round-trip：LowerThirdOverlay/TopicStripOverlay → dict → 还原
- ASS 生成：1920x1080 目标，结构正确（Header + 2 Style + 6 Dialogue）
- e2e ffmpeg render：10s testsrc + 2 overlays → MP4 渲染成功 + 抽帧验证
  名牌（深蓝底 + 红色 accent + 双行文字）和 topic strip（顶部蓝条）都正确显示

### 下一步要做（news_desk UI 工作台壳）

渲染管线打通了，下一步是工作台 UI（task.md 老清单第 6-8 步）：

8. **`tools/news_desk/news_desk_tool.py`** —— 工作台壳（新文件）：
   - 复用 subtitle_tool 的 normalized layout 控件 + 双语字幕设置
   - Overlay 列表编辑器：增删改 LowerThird（基础 5 字段：title /
     subtitle / start / end / position）
   - 自动从 chapters.json 派生 TopicStrip（每章一条，[start, end] 取章节区间）
   - 自动从 basic_info.json 预填 LowerThird（host + host_bio + host_affiliation）
   - WebView 预览（CompositionPreview + set_overlays）
   - 导出按钮 → render_composition → derivatives/news_desk/<instance>/

9. **`VideoCraftHub.py` `TOOL_MAP`** — 挂载 `"news-desk"` →
   `"tools/news_desk/news_desk_tool.py"` / `"NewsDeskApp"`

10. **`i18n/{zh,en}.json`** — `derivative.news_desk` 显示名 + overlay
    UI 字符串（"添加名牌" / "Add lower third" 等）

### 重要参考

- 渲染入口：`src/core/composition/news_desk_overlays.py` （build_news_desk_ass）
- 默认样式：`LowerThirdStyle` / `TopicStripStyle` 字段含义见 dataclass docstring
- chapters 数据架构：`core/chapters_io.normalize_chapters` 单源；遍历
  即可派生 TopicStrip（每章 → 一条 TopicStripOverlay(topic_text=title,
  start=ch.start, end=ch.end)）
- 派生路径：`<project>/derivatives/news_desk/<instance>/` 约定
- 字幕轨复用：news_desk 的字幕跟 bilingual_video 是同一套 SubtitleStyle，
  preset 默认双语都开

### 当前会话状态

- HEAD: 待 commit（本会话改动尚未提交；task.md 已含完整接力信息）
- workspace dirty（待 commit / 或继续做 UI 后一并 commit）

### 重要参考（旧）

- 内容上下文数据架构：`src/core/source_context.py`（双 dataclass + 合并）
- AI 路由严格契约：`src/core/ai/router.py::_complete_json_by_tier`
- xAI Responses API 集成：`src/core/ai/providers/openai_compat.py::_call_xai_responses_json`
- ClaudeCode WebSearch 集成：`src/core/ai/providers/claude_code.py::_call_json_with_search`
- 设计文档：`docs/draft/news-desk-derivative.md`

### 重要参考

- 内容上下文数据架构：`src/core/source_context.py`（双 dataclass + 合并）
- AI 路由严格契约：`src/core/ai/router.py::_complete_json_by_tier`
- xAI Responses API 集成：`src/core/ai/providers/openai_compat.py::_call_xai_responses_json`
- ClaudeCode WebSearch 集成：`src/core/ai/providers/claude_code.py::_call_json_with_search`
- 现有 stub：`src/core/composition/overlays.py`（OverlaySpec 已预留 API 座位）
- 设计文档：`docs/draft/architecture-vision.md`
