# 切片稿（Clip Script）

**状态**：草稿 / 待评审
**日期**：2026-05-01
**优先级**：P1（节目稿子生成 5 形态之首）
**命名约定**：本文是 `docs/draft/program-script-<form>.md` 系列的第一份。
未来 4 份对应：`-summary.md` / `-commentary.md` / `-dialogue.md` / `-theater.md`。
视频生成层另立 `program-video-synthesis.md`，等稿子层 MVP 跑通后写。

---

## 1. 定位

**一句话**：长视频（直播 / 演讲 / 访谈 / 发布会）→ N 条 30-60 秒竖屏短视频，每条带 hook + 原片片段 + outro + 标题 + hashtags，可独立发布到 TikTok / YouTube Shorts / Reels。

**对标**：OpusClip（2024 年估值 ~2.15 亿美金，赛道标杆）。

**与 OpusClip 的核心差异**：

| 维度 | OpusClip | VideoCraft 切片稿 |
|------|---------|-----------------|
| 找亮点的方式 | 端到端 AI 扫长视频，自带"病毒性预测"模型 | **基于 chapter 级联**：复用前置 `subtitle.pack` 的章节划分，AI 只在已切好的章节内打分/找峰 |
| AI 训练数据需求 | 需要"什么爆过"的真实数据 | 不需要，纯 LLM prompt 工程 |
| 用户控制权 | 弱（黑盒推荐，被动接受） | **强（AI 推荐，人工守关每一步）** |
| 横转竖 | Face tracking 自动 pan/crop | **人工拖矩形框**（face tracking 砍出 MVP） |
| B-roll / 表情包覆盖 | 自动 | **MVP 不做** |
| 字幕动态高亮 | 关键词逐字放大 | MVP 不做（独立 backlog 项） |

**核心策略**：把"AI 在 90 分钟里找精彩"这个真难题，**降级**为"AI 在 5 分钟章节里找峰值" —— chapter 这层粗划分由现有 `subtitle.pack` 流水线免费提供。AI 任务从长文档语义跨度判断变成短文本批量打分，难度塌缩一个数量级，中文场景效果可控。

**目标用户场景**：
- 自媒体主：一场 90 分钟直播 → 5-10 条短视频引流
- 财经/科技博主：把发布会切成"X 谈 Y"系列
- 教育创作者：把 1 小时讲座切成"金句合集"

---

## 2. 核心工作流（4 阶段）

### 阶段 0：前置依赖（subtitle.pack 已产出）

切片稿的输入完全建立在现有 manifest pack 流水线产物上：

| 文件 | 内容 | 切片稿用途 |
|------|------|----------|
| `<basename>-postprocess.json` | 完整结构化 bundle | 主输入，含 segments + titles + paragraphs |
| `<basename>-chapters.txt` | `HH:MM:SS title` 每行 | 时间轴对齐的章节索引 |
| `<basename>-paragraphs.txt` | 每章节的原始 SRT slice | 阶段 2 AI 找峰的输入 |
| `<basename>-titles.txt` | 候选视频标题 | 可作为 hook 文案灵感 |
| `<basename>.mp4`（canonical） | 烧录前的源视频 | 阶段 4 切片输出的源 |

**前置校验**：进入切片稿工具时检查 `output/<basename>-postprocess.json` 是否存在；不存在引导用户先跑 manifest 的 step5_pack。

---

### 阶段 1：AI chapter 排序 + 用户勾选

**输入**：`postprocess.json` 里的 `segments[]`（每个含 `time_str` / `title` / `refined`）

**AI 任务**（`prompts/clip.rank-chapters.md`）：
对每个 chapter 打"亮点潜力分" 0-100，给一句话推荐理由。判断维度：
- 钩子强度（开头有没有金句 / 反问 / 反转）
- 观点密度（refined 浓缩里信息量是否密集）
- 情绪词 / 转折词 / 数据 / 命名实体出现频次
- 是否有"独立可看懂"的话题完整性

**AI 输出**：
```json
{
  "ranked": [
    {"idx": 3, "score": 87, "reason": "鲍威尔首次承认通胀'sticky'，市场关注焦点"},
    {"idx": 7, "score": 82, "reason": "失业率创新低但措辞谨慎，反差强"},
    ...
  ]
}
```

**用户操作**：
- UI 表格按分降序展示所有 chapter（标题 + AI 分 + 推荐理由 + refined 摘要 + 时长）
- **勾选**实际要切的 chapter（不限数量，5-10 个最常见）
- 可手动改打分排序、可加 AI 漏掉的 chapter

