# AI 切片重构设计稿

**状态**：设计中（设计先于实现）
**日期**：2026-05-12
**前身**：`docs/draft/program-script-clip.md`（Phase A~C 已上线，但 2026-05-11 从 derivative_types REGISTRY 摘下，相关代码进入 dead-code-ish 状态等待大幅简化）
**触发**：5-12 重构后 sidebar 三段式落地，是时候把 AI 切片从「一个怪兽工作台」拆开重做

---

## 1. 核心架构转变

**问题**：旧 `ai_clip` 派生把所有事情都装一个袋子里 — 章节检测 / 段落精炼 / 标题生成 / 热点评分 / 选段 / 切视频 / 应用样式 / 烧录。AI 决策跟渲染绑死，导致：

- 重跑 AI 必须重渲染
- 调样式必须重跑 AI
- 中间产物（章节、标题）独立没有价值，不能跨派生复用
- prompt 调优困难，因为输入输出耦合在一个超大工作台里

**新模型 = 两层分离**：

```
[字幕分析层] 项目级、可复用、AI 都在这里
└── subtitles/<iso>.srt → 多个分析产物 (titles / chapters / hotclips / ...)

[切片派生层] 实例级、确定性、零 AI
└── derivatives/clip/<inst>/ 消费 hotclips.json + 用户挑选 + 样式 preset → 短视频
```

**两层通过结构化文件解耦**。修改样式不用重跑 AI；重跑 AI 不影响已渲染的实例。

---

## 2. 字幕分析层（Subtitle Analysis）

每个字幕（`subtitles/<iso>.srt`）可以衍生 **6 种分析产物**。每种都是 AI 产出的项目级数据文件，跟字幕语言绑定。

### 2.1 6 种分析

| 类型 | 文件 | 复用现有 | 描述 |
|---|---|---|---|
| 标题 | `<iso>.titles.json` | `srt-gen-titles` prompt | 候选标题数组 |
| 章节 | `<iso>.chapters.json` | `srt-gen-segments` prompt | `[{start, end, title}]` |
| 全文文字稿 | `<iso>.transcript.md` | `srt-extract-subtitles` | 纯文本 dump，去时间戳 |
| 分章节全文 | `<iso>.chapter_transcript.md` | `srt-extract-paragraphs` | 按章节聚合的段落 |
| 分章节精炼 | `<iso>.chapter_refined.md` | `srt-refine` prompt | 各章节精炼后的内容 |
| 热点片段 | `<iso>.hotclips.json` | **全新** | 病毒性候选片段 |

前 5 种**复用现有 `tools/subtitle/srt_tools.py` 的 prompt**（已经在 `srt-gen-pack` 里串过）。这次只是把它们从「独立菜单工具」重新封装成「字幕的项目级派生」，并落到规范路径。

第 6 种是真正的新东西，见 2.4。

### 2.2 文件布局

```
<project>/
└── subtitles/
    ├── zh.srt
    ├── zh.json                       ← ASR verbose（现状，可选）
    ├── zh.titles.json                ← 新
    ├── zh.chapters.json              ← 新
    ├── zh.transcript.md              ← 新
    ├── zh.chapter_transcript.md      ← 新
    ├── zh.chapter_refined.md         ← 新
    ├── zh.hotclips.json              ← 新
    ├── en.srt
    └── en.titles.json
    └── ...
```

**扁平结构**：靠 `<iso>` 前缀文件名自然排序，同语言的所有产物挨在一起。`_list_subtitle_srts` 只匹配 `<iso>.srt`，跟分析文件不冲突。

### 2.3 Sidebar 交互

字幕 section 改造：

```
[字幕]
  ✓ 源 (中文): zh.srt          [+ 生成派生]  [↻ 重生]   ← 行为不变
  ▼ 📋 标题 (zh)               ← 子节点，单击 → tab 0 预览
  ▼ 📑 章节 (zh)
  ▼ 📄 全文 (zh)
  ▼ 🔥 热点 (zh, 7 条)
  ✓ 翻译 (English): en.srt    [+ 生成派生]  [↻ 重生]
  ...
  [+ 添加翻译]
```

