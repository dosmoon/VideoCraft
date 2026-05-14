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

#### ✅ 已完成：`ChapterPointCard` Broadcast L3 — 2026-05-14
- 数据来源：analysis.json 的 `chapter[].key_points[0]` 优先，否则
  `refined` 截断到 40 字
- **形态：广播 L3 半透底条**（CNN/Reuters/央视 L3，用户先 picked
  Hero-上三分之一，实测贴脸 + 无底丑陋，改下三分之一 + L3 band）
- 视觉：SimHei 40px 加粗白字 / 半透深底 #0F172A @ 78% / 左 4px 红
  accent stripe / 底条 fit 文字宽度 + padding
- 动画：bg + accent + text 三件套共享 `\move(slide_in_px=24)` lift +
  `\fad(350,300)` —— 整组当作刚体动画；canvas 用 `globalAlpha` +
  yOffset 同步镜像
- 位置：`y_pct=0.70` 下三分之一 —— 在 sub2 (80%) 上方留 5% 安全距
- 已弃用字段：`position` (4-corner) 从 dataclass 移除；dialog 不再问位置
- 工作台：手动「+ 章节卡」/「从 analysis.json 派生章节卡」批量（每段 6 秒）
- i18n: `add.chapter_point_card` / `derive_cpc` / `field.card_text` 双语

#### ✅ 已完成：日期展示 (L3 嵌入 + DateStamp 角标) — 2026-05-15
- 数据源：现成的 `basic_info.event_date` (YYYY-MM-DD)
- **L3 内嵌**：`_derive_lower_third_from_basic` 把 event_date 追加到
  subtitle 行（host_bio · affiliation · 2026-05-15）；零代码 + 跟主播
  身份信息同行
- **DateStamp 角标** = 新 overlay kind `date_stamp`，全程常驻小字
  - `DateStampOverlay`(text + start/end + position 4-corner) +
    `DateStampStyle`(SimHei 22 / 白字 / 可选半透深底 60% / 4-corner
    margin)
  - libass `_build_date_stamp_dialogues`：可选 fitted 背景 + 文字，
    无动画（"bug" 语义,持续不闪)
  - canvas mirror `_drawDateStamp`
  - 工作台「+ 日期戳」按钮 / edit dialog (文字 + 4 角位置) /
    「从 basic_info 派生日期戳」批量按钮（先清旧 DateStamp，再加新的
    持续整段，默认左下避开右上水印）
- 不采用方案 4 (每章节加日期)：用户判定章节级重复无价值
- i18n: `add.date_stamp` / `derive_ds` / `derive.no_date` /
  `field.date_text` 双语

#### ✅ 已完成：字幕位置 + 水印 UI 暴露 — 2026-05-15
- **字幕位置**：`SubtitleStyle.block_margin_pct` (距边) + `track_gap_pct`
  (双轨间距) 已存在但工作台没 UI；现在同一行 (top/bottom radio 旁) 加
  两个 % spinbox，让用户根据源条幅高度上抬字幕
- **水印**：`WatermarkStyle` 整个 dataclass 之前完全没 UI；现在工作
  台底部新 LabelFrame，4 行：(1) 启用 + 类型 (文/图 radio) + 4-corner
  位置 (2) 文字模式 (内容/字号/色/不透明) (3) 图片模式 (路径+...+缩放+
  不透明) (4) 边距 X/Y
- 两种 watermark 字段一直可见，由 `type` radio 决定渲染哪个 (跟
  `OutputGeometry` 的 reframe/passthrough 一样的 UX 模式)
- i18n: `style.sub.block_margin` / `.track_gap` + `style.wm.*` 共 15
  键双语

#### ✅ 已完成：字幕底衬（box mode）— 2026-05-15
- **动机**：白宫/CSPAN 这类源视频自带固定下三分之一 chyron（"TEXT
  VP TO 45470 FOR UPDATES…"），sub1 默认 92% Y 撞上去看不清；不愿
  动源视频 → 给字幕加底衬