**失败回退**：AI 排序失败（API 错误 / 超时） → 退回纯人工排序，所有 chapter 默认按时间序展示，用户自己挑。

---

### 阶段 2：选中 chapter 内 AI 找精确亮点段 + 用户 review

**输入**：每个选中 chapter 对应的 `paragraphs.txt` slice（带原始 cue 时间戳）

**AI 任务**（`prompts/clip.find-peaks.md`）：
在该 chapter 范围内（一般 3-8 分钟）找 1-3 个 30-60 秒的精确切点。返回 cue 边界 + 评分理由。

**AI 输出**：
```json
{
  "peaks": [
    {
      "start_sec": 754.0,
      "end_sec": 798.0,
      "score": 91,
      "reason": "鲍威尔说出'sticky inflation'关键词后立即给出政策含义"
    },
    ...
  ]
}
```

**对齐规则**：AI 给的 start/end 必须 snap 到最近的 cue 边界（避免句子被切半）。规则：
- start_sec → 取该时刻**之前**最近的 cue start
- end_sec → 取该时刻**之后**最近的 cue end
- 整段长度限制：30s ≤ duration ≤ 90s（超界 → AI 重试或丢弃）

**用户操作**：
- 列表展示所有候选切片（chapter 标题 + 起止 + 文本预览 + AI 分）
- 复用 `tools/video/split_workbench.py` 的 `VlcPlayerFrame`（[ui/vlc_player.py:47-100](ui/vlc_player.py)）做预览
- 拖时间轴 / 输入框微调起止
- 删不要的、加 AI 漏掉的

**失败回退**：单个 chapter AI 失败 → 标红跳过，不阻塞其他；用户可手动框选段落作为该 chapter 的切片。

---

### 阶段 3：AI 生成包装文案 + 用户改字

**输入**：每条切片的（原片字幕文本 + chapter 上下文 + 视频整体标题）

**AI 任务**（`prompts/clip.package.md`）：
为每条切片生成 4 件套：
- `hook`：开头 5 秒贴在画面顶部的钩子文本（中文 ≤ 15 字 / 英文 ≤ 8 词）
- `outro`：收尾 5 秒的引导/总结/CTA（中文 ≤ 20 字）
- `title`：发布平台用的视频标题（中文 ≤ 30 字）
- `hashtags`：3-5 个相关 hashtag

**AI 输出**（每条切片一份）：
```json
{
  "hook": "美联储主席今天说了一个关键词",
  "outro": "黏性通胀 = 降息再等等",
  "title": "鲍威尔承认通胀'有点黏'，市场怎么解读？",
  "hashtags": ["#美联储", "#鲍威尔", "#通胀"]
}
```

**用户操作**：每条切片一张卡片，4 个字段都可改。

**失败回退**：AI 失败 → 字段留空，用户自己写；不阻塞导出。

---

### 阶段 4：人工 crop 框选竖屏 + 一键导出

**横转竖策略**：
- 默认：center crop（取画面正中 9:16 区域，最简单）
- 高级：用户在 VLC 预览上拖拽一个 9:16 矩形框，整段切片沿用同一个 crop
- **不做**：face tracking 自动 pan、多 keyframe crop（B 段切 A 段）—— Phase 2 再考虑

**新组件**：`ui/crop_overlay.py`
- 在 VLC 预览画布上叠加一个可拖拽 / 可缩放的矩形（锁定 9:16 比例）
- 输出：`crop_rect = {x, y, w, h}` （相对原视频分辨率的归一化坐标 0.0-1.0）

**字幕策略**：
- 复用 `core/subtitle_ops.py:21-26` 的 `LAYOUT_DEFAULTS["vertical"]`（max_chars_zh=10 / fontsize=20 / margin_v=60）
- 字幕来源：从原片字幕里截取该切片时间段，重新分行适配竖屏宽度
- Hook / Outro：作为额外字幕轨（更大字号、靠顶部 / 靠底部），用 ffmpeg drawtext filter 烧录

**导出流程**（每条切片）：
```
源视频 → ffmpeg 切段（-ss/-to）→ crop filter → scale to 1080x1920
       → 烧录原片字幕（重新分行的竖屏版）
       → 烧录 hook（前 5s）+ outro（后 5s）的额外字幕
       → 输出 <basename>/output/clips/<basename>-clip-<N>-<title-slug>.mp4
```

