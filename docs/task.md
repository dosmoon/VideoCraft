# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。每个任务结束后清空或归档。

---

## 当前任务

**节目形态 #3：news_desk —— v0.2 数据层升级已完成，待开 overlay 消费方**

### v0.1 已封板（参见 git log `acc7cd1` 之前）

news_desk 派生形态完整端到端：
- LowerThird + TopicStrip 两种 overlay（libass 单 .ass 合并 + canvas 镜像）
- 双语字幕烧录（passthrough + auto_max_chars 计算）
- 工作台 UI（Hub 可打开，preset / overlay 列表 / 自动派生 / 单击 seek / 样式 form / 导出 / publish.md）
- 已用真实视频跑过验证：53 分钟新闻发布会渲染正常

### v0.2 计划（用户拍板：A 缩窄版 + B 延后）

**杠杆最大方向 A**：消费项目里**已有的非 AI 数据**生成更有信息密度的 overlay。
明确**不**做：AI 自动派生嘉宾名牌（用户判定礼貌废话无价值）。

**B (timeline 拖拽编辑) 延后**，先做完 A 看是否真的需要时间轴辅助再说。

### 已完成（2026-05-14 第四+五+六轮：架构清债 + 数据层准备）

A 路径数据准备工作连带做了几个架构清债：

1. **publish_sidecar 按 tier 拆分**（commit `9303d1c`）
   - 老 `core/publish_sidecar.py` 混了 tier-1 工具 + tier-2 派生模板（违反 core 边界）
   - 拆成：`core/markdown_fmt.py`（tier-1 fmt_dur/fmt_hashtags/t/is_zh）+
     `tools/{subtitle,clip,news_desk}/publish.py`（per-tier 模板）
   - news_desk 新增 `render_news_desk_publish` —— 三派生中信息最丰富
     （消费 basic_info + AI context + chapters + LowerThird roster）

2. **subtitle 分析 3 件套 → 单 envelope** （commit `acc7cd1`）—— **核心架构改动**
   - 之前 titles.json + chapters.json + chapter_refined.md 是同一个 AI call
     输出硬拆 3 文件 + 3 sidebar 行，消费方要 cross-reference，refined 还
     是 markdown 没法程序化消费
   - 合并到 `<iso>.analysis.json` envelope，schema_version=2
   - **新增 AI 字段** `chapter[].key_points: list[str]` (3-5 条 ≤25字 短要点)
   - Registry 6 → 4：analysis / transcript / chapter_transcript / hotclips
   - Runner 3 → 1：`run_pack_analysis`
   - chapter_editor 加只读 AI 详情面板（refined + key_points）
   - **不做向后兼容**：旧项目要重新生成

3. **analysis preview 标题条压缩**（commit `ea3ab5f`）
   - 候选标题不是焦点，从顶部 200px 块压成底部 50px 灰色细条

### 下一步：v0.2 overlay 消费方实现

数据底座齐了（analysis.json 含 chapter.refined + chapter.key_points；
hotclips.json 含 hook/start/end/score）。下面要做的是**新增两种 overlay
kind 把这些数据渲到视频上**：

#### 待开发：`ChapterPointCard`（章节摘要小卡）
- **数据来源**：`subtitles/<iso>.analysis.json` 的 `chapter[].refined` 或 `key_points[i]`
- **形态**：章节切换时左/右下角弹出 5-8 秒 1-2 行小卡，显示精炼摘要前 ~40 字
- 新 dataclass `ChapterPointCardOverlay`（参考 LowerThirdOverlay 套路）
- 新 style class `ChapterPointCardStyle`
- libass 渲染（沿用 `core/composition/news_desk_overlays.py` 框架）
- canvas 镜像
- 工作台新按钮"从 analysis.json 派生章节卡"

#### 待开发：`PullQuote`（金句弹屏）
- **数据来源**：`subtitles/<iso>.hotclips.json` 的 `hook` 字段 + `start`/`end`
- **形态**：hotclip 时段中段，屏幕中央偏上短暂 (3-5 秒) 大字 + 半透明黑底
- 新 dataclass `PullQuoteOverlay`
- 新 style class `PullQuoteStyle`
- libass 渲染（中央定位，比 LowerThird 略复杂）
- canvas 镜像
- 工作台新按钮"从 hotclips.json 派生金句"

#### 嘉宾标签 → 不做
用户判定 `refined` 自由文本识别人物不靠谱，v0.2 跳过。如果未来用户实测
发现稳定模式，再考虑加 v0.3 regex pass。

### 实现成本估算

- ChapterPointCard 全套：~1 会话（dataclass + style + ASS builder + canvas + i18n）
- PullQuote 全套：~1 会话（同上，居中定位略不同）
- 工作台两个派生按钮 + edit dialog 调整：~0.5 会话

合计 **~2.5 会话**。建议下次会话开 ChapterPointCard。

### 关键参考路径

- 渲染框架：`src/core/composition/news_desk_overlays.py`
  （`build_news_desk_ass` + libass 绘图模式 rect + 文本 dialogue 套路）
- 数据加载：`src/core/chapters_io.load_analysis(path) -> dict`
- analysis.json 字段：见 `src/core/chapters_io.py` 模块 docstring
- hotclips.json 字段：见 `src/core/subtitle_analysis_runners.py::HOTCLIPS_SCHEMA`
- 工作台模式：`src/tools/news_desk/news_desk_tool.py::_derive_topic_strips_from_chapters`
  （照这个套路加 `_derive_chapter_cards` 和 `_derive_pull_quotes`）

### 当前会话状态

- HEAD: `ea3ab5f`（已 push 到 origin/main）
- workspace clean
- v0.2 数据底座完成，UI 测试用户已确认渲染输出 OK
- 下次开 ChapterPointCard 实现

### 不在本任务范围（备忘）

- v0.3+ 候选见 `docs/draft/news-desk-derivative.md` 第 3 节
- B 路径（timeline 拖拽编辑）—— 等 A 完了看用户感受再定
- AI 增强 overlay（嘉宾自动派生 / 智能金句挑选） —— 暂搁