字幕行新增 `[+ 生成派生]` 按钮（小图标），点击弹菜单：

```
+ 标题
+ 章节
+ 全文文字稿
+ 分章节全文
+ 分章节精炼
+ 热点片段
```

每项点击：跑对应 prompt → 进度 modal → 写入 `subtitles/<iso>.<type>.json|md` → sidebar 自动刷出子节点。已存在的产物再次生成 = 覆盖（带确认）。

### 2.4 热点片段 prompt 设计

**输入**：

- 字幕文本（按策略切片，见下）
- `source/context.json`（topic / speakers / audience / register / ... — 见第 3 节）
- 用户参数：
  - `target_duration_range`：候选片段时长，默认 30~90s
  - `desired_count`：期望返回多少候选，默认 10~15

**输出**（`<iso>.hotclips.json`）：

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-12T...",
  "source_subtitle": "zh.srt",
  "strategy": "per_chapter",
  "clips": [
    {
      "start": "00:03:42.500",
      "end":   "00:04:35.200",
      "duration_sec": 52.7,
      "hook": "你以为美联储真的能控制通胀？",
      "why_viral": "反共识开场 + 数据反差 + 留白结尾",
      "score": 8,
      "suggested_title": "美联储的通胀谎言",
      "suggested_hashtags": ["#经济", "#美联储"]
    }
  ]
}
```

**MVP 路线决策**：路线 A —— **AI 推荐，用户主选**。

AI 返回 10~15 条候选 + 评分 + 理由；UI 不强排序、不自动选；用户在切片派生工作台里勾选要哪几条。score 字段保留，仅作为视觉提示（颜色、显示顺序），不绑死用户选择。

这避开了"病毒性预测"这个无底洞 prompt 调优问题。日后想升级路线 B（OpusClip 模式 AI 直接选）可以无缝切换 —— 因为产物格式不变，只是上层 UI 默认显示策略变。

### 2.5 章节作用范围（关键设计）

> 你说：章节排序无意义，但章节缩短 AI 处理文本能提精度

`hotclip` prompt 的内部统一接口：

```python
hotclip_prompt(transcript_slice: str, context: dict, params: dict) -> list[Clip]
```

prompt 单次处理一个 slice。调用方决定 slice 怎么切：

```
context_strategy = "per_chapter"  ← 有章节就一章一调，结果合并到一个池子
context_strategy = "full"         ← 不切，整段塞 prompt
context_strategy = "auto"         ← 有章节走 per_chapter，没章节走 full（默认）
```

无章节时整段=一章，逻辑天然兼容。

**章节只做 prompt 分窗，不参与最终排序**。所有 chapter 的候选合并到一个池子，按 score 排或者按时间排（UI 用户切换），不按 chapter 边界排。

这是设计上的硬约束 —— 旧 ai_clip 的失败教训之一就是"章节A 的 top1 vs 章节B 的 top1 不可比，但还是被放在同一个排序里"。

`per_chapter` 策略需要先存在 `<iso>.chapters.json`，否则 fallback 到 `full`。生成热点片段时如果用户选 `auto` 且章节不存在，UI 提示"建议先生成章节以提升精度"，但不强制。

---

## 3. 源信息卡（Source Context Card）

### 3.1 动机

目前 `Source` dataclass 只有技术参数（duration / width / height / url）。AI 分析在没有 topic / speaker / audience 信号的情况下，章节标题平淡、热点选段相关性弱。

加内容上下文层显著提升 AI 输出质量。这也填上了 `project_overview.md` 早就立好的 `background.json` 槽位（之前在 P4 milestone 里被搁置）。

### 3.2 数据模型

**复用既有 `ProjectBackground`**（`core/program/clip.py:197`，Phase C 已落地的 dataclass），但搬出 program/clip.py（那是被淘汰的旧切片代码），迁到 `core/source_context.py`：

```python
@dataclass
class SourceContext:
    """Free-form context describing the source material.
    Fed into AI prompts so generation has enough situational
    context to produce non-generic outputs. All fields optional."""
    show_type: str = ""          # 访谈 / 演讲 / 直播切片 / 课程 / 评论 / 解说
    host: str = ""               # 主讲人姓名
    host_bio: str = ""           # 一句话身份
    guests: str = ""             # 其他出场人 (free text, comma-separated)
    audience: str = ""           # 目标观众画像
    episode_topic: str = ""      # 整集主题 / YouTube 标题
    platform_tone: str = ""      # B 站 / 抖音 / 小红书 / YouTube
    notes: str = ""              # 杂项: 敏感话题 / 避雷词 / 特殊语气
