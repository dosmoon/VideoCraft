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

### 下一步要做（news_desk overlay 系统）

事件档案有了，现在做"把档案信息渲染到视频上"的部分：

**v0.1 范围（已在 part 3 规划讨论时达成共识，待开工）**：

1. `core/composition/overlays.py` 升级（现在只有 stub）：
   - 实现 `LowerThirdOverlay` dataclass：演讲者名牌（host + host_bio
     + host_affiliation），左下/右下时段控制
   - 实现 `ChapterRibbonOverlay`：顶部常驻细条显示当前章节标题
2. `core/composition/render.py` 注册 overlay renderer：
   - 走 libass 多轨方案（再加 1-2 个 ASS dialogue 轨道，带 `\\pos()` 
     绝对定位 + 起止时间），与现有字幕轨同引擎，**preview≡render**
3. `composition_preview.html`：Canvas 镜像绘制两种 overlay
4. `core/composition/style.py`：`overlay_styles` 加这两个 class 的 schema
5. `derivative_types.py` 注册 `news_desk` type
6. `tools/news_desk/news_desk_tool.py` 工作台壳：基本字幕设置 +
   overlay 列表编辑器 + 预览
7. preset `news_desk_default.json`

**明确不在 v0.1**：
- AI prompt 自动生成 overlay 列表（先支持 chapters → ChapterRibbon
  自动派生 + 用户手填 LowerThird）
- 弹入弹出动效
- Zone 自动避让管理器
- ASR diarization 多说话人切换

**先决条件**：news context 数据底座已经齐了，可以直接开做。

### 当前会话状态

- HEAD: `66735ae` (news.realtime: ClaudeCode + WebSearch as second-source provider)
- 已 push origin/main
- workspace clean
- 准备 /clear 长上下文

### 重要参考

- 内容上下文数据架构：`src/core/source_context.py`（双 dataclass + 合并）
- AI 路由严格契约：`src/core/ai/router.py::_complete_json_by_tier`
- xAI Responses API 集成：`src/core/ai/providers/openai_compat.py::_call_xai_responses_json`
- ClaudeCode WebSearch 集成：`src/core/ai/providers/claude_code.py::_call_json_with_search`
- 现有 stub：`src/core/composition/overlays.py`（OverlaySpec 已预留 API 座位）
- 设计文档：`docs/draft/architecture-vision.md`
