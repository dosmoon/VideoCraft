# news_desk 派生形态设计文档

> 状态：草稿 v0.1 / 2026-05-14
> 范围：节目形态 #3「新闻编导 / 演讲发布会」的整体设计，重点 v0.1 落地范围
> 上游依赖：news context 数据底座（已 ship，commit `d602bfe` / `66735ae`）
> 阶段：**v0.1（本 doc）= overlay 渲染引擎 + 最小工作台壳**

---

## 0. 立项与背景

VideoCraft 的 5 种节目形态规划见 [architecture-vision.md](architecture-vision.md)：
clip / bilingual_video / news_desk / 摘要 / 解读 / 对话 / 剧场。前两种已落地。

**news_desk 是什么**：演讲、新闻发布会、白宫简报这类源视频的成片输出。
本质 = `bilingual_video`（双语字幕烧录）+ 一组带时间窗口的**信息编导 overlay**
（演讲者名牌、章节进度条、引用金句弹屏等）。

**为什么独立于 bilingual_video**：
- 单一项目可能切多个版本（完整版 / 媒体短版 / 主题剪辑）→ `single_instance=False`
- AI prompt 完全不同 —— 这种形态依赖人物 / 时间地点 / 机构等结构化上下文
- UI 复杂度跟字幕烧录不在一个量级（要 overlay 编辑器）

**底座已就绪**（2026-05-14 这一轮做的）：
- `source/basic_info.json` 5 字段人工锚定（host / host_bio / event_date /
  event_location / episode_topic）
- `source/context.json` 10 字段 AI 联网生成（host_affiliation / guests /
  event_summary / key_points / background / ...）
- `news.realtime` task 双 provider（xAI Grok / claude -p WebSearch）

下游 overlay 直接消费这套数据，不需要再让 AI 重跑。

---

## 1. v0.1 范围

最小可用集，把渲染管线打通：

### 1.1 两种 overlay 类型

**LowerThirdOverlay（下三分之一名牌）**
- 演讲者名牌：左下或右下条形块 + 标题（host）+ 副标题（host_bio + host_affiliation）
- 时段控制：start_sec / end_sec 决定何时出现何时消失
- v0.1 默认整段一个名牌（用户在工作台单条编辑），等 ASR diarization 之后再做切换

**ChapterRibbonOverlay（章节进度条）**
- 顶部常驻细条，显示当前章节标题
- 从 chapters.json 自动派生，无需用户手填
- 时段 = 每个章节的 [start_sec, end_sec]

**v0.1 不在范围**：
- ChapterCard（章节切换全屏弹卡 + 动效）
- PullQuote（金句弹屏 / 引用框）
- ProgressBar（底部进度条 + 章节刻度）
- 弹入弹出动效（fade in / slide）

### 1.2 渲染选型：libass 多轨方案

**决定**：再加 1-2 个 ASS dialogue 轨道，与现有字幕轨同引擎。每条 overlay 编译为
ASS dialogue，带 `\\pos(x,y)` 绝对定位 + 起止时间。

**为什么不用 drawtext+drawbox**：
- 中文字体处理已经在 libass 验过，不要再踩一次坑
- preview≡render 的契约靠 composition core 维护，libass + JS Canvas
  归一化坐标体系已经覆盖字幕，扩展 overlay 是同形扩展
- ffmpeg 单管线，性能可控

**WebView Canvas 镜像**：必须画。`composition_preview.html` 加 overlay 绘制函数，
读 ASS dialogue 时段表，按当前播放时间显示对应 overlay 矩形 + 文字。

### 1.3 工作流（v0.1）

```
1. 用户在 source pane 填 basic_info（host / host_bio / event_date / ...）
2. 用户点 news_context pane 的 ✨ AI 填充 → 拿到 host_affiliation /
   event_summary / chapters 等
3. 用户从派生作品 [+ 添加] 创建 news_desk 实例
4. news_desk 工作台打开：
   - 字幕设置（复用 subtitle_tool 的 normalized layout 控件）
   - Overlay 列表（v0.1：1 个 LowerThird 默认从 basic_info 自动填，
     N 个 ChapterRibbon 自动从 chapters 派生 ——用户可编辑可删除）
   - WebView 预览
5. 用户点导出 → composition core 渲染 → MP4 落到 derivatives/news_desk/<instance>/
```