```

落盘位置：`source/context.json`（跟 `source/meta.json` 同层 — 它是关于源视频的，不是项目元配置）。

### 3.3 编辑 UI

源 preview pane（preview tab 0 内）右栏元数据下方新增按钮 `[编辑上下文]` → **模态对话框**：

```
┌─ 内容上下文 ─────────────────┐
│  📄 yt-dlp 元数据（只读参考）  │
│  uploader: ...                │
│  description: ...             │
│  tags: ...                    │
│  ─────────────────────────    │
│  ✏️ 编辑字段                   │
│  节目类型:  [Combobox]        │
│  主讲人:    [Entry]           │
│  身份:      [Entry]           │
│  嘉宾:      [Entry]           │
│  观众画像:  [Entry]           │
│  整集主题:  [Entry]           │
│  平台语气:  [Combobox]        │
│  备注:      [Text]            │
│                               │
│         [取消]    [保存]      │
└───────────────────────────────┘
```

yt-dlp 自动拉到的 `description / uploader / tags`（在 `source/meta.json` 里）以**只读区**显示作为参考，不混入可编辑字段（platform truth 不能被用户改写覆盖）。

模态比 inline editable 简单 —— 跟 `subtitle_check_dialog` 等现有弹窗风格一致。

### 3.4 Prompt 注入

所有 6 个分析（5 个复用 + 1 个新增）的 prompt 加上 system context block：

```
你正在为以下节目生成 <type>：
- 节目类型: {show_type}
- 主讲人: {host} ({host_bio})
- 嘉宾: {guests}
- 整集主题: {episode_topic}
- 观众: {audience}
- 平台语气: {platform_tone}
- 备注: {notes}

字幕内容如下:
{transcript_slice}
```

空 context 也能跑（每个字段独立 fallback），但有 context 显著提升输出质量。

Prompt 文件放 `prompts/<task>.md`（沿用现有 `core.prompts.get` 体系），新增/改动具体文件清单见 Phase 落地段。

---

## 4. 切片派生层（Slimmed `clip` Derivative）

### 4.1 定位

**完全去除 AI**。这层就是"基于已选热点片段 + 样式 preset，跑 ffmpeg 切段 + 烧录字幕 + 加 hook/outro 卡 → N 个 mp4"的渲染调度器。

### 4.2 派生类型注册

```python
DerivativeType(
    type_name="clip",
    display_zh="切片",
    display_en="Clip",
    tool_key="clip",                    # 新工作台
    default_basename="default",
    single_instance=False,              # 同项目可有多个 clip 实例（不同样式/选段）
    description_zh="基于热点片段批量生成短视频"
)
```

加回 `derivative_types.REGISTRY`（之前 5-11 摘下的 `ai_clip` 不复活，新的 `clip` 是新东西）。

### 4.3 派生实例配置

```
derivatives/clip/<inst>/config.json:
{
  "schema_version": 1,
  "source_subtitle": "zh",                    ← ISO，指向 subtitles/zh.hotclips.json
  "selected_clip_indices": [0, 2, 5, 8],     ← 用户在工作台里勾的
  "render": {
    "aspect": "9:16",                         ← 竖屏
    "subtitle_preset": "default",             ← 复用 tools/subtitle 的 preset 系统
    "burn_subtitle_iso": "zh",
    "hook_card": {"enabled": true, "template": "use_suggested"},
    "outro_card": {"enabled": false}
  },
  "rendered_at": "2026-05-12T..."
}
```

### 4.4 工作台 UI

```
[左] 候选片段列表（来自 hotclips.json）
  ☑ #1  00:03:42 → 00:04:35 (53s)  ⭐8  "美联储的通胀谎言"
  ☐ #2  00:08:12 → 00:09:01 (49s)  ⭐7  ...
  ...