**额外产出**：
- `<basename>-clips.json` —— 整体稿子（所有切片的结构化数据，给视频生成层）
- `<basename>-clip-<N>.yaml` —— 每条切片的独立稿子（可选导出，给视频层逐条消费）

---

## 3. 数据模型

### CLIP_SCRIPT_SCHEMA（新增）

整体稿子文件 `<basename>-clips.json`：

```python
CLIP_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_basename": {"type": "string"},
        "source_video": {"type": "string"},      # canonical mp4 path
        "generated_at": {"type": "string"},      # ISO datetime
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},               # 1-based
                    "chapter_idx": {"type": "integer"},      # 来自 segments[idx]
                    "chapter_title": {"type": "string"},
                    "start_sec": {"type": "number"},         # 已 snap 到 cue 边界
                    "end_sec": {"type": "number"},
                    "score": {"type": "integer"},            # 0-100
                    "score_reason": {"type": "string"},      # AI 给的理由
                    "original_excerpt": {"type": "string"},  # 原片字幕该段文本
                    "hook": {"type": "string"},
                    "outro": {"type": "string"},
                    "title": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "crop_rect": {                           # 阶段 4 才填
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "w": {"type": "number"},
                            "h": {"type": "number"}
                        }
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "reviewed", "exported", "skipped"]
                    },
                    "output_path": {"type": "string"}        # 导出后填
                },
                "required": ["id", "chapter_idx", "start_sec", "end_sec", "status"]
            }
        }
    },
    "required": ["source_basename", "source_video", "clips"]
}
```

### 复用：subtitle.pack 现有 schema

不改动 `core/srt_ops.py:21-47` 的 `SUBTITLE_PACK_SCHEMA`，只读消费它。

### 落盘位置

```
<project>/<basename>/
├── output/
│   ├── <basename>-postprocess.json     ← 已有，输入
│   ├── <basename>-chapters.txt         ← 已有
│   ├── <basename>-paragraphs.txt       ← 已有
│   ├── <basename>-titles.txt           ← 已有
│   └── clips/                          ← 新增子目录
│       ├── <basename>-clips.json       ← 新增，整体稿子
│       ├── <basename>-clip-1.yaml      ← 新增，每条独立稿子（可选）
│       ├── <basename>-clip-1-<slug>.mp4
│       ├── <basename>-clip-2.yaml
│       └── <basename>-clip-2-<slug>.mp4
```

`<slug>` = title 取前 20 字符 + ASCII 化（中文用拼音 / 直接保留 UTF-8 看 OS）。

---

## 4. AI Prompt 设计

三个独立 prompt，每个走 `core.ai.complete_json` + JSON schema。Task 命名进 router task_routing：

| Task 名 | Prompt 文件 | 默认 tier | 说明 |
|---------|-----------|---------|------|
| `clip.rank` | `prompts/clip.rank-chapters.md` | STANDARD | 短文本批量打分，对模型质量要求中等 |
| `clip.peak` | `prompts/clip.find-peaks.md` | STANDARD | 段内挑句子，要求中等 |
| `clip.package` | `prompts/clip.package.md` | PREMIUM | 创意文案生成，对模型质量要求高 |

**Prompt 通用约束**（所有三个 prompt 都要写明）：
- 输出语言 = 输入语言（中文输入出中文 hook）
- 必须严格遵循 schema，不许加额外字段
- 评分必须给 reason，禁止只给分不解释
- 禁止编造原片没说过的事实（hook 可以提炼，不能虚构）

**Prompt 文件结构**（沿用现有 `prompts/subtitle.pack.md` 的范式）：
```
# Clip Rank Chapters

## Role
You are a short-video editor analyzing chapter highlights...

## Input
{chapter_list}

## Output Schema
(JSON schema 描述)

## Examples
(few-shot examples)

## Constraints
- 评分 0-100，60 分以下不推荐
- reason 一句话不超过 30 字
...
```

---

## 5. UI 草图

切片稿是个**多阶段 wizard**，不适合塞进单一窗口。建议 4 个 Tab（也可以是单页面纵向 4 个区块，按用户偏好）。

### Tab 1：章节排序

