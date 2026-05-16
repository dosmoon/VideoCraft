# ADR-0001: 章节存活在 analysis.json envelope

- **状态**: Active
- **决定日期**: 2026-05-14

## 决定

AI 标题与章节产物合并为单一 envelope 文件 `<iso>.analysis.json`（`schema_version: 2`），不再拆 `titles.json` + `chapters.json` + `chapter_refined.md` 三件套。所有章节写入路径**必须**经过 `core/chapters_io.py` 的 `save_analysis*` 函数，统一过 `normalize_chapters` 不变量。

Envelope 结构：

```json
{
  "schema_version":  2,
  "generated_at":    "...",
  "source_subtitle": "zh.srt",
  "titles":          ["候选标题1", ...],
  "chapters": [
    {
      "start": "HH:MM:SS", "start_sec": float,
      "end":   "HH:MM:SS", "end_sec":   float,
      "title": "...",
      "refined":    "≤128字精炼摘要",
      "key_points": ["≤25字短要点", ...]
    }
  ]
}
```

## 为什么

之前三件套同源（一次 AI call 产出）硬拆 3 文件 + 3 sidebar 行，消费方要 cross-reference 才能拼齐数据；`chapter_refined.md` 是 markdown 没法程序化消费，overlay 等下游想用 refined+key_points 时还得反解。合并后：

- 单文件、单 sidebar 行，UI/存储复杂度都降
- `refined` + `key_points` 直接挂在 chapter 上，下游（publish sidecar、news_desk overlay、Hero Card）`load_analysis()` 一次拿全
- 单一规范化入口确保 AI 生成路径和 UI 编辑路径用同一套不变量，不会出现"AI 写的能过校验，用户编辑保存的过不了"

按用户决议**不做向后兼容**——未发布项目不需要养垃圾代码；旧项目用户在 sidebar 重点一次"标题与章节"即可重生。

## 如何应用

- **写章节**: 调 `core.chapters_io.save_analysis(...)`（全 envelope）或 `save_analysis_chapters_only(...)`（保留 titles[]，只更 chapters）。自带 normalize + atomic write，不要绕过直接写盘
- **读章节**: `load_analysis(path).get("chapters")`，每章自包含，不需要 join 别的文件
- **改不变量**: 动 `chapters_io.normalize_chapters()` 一处即可，AI 生成和 UI 编辑同时受益

`normalize_chapters` 强制四不变量：

1. 首章 = `00:00:00`（YouTube 强制）。第一章 start > 0 时自动 prepend intro chapter，标题按 `lang_iso` 选「开始」/「Intro」
2. 章节按 start 升序
3. 每章 `end` = 下一章 `start`；最后一章 `end` = SRT 最后 cue 的结束时间
4. 退化章节（`end ≤ start`）自动丢弃
5. `refined` + `key_points` 在 normalize 过程中穿透不丢失（2026-05-14 新增），保证用户改 start/title 不影响 AI 字段

章节验真 + 编辑 UI 在 `src/ui/chapter_editor.py`，preview tab 0 单击 analysis.json artifact 时挂载。