[中] 排序: [按时间 ▼] [按 score ▼]

[右] 样式设置
  方向:   [9:16 ▼]
  样式 preset: [default ▼]  [管理 preset...]
  字幕烧录: [✓] 用 zh 字幕
  Hook 卡: [✓]  使用 AI 推荐 hook
  Outro 卡: [✗]

[底] [渲染选中 (4 条)] [清空选择]
```

渲染：foreach selected → ffmpeg 切段 → 复用 `core/subtitle_burn` 套字幕 → 输出 `clip_001.mp4 ... clip_NNN.mp4`。

样式 preset **直接复用** `tools/subtitle/subtitle_tool.py` 的 preset 系统，不重新造轮子。

### 4.5 路径产物

```
derivatives/clip/default/
├── config.json
├── clip_001.mp4
├── clip_002.mp4
└── clip_NNN.mp4
```

每个 `clip_NNN.mp4` 都是独立可发布短视频。

---

## 5. 实施分期

| Phase | 范围 | 风险 | 价值 |
|---|---|---|---|
| **P1 框架** | 文件落盘 + sidebar `[+]` 菜单 + tab 0 通用预览渲染器 | 低 | 骨架 |
| **P2 复用 5 个 AI** | 标题/章节/全文/分章节全文/分章节精炼 → 项目化 | 低（prompt 现成）| 80% 价值 |
| **P3 源上下文卡** | `source/context.json` + 模态编辑 + prompt 注入 | 中（要改 5 个 prompt 文件）| AI 质量阶跃 |
| **P4 热点 + 切片派生** | 新 hotclip prompt + 切片 derivative 简化版 | 高（新 prompt 调优）| 完整闭环 |

### P1 具体任务

- [ ] `core/subtitle_analysis.py` — 新模块。定义分析类型枚举、文件名约定、`AnalysisArtifact` dataclass、扫描 / 写入 helpers
- [ ] Sidebar 字幕行新增 `[+ 生成派生]` 按钮 + 弹菜单（VideoCraftHub.py `_refresh_subtitles_section`）
- [ ] Sidebar 字幕行下展开分析子节点（类似派生实例的 artifacts 子节点）
- [ ] `ui/subtitle_analysis_preview.py` — 通用 tab 0 预览，按类型分发到 JSON / Markdown 渲染分支
- [ ] 进度 modal 复用 `SubtitlesProgressModal`（已经够通用）

### P2 具体任务

- [ ] `core/subtitle_analysis.py` 加 5 个 runner：`run_titles / run_chapters / run_transcript / run_chapter_transcript / run_chapter_refined`
- [ ] 5 个 runner 内部走现有 `srt_tools.py` 的 AI 函数（已经稳定）
- [ ] 输出格式标准化（每个产物的 schema 见 §2.1，落到 `core/subtitle_analysis_schema.py`）
- [ ] 通用预览渲染各产物：titles 列表、chapters 时间线、transcript markdown 渲染

### P3 具体任务

- [ ] 搬 `ProjectBackground` 从 `core/program/clip.py` → `core/source_context.py`（rename `SourceContext`）
- [ ] `Project` 类加 `context_path` / `read_context()` / `write_context()` 方法
- [ ] `ui/source_context_dialog.py` — 模态编辑弹窗
- [ ] 源 preview pane 右栏加 `[编辑上下文]` 按钮
- [ ] 5 个 prompt 文件加 system context block（`prompts/srt-*.md` 系列）
- [ ] `core/subtitle_analysis.py` 的 runners 调用前拼上 context

### P4 具体任务

- [ ] `prompts/hotclips.md` — 新 prompt 文件
- [ ] `core/subtitle_analysis.py` 加 `run_hotclips(strategy: "auto"|"per_chapter"|"full")`
- [ ] `hotclips.json` 预览 UI（带 score 着色 + 时间戳跳转）
- [ ] `core/derivative_types.py` 注册 `clip` 类型
- [ ] `tools/clip/clip_tool.py` — 新工作台（候选列表 + 样式 + 渲染）
- [ ] `core/clip_render.py` — 渲染调度（复用 subtitle_burn）
- [ ] 端到端测试：1 小时访谈 → 热点候选 10 条 → 选 5 条 → 渲染 5 个竖屏短视频

---

## 6. 不做 / 不变 / 留待将来

- **现存菜单 `字幕 → ...` 6 个工具**：原样保留作为「独立模式 fallback」，跟 subtitle_tool 的独立模式一样。重构不动它们。
- **平台原生章节**（YouTube 自带 chapters）：暂不做。罕见且需要用户对比确认 UI，不值当。将来再说。
- **Face tracking / 自动横转竖**：MVP 不做，沿用 program-script-clip 旧定位 — 用户拖矩形框。
- **B-roll / 表情包覆盖 / 字幕动态高亮**：MVP 不做，独立 backlog 项。
- **章节级排序 / 跨章节排序**：明确不做。所有候选合并一个池子，按时间或 score 排，不按章节边界。
- **路线 B（AI 自动选片直接出最终结果）**：MVP 不做。先 A 路线（候选 + 用户主选）。产物格式预留 score 字段，将来切换无需重做。
- **多语言交叉分析**（用 zh 章节去切 en 字幕）：暂不支持。每个分析锚一个 `<iso>`。

---

## 7. 与现存代码的清理关系

- `core/program/clip.py`：Phase A~C 大量代码 dead-code-ish。重构期间**先不动它**（保留为参考实现）。P4 切片派生跑通后再做整轮清理（删除旧 workbench、迁移测试）。新切片派生**不复用旧 program/clip 路径**，从干净 slate 开始。
- `ProjectBackground` → `SourceContext`：P3 期搬迁，搬完老位置加 deprecated alias 一个版本周期，再删。
- 现存菜单 `srt-gen-*` 系列：保留独立模式不动；P2 期 runner 复用其 AI 函数（不复用其 UI）。
- `derivative_types.REGISTRY` 当前只有 `bilingual_video`。P4 加 `clip`。
- 老 `ai_clip` type_name：永久不再使用（避免老项目 derivatives 目录里的存量 `ai_clip` 误冲突）。

---

## 8. 开放问题（实施中再定）

- hotclip prompt 的 `desired_count` 是硬上限还是软目标？建议软目标（AI 可能少给）。
- 分章节全文 / 分章节精炼如果 chapters.json 不存在，是 fail 还是自动先生成 chapters？建议自动先生成并提示用户。
- 热点片段的 `hook` 字段 vs `suggested_title` 字段如何区分？hook 是"开头一句钩子文案"，title 是"完整短视频标题"。要不要再加 `description` 字段？P4 试用中再定。
- 切片渲染的 hook / outro 卡跟旧 `HookOutroStyle` 体系怎么衔接？是复用还是重做？倾向 P4 期评估，看旧代码状态。