- 数据：`SubtitleLineStyle` 加 `bg_color` / `bg_opacity` (0-100) /
  `bg_padding_x_pct`；默认 `bg_opacity=0` 保持向后兼容
- libass 侧：`_build_subtitle_force_style` 走 `BorderStyle=3` +
  `BackColour=&HAA{BGR}&`；padding 由 `Outline` 接管；`OutlineColour`
  跟 `BackColour` 相同 → 看起来就是一片纯平半透底
- canvas 镜像：drawSubtitles 加 measureText 算文字宽度，画 fit 矩形
  + padding；箱模式下不再叠 stroke（跟 libass 行为一致）
- 跨 derivative 受益：所有用 `SubtitleStyle` 的 derivative（subtitle
  /clip/news_desk/将来的）都自动支持，加配置就生效
- UI：暂只在 news_desk 工作台 style form 加 sub1/sub2 各一组「底衬
  色 + 不透明」(0=关)；其他工作台 UI 后续扩散
- i18n: `tool.news_desk.style.sub.bg` / `.bg_opacity` 双语

#### ✅ 已完成：工作台「渲 20s 预览」按钮 — 2026-05-14
- 位置：导出 MP4 旁边的次按钮
- 锚点：选中行的 overlay.start_sec（无选中 fallback t=0）；
  窗口 = [anchor - 2s, anchor + 18s] 共 20s，给入场动画留 2s 预热
- 输出：`output.preview.mp4`（与正式产物 output.mp4 分文件，不覆盖）
- 跳过 publish.md sidecar（预览是抛弃物，不是交付物）
- `_rebase_overlays` helper 把用户 overlay 时间线 rebase 到 [0, win_len]
  —— 因为 ffmpeg `-ss` 会把片段 timeline 归 0，字幕 SRT 已经被
  render.py 自己 rebase；overlay 之前要手动；现在新加这步

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

- ~~ChapterPointCard 全套~~：✅ 已完成
- PullQuote 全套：~1 会话（dataclass + style + libass + canvas + i18n，
  居中定位略不同，参考 ChapterPointCard 套路）
- v0.2 收尾（用户实测两种 overlay + 文档/git tag）：~0.5 会话

### 关键参考路径

- 渲染框架：`src/core/composition/news_desk_overlays.py`
  （`build_news_desk_ass` + libass 绘图模式 rect + 文本 dialogue 套路；
  ChapterPointCard 是最近的可抄作业样本）
- canvas wrap 镜像：`src/ui/composition_preview.html::_wrapTextCjk` /
  `_drawChapterPointCard`
- 数据加载：`src/core/chapters_io.load_analysis(path) -> dict`
- hotclips.json 字段：见 `src/core/subtitle_analysis_runners.py::HOTCLIPS_SCHEMA`
- 派生按钮模式：`news_desk_tool.py::_derive_chapter_cards_from_analysis`
  （照这个套路加 `_derive_pull_quotes_from_hotclips`）

### 当前会话状态

- HEAD: `ea3ab5f` + 未提交的 ChapterPointCard 改动
- 改动文件：overlays.py / style.py / news_desk_overlays.py / render.py
  / news_desk_tool.py / composition_preview.html / zh.json / en.json
  / docs/task.md
- 已通过：py_compile + ASS 构建 smoke test + JSON 解析
- **尚未做**：用户实测真实视频；待用户跑通后再 commit
- 下次（或本会话续）：用户验收 → commit；之后开 PullQuote

### 不在本任务范围（备忘）

- v0.3+ 候选见 `docs/draft/news-desk-derivative.md` 第 3 节
- B 路径（timeline 拖拽编辑）—— 等 A 完了看用户感受再定
- AI 增强 overlay（嘉宾自动派生 / 智能金句挑选） —— 暂搁
