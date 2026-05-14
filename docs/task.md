# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## news_desk 派生形态 v0.2 —— 几乎收尾，只剩 PullQuote

### 已完成（v0.2 4/5）

| 项 | 形态 | 数据源 | 关键 commit |
|---|---|---|---|
| **ChapterPointCard** | 广播 L3 半透底条（CNN/Reuters 风格）+ fade+lift 入场 | analysis.json `chapter[].key_points[0]` 或 `refined[:40]` | `146d53c` |
| **字幕底衬 (box mode)** | libass `BorderStyle=3` 半透底，每条 cue 一个 fit rect | UI 配置 `bg_color` + `bg_opacity` | `6227d19` |
| **字幕位置 + 水印 UI** | `block_margin_pct` / `track_gap_pct` 暴露；WatermarkStyle 全字段暴露；水印 z_order 抬到 60 高于 news_desk overlay | UI 配置 | `39ca6e4` |
| **日期展示** | (a) `_derive_lower_third_from_basic` append event_date 到 subtitle (b) DateStampOverlay 持续角标 | `basic_info.event_date` | `5bc249f` |

附加：
- 工作台「渲 20s 预览」按钮（`output.preview.mp4` / 选行作锚点 / lead-in 2s）—— `146d53c`
- 弃用方案：「Hero 上三分之一」「TopicStrip 章节前缀加日期」（用户判定不合适）

### v0.2 还差 1 项 —— `PullQuote`（金句弹屏）

- **数据来源**：`subtitles/<iso>.hotclips.json` 的 `hook` 字段 + `start` / `end`
- **形态**：hotclip 时段中段，屏幕中央偏上短暂 (3-5 秒) 大字 + 半透明黑底
- **抄作业模板**：ChapterPointCard L3 band 那套套路（dataclass + style + libass builder + canvas mirror + workbench add/derive 按钮）；定位逻辑改成「中央偏上」而非「下三分之一」
- 估计：~1 会话

### 当前会话状态

- HEAD: `5bc249f`（已 push origin/main）
- workspace clean
- 用户已实测 v0.2 现有功能 OK（截图验过 watermark / L3 / TopicStrip / 字幕底衬都正常烧录）
- 下次：开 PullQuote 或先 v0.3 优先级讨论

---

## 已知潜在 bug（next-session 顺手清）

`src/tools/subtitle/subtitle_tool.py` 有 4 处 `logger.debug` / `logger.exception` 调用——HubLogger 不支持这俩方法（只有 `info/warning/error`），命中任何错误路径就会再抛 `AttributeError`。新 news_desk 类似问题已在本会话修掉，subtitle_tool 还遗留。

行号（截至 `5bc249f`）：
- `491` / `517` / `652` — `logger.debug(...)` → 改 `logger.warning(...)`
- `1444` — `logger.exception("Subtitle burn failed")` → 改 `logger.error(...)` + `traceback.format_exc()`

---

## 关键参考路径

- 渲染框架：`src/core/composition/news_desk_overlays.py`
  - `build_news_desk_ass` 是合并 .ass 入口；新 overlay kind 加 dispatch 分支
  - 最新可抄作业的两个 builder：
    - `_build_chapter_point_card_dialogues`（L3 band + 3 层 dialogue 共享 `\move`+`\fad`）
    - `_build_date_stamp_dialogues`（无动画 / 可选背景的最简版）
- canvas 镜像：`src/ui/composition_preview.html`
  - `_drawChapterPointCard` / `_drawDateStamp`；wrap helper `_wrapTextCjk`
- 数据加载：
  - chapters → `src/core/chapters_io.load_analysis()`
  - hotclips → `subtitles/<iso>.hotclips.json`（schema 见 `subtitle_analysis_runners.py::HOTCLIPS_SCHEMA`）
- 派生按钮模式：`news_desk_tool.py::_derive_chapter_cards_from_analysis`（一段一条 + 幂等清旧 + 错误对话框）
- 工作台 style form：`_build_style_form` / `_build_sub_row` / `_apply_style_to_vars` / `_on_style_var_changed` 是四件套，新加 style 字段必须四处都改

---

## 不在本任务范围（备忘）

- v0.3+ 候选见 `docs/draft/news-desk-derivative.md` 第 3 节
- timeline 拖拽编辑（B 路径）—— v0.2 全部完成后再评估，看用户是否真需要
- AI 增强 overlay（嘉宾自动派生 / 智能金句挑选）—— v0.3 暂搁