### 1.4 落地清单（按依赖序）

| # | 文件 / 模块 | 改动 |
|---|---|---|
| 1 | `core/composition/overlays.py` | 升级现有 stub。定义 `LowerThirdOverlay` / `ChapterRibbonOverlay` 两个 dataclass。`@register_overlay_renderer("lower_third")` / `("chapter_ribbon")` 装饰器骨架 |
| 2 | `core/composition/style.py` | `overlay_styles` 加 LowerThird / ChapterRibbon 两个 class 的 schema（颜色 / 字体大小 / 边距 pct） |
| 3 | `core/composition/render.py` | overlay dispatch loop（已有 stub，填 LowerThird + ChapterRibbon 两个 renderer，生成 ASS dialogue 行） |
| 4 | `ui/composition_preview.html` | Canvas 加 `drawOverlays()`，按当前时间过滤可见 overlay，画矩形 + 文字 |
| 5 | `core/composition/presets.py` | 加 `news_desk_default.json` preset 模板 |
| 6 | `core/derivative_types.py` | 注册 `news_desk` 条目（type_name="news_desk", single_instance=False, tool_key="news_desk"） |
| 7 | `tools/news_desk/news_desk_tool.py` | 工作台壳：复用 subtitle layout 控件 + overlay 列表编辑器 + WebView 预览 + 导出按钮 |
| 8 | `VideoCraftHub.py` `TOOL_MAP` | 加 news_desk |
| 9 | `i18n/{zh,en}.json` | derivative 名称 / overlay UI 字符串 |

---

## 2. 设计决策记录（来自 part 3 规划讨论）

这些决策本应在另一次会话讨论时记录，2026-05-14 那次对话被压缩前补上：

### Q1. 形态独立 vs bilingual_video mode → **独立 type**

bilingual_video 是字幕烧录工具，UI 是"字幕参数"心智模型。news_desk 是
"信息编导"心智模型，要 overlay 编辑器、要消费章节数据、要演讲者名牌 ——
不可能塞进 subtitle_tool 还保持工具简洁。

### Q2. overlay 最小集 → **LowerThird + ChapterRibbon**

两者都是矩形 + 文字，技术风险最低。chapter_card 动效 / pull_quote 与字幕争位 /
progress_bar 刻度计算等放 v0.2。

### Q3. 数据来源 → **basic_info anchor + AI context + chapters 自动派生**

用户工作流：填 5 anchor → AI 填 10 上下文 → 创建 news_desk → 章节
overlay 从 chapters.json 自动来 / 名牌从 basic_info 自动来。**用户在工作台**
**手填的最少**。

ASR diarization（多说话人切换的 LowerThird）等 aistack 上游接入再做。

### Q4. 渲染管线 → **libass 多轨**

不走 drawtext+drawbox。复用 composition core 的归一化坐标体系。

---

## 3. v0.2+ 候选

- ChapterCard 弹屏（章节切换时全屏 1-3 秒标题卡）
- PullQuote 金句弹屏（从 hotclips 派生）
- ProgressBar 底部进度条 + 章节刻度
- 动效层（fade in / slide）
- Zone 自动避让（LowerThird 跟字幕重叠时自动上移）
- ASR diarization 多说话人 LowerThird 自动切换

均不影响 v0.1 schema，渲染层扩展即可加。

---

## 4. 不在 news_desk 范围（但相关）

**Source URL 提供链路**：news context 已 ship，basic_info / context.json 数据齐了。
news_desk 不再触碰 AI 调用，纯消费。

**publish.md 输出**：复用 `core/publish_sidecar`，新派生形态发布稿自动收益。

**AI 多轮迭代**：[BACKLOG](../../BACKLOG.md) P3 项已记，不在 v0.1。