```
┌──────────────────────────────────────────────────────────────┐
│  切片稿 — 鲍威尔 2026-04-30 议息会议发布会                     │
│  [刷新 AI 排序]  AI: claude-sonnet ▼  Tier: STANDARD ▼       │
├──────────────────────────────────────────────────────────────┤
│  ☐ 选 │ AI 分 │ 章节标题            │ 时长  │ 推荐理由        │
│  ───┼──────┼─────────────────────┼─────┼───────────────  │
│  ☑   │  91   │ 通胀 sticky 表态    │ 5:23 │ 全场关注焦点     │
│  ☑   │  87   │ 失业率新低反差      │ 4:12 │ 措辞谨慎反差强    │
│  ☐   │  72   │ 量化紧缩进度        │ 6:45 │ 技术性强，长尾受众  │
│  ☑   │  68   │ Q&A 答记者         │ 8:30 │ 多个具体数字       │
│  ☐   │  41   │ 开场寒暄          │ 1:15 │ 信息量低           │
│  ...                                                         │
├──────────────────────────────────────────────────────────────┤
│  已选 3 个章节，共 17:55 → [下一步：找精确亮点]                  │
└──────────────────────────────────────────────────────────────┘
```

### Tab 2：段内找峰 + Review

```
┌──────────────────────────────────────────────────────────────┐
│  候选切片列表                                  视频预览          │
│  ───────────────────────────────              ┌────────────┐ │
│  ▼ 通胀 sticky 表态 (3 candidates)           │            │ │
│   ☑ #1  91分 12:34-13:18 (44s)              │ [VLC 画面]  │ │
│      "鲍威尔说sticky inflation..."           │            │ │
│   ☑ #2  76分 14:02-14:45 (43s)              │            │ │
│      "市场对通胀的预期..."                    │            │ │
│   ☐ #3  62分 15:20-15:50 (30s)              └────────────┘ │
│  ▼ 失业率新低反差 (2 candidates)              ▶ ⏸ ⏹ 12:50  │
│   ☑ #4  88分 ...                              ─────●────── │
│  ▼ Q&A 答记者 (1 candidate)                  起止微调:       │
│   ☑ #5  79分 ...                            start [12:34] │
│                                              end   [13:18] │
│  [+ 手动添加切片]                              [应用]        │
├──────────────────────────────────────────────────────────────┤
│  已选 5 条切片 → [下一步：生成文案]                             │
└──────────────────────────────────────────────────────────────┘
```

### Tab 3：包装文案

```
┌──────────────────────────────────────────────────────────────┐
│  切片 #1 — 通胀 sticky 表态  (44s)            [批量重生成]   │
│  原片片段："鲍威尔说sticky inflation, 这意味着..."             │
│                                                              │
│  Hook    [美联储主席今天说了一个关键词                  ]  ✓ │
│  Outro   [黏性通胀 = 降息再等等                         ]  ✓ │
│  Title   [鲍威尔承认通胀'有点黏'，市场怎么解读？          ]  ✓ │
│  Tags    [#美联储] [#鲍威尔] [#通胀]  [+ 添加]              │
├──────────────────────────────────────────────────────────────┤
│  切片 #2 — 失业率新低反差 ...                                │
│  ...                                                         │
└──────────────────────────────────────────────────────────────┘
```

### Tab 4：Crop + 导出

```
┌──────────────────────────────────────────────────────────────┐
│  切片 #1 — Crop 框选                                          │
│  ┌──────────────────────────────────────┐  Crop 模式:        │
│  │   原视频 16:9 预览                    │  ○ Center crop     │
│  │  ┌─────┐                             │  ● Manual frame    │
│  │  │     │ ← 拖拽红框定位竖屏区域        │                    │
│  │  │     │   (锁定 9:16 比例)            │  字幕样式:         │
│  │  │     │                              │  Vertical preset ▼ │
│  │  └─────┘                             │  Hook 字号 [40] ▼  │
│  └──────────────────────────────────────┘  Outro 位置  ▼     │
│  [应用此 crop 到所有切片] [仅本切片]                            │
├──────────────────────────────────────────────────────────────┤
│  ▶▶ [一键导出全部 5 条] → output/clips/                       │
│  进度：[████████░░] 3/5  当前：clip-3 烧录字幕...              │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. 复用清单

实施时这些已有模块直接拿来用，**不重写**：

| 模块 | file:line | 用途 |
|------|----------|------|
| `core/srt_ops.py:21-47` | SUBTITLE_PACK_SCHEMA | 阶段 0 输入 schema |
| `core/srt_ops.py:354-474` | write_subtitle_pack 范式 | 写 clips.json 时仿写 |
| `core/segment_model.py` | Segment / parse_timestamp / format_timestamp | 时间戳处理 + segment 数据结构 |
| `ui/vlc_player.py:47-100` | VlcPlayerFrame | Tab 2/4 的视频预览 |
| `tools/video/split_workbench.py:66-100` | segment 编辑器范式 | Tab 2 候选列表交互 |
| `core/subtitle_ops.py:21-26` | LAYOUT_DEFAULTS["vertical"] | 竖屏字幕样式 |
| `core/burn_presets.py:57` | orientation 参数 | 字幕烧录走垂直 preset |
| `core/ai/__init__.py:60-72` | complete_json + cancel_token | 三个 AI 调用入口 |
| `core/translate.py:302-307` | AIError unwrap 范式 | 错误处理 |
| `core/prompts.py` | get / set / reset | 三个新 prompt 走统一管理 |

---

## 7. 实施时的文件清单（预期）

### 新增

| 路径 | 用途 |
|------|------|
| `src/core/program/__init__.py` | 模块标识 |
| `src/core/program/clip.py` | 业务层：rank_chapters() / find_peaks() / package_clip() / export_clip() |
| `src/tools/program/__init__.py` | 模块标识 |
| `src/tools/program/clip_workbench.py` | UI 主窗口（4 Tab） |
| `src/ui/crop_overlay.py` | VLC 上的 9:16 矩形拖拽组件 |
| `prompts/clip.rank-chapters.md` | 阶段 1 prompt |
| `prompts/clip.find-peaks.md` | 阶段 2 prompt |
| `prompts/clip.package.md` | 阶段 3 prompt |

### 修改

| 路径 | 改动 |
|------|------|
| `src/core/prompts.py` | DEFAULTS dict 加 3 条 clip.* |
| `src/core/ai/router.py` | task_routing 默认加 clip.rank/clip.peak/clip.package（可选，不加也能跑 fallback） |
| `src/hub/...` (TOOL_MAP) | 注册新工具入口 "切片稿" → clip_workbench.ClipWorkbenchApp |
| `src/i18n/zh.json` + `en.json` | ~30 条新 keys（4 个 Tab + AI 状态 + 错误提示），双语对称 |

### 不动

- 现有 manifest / project_workbench / subtitle.pack 流水线 —— 切片稿是消费方，不修改生产方
- `core/subtitle_ops.py` 的 LAYOUT_DEFAULTS["vertical"] 暂不改（如发现竖屏字幕在 1080×1920 下需微调字号再说）

---

## 8. MVP 边界（明确不做）

| 功能 | 为什么不做 | 何时考虑 |
|------|----------|---------|
| Face tracking 自动 pan/crop | 工程量大 + 需要训练数据 + 中文场景质量未知 | Phase 2，先看人工 crop 体验 |
| B-roll / 表情包覆盖 | 需要素材库 + AI 选图，超出 MVP scope | 独立功能，未来另议 |
| 病毒性预测打分 | OpusClip 真护城河，需要平台数据 | 永远不做（不是我们能做的事）|
| 字幕动态高亮（关键词放大） | 视觉灵魂但是独立工程量 | 单独 backlog 项 |
| 平台直接发布 | 走 buffer-publishing-integration 另议 | 看 Buffer 集成进度 |
| 多视频批量切片 | UI 复杂度 ×N | Phase 2，单视频跑通后 |
| 多 chapter 跨段拼接成 highlight reel | 改变数据模型 | Phase 2 |
| AI 生成的切片自动配音替换原音 | 走对话稿 / 解读稿形态，不是切片稿的事 | 对应形态文档另议 |

---

## 9. Phase 2 / 未来扩展接入点

设计时**预留**这些扩展位，避免 Phase 2 重构：

1. **字幕动态高亮**：Tab 4 字幕烧录步骤暴露 `subtitle_renderer` 接口，未来可插入 ASS karaoke 渲染器替代默认 SRT 烧录。
2. **AI crop 推荐**：CLIP_SCRIPT_SCHEMA 的 `crop_rect` 已是结构化字段，未来加 `crop_candidates: [{x,y,w,h,confidence}]` AI 可填，UI 仍人工选确认。
3. **跨段拼接**：clips 数组项加可选 `segments: [{start,end}]` 字段（多段构成一条切片），UI 加"合并"按钮。
4. **Prompt 调风格**：用户在工具里选"hook 风格"（疑问 / 反转 / 数据 / 情绪）→ 走 per-(task, provider) prompt 变体（已在 backlog）。
5. **批量切多视频**：clips.json 改为支持 `source_videos: []` 数组。

---

## 10. 验证 & 端到端测试

### Smoke test：跑通最小路径

测试素材：本地已有任意 manifest unit（必须已跑过 step5_pack）。

```python
from core.program import clip

# Aliases for ergonomics
postprocess = "/path/to/<basename>-postprocess.json"
video       = "/path/to/<basename>.mp4"

# 阶段 1
ranked = clip.rank_chapters(postprocess)
assert all("score" in r and "reason" in r for r in ranked["ranked"])

# 阶段 2
selected = [r["idx"] for r in ranked["ranked"][:2]]  # top 2
peaks_per_chapter = clip.find_peaks(postprocess, selected)
assert all(30 <= (p["end_sec"] - p["start_sec"]) <= 90
           for ps in peaks_per_chapter.values() for p in ps)

# 阶段 3
all_peaks = [p for ps in peaks_per_chapter.values() for p in ps]
packaged = [clip.package_clip(postprocess, p) for p in all_peaks]
assert all("hook" in pk and "title" in pk for pk in packaged)

# 阶段 4
out_dir = "/tmp/clip_test"
for i, (peak, pkg) in enumerate(zip(all_peaks, packaged), 1):
    clip.export_clip(
        video, peak, pkg,
        crop="center",  # MVP 默认
        out_dir=out_dir,
        clip_id=i,
    )

# 验证
import os
assert os.path.exists(f"{out_dir}/<basename>-clips.json")
assert len(os.listdir(out_dir)) >= len(all_peaks) + 1  # mp4 + json
```

### UI 端到端（用户视角）

1. Hub → 「切片稿」工具 → 选一个已 pack 完的 manifest unit
2. Tab 1：等 ~10s AI 排序 → 勾 3 个 chapter → 下一步
3. Tab 2：等 ~30s AI 出候选 → review，留 5 条切片，微调 1 条起止 → 下一步
4. Tab 3：等 ~20s AI 出文案 → 改其中 2 条 hook → 下一步
5. Tab 4：默认 center crop → 一键导出
6. 验证 `output/clips/` 下：1 份 clips.json + 5 个 .mp4，每个 mp4 是 1080×1920、30-60s、烧录字幕清晰、hook/outro 字幕显示

### 验证点 checklist

- [ ] 竖屏分辨率正确（1080×1920）
- [ ] 字幕没出 9:16 安全区
- [ ] 起止 snap 到 cue 边界（句子不被切半）
- [ ] hook 在前 5 秒显示，outro 在最后 5 秒显示
- [ ] clips.json 格式符合 CLIP_SCRIPT_SCHEMA
- [ ] AI 失败时降级路径可用（人工排序 / 人工框选 / 人工写文案）
- [ ] 取消按钮在三个 AI 阶段都能秒停（cancel_token 链路）
- [ ] 中文/英文双 i18n 显示正确

---

## 11. 开放问题（评审时需拍板）

| 问题 | 选项 | 默认建议 |
|------|------|---------|
| 4 Tab wizard vs 单页纵向 | 两种 UI 范式 | 4 Tab（流程感强，跨 chapter 切换不乱） |
| crop_rect 是否每条切片独立设置 | 全局共享 / 每条独立 | 默认共享，可单条覆盖 |
| 是否在 BACKLOG 加链接到本草案 | 加 / 不加 | 加（提升发现性） |
| chapter 排序时是否要给"全部不要"按钮 | 加 / 不加 | 加（用户可能整片不值得切） |
| 导出时是否同步生成 .yaml 个体稿子 | 默认导出 / 仅在选项勾选时导出 | 默认导出（视频生成层未来要消费） |
| AI 模型默认 tier | STANDARD 全程 / package 走 PREMIUM | rank/peak STANDARD，package PREMIUM |

---

## 12. 跟进项 / 不在 scope

- **代码实施另立 plan**：本文是设计草案，实施时按本文做
- **prompt 文件本体**（prompts/clip.*.md）—— 实施阶段写
- **其余 4 种形态文档**（summary / commentary / dialogue / theater）—— 等本草案磨合定型，批量产出，复用本文的章节模板和命名约定
- **视频生成层**（program-video-synthesis.md）—— 等切片稿 MVP 跑通
