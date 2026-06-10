# 派生作品 publish 配套文件 Plan

> 解决两个派生场景的"导出内容信息缺失"痛点：
> 1. **字幕烧录**：发布到 YouTube 需要手动回源项目找标题、描述、章节，章节首章还要修 00:00（已被 Phase A 修掉）
> 2. **切片**：输出一堆 `clip_001.mp4` `clip_002.mp4`，要开 VSCode 一个一个看 JSON 才知道哪个是哪个；发布到 X 还得手抄 transcript 写稿

## 核心判断

**这不是数据缺失，是导出格式缺失**。所有需要的数据**已经在源项目和 sidecar JSON 里**：
- 章节：`subtitles/<iso>.chapters.json`（Phase A 修过首章 00:00）
- 标题：`project.meta.source.title` + AI 生成的 `titles.json`
- 切片标题/hashtags/hook/outro/score：已经在 `clip_NNN.json` 里
- 切片原对白：已经在源 `hotclips.json` 每条 clip 的 `transcript` 字段里（但**没传递到 sidecar JSON**——这是个小 bug，要顺手修）

修复路径就是**在导出层 join 这些数据，落盘成人眼直接可读、可复制到发布工具的 Markdown**。

## 文件产物

### 1. 字幕烧录 — 一个 `publish.md`

落点：`derivatives/bilingual_video/<instance>/publish.md`，跟 `output.mp4` 同目录

内容样板：

```markdown
# {标题}

> Source: {source.url 如果存在}
> Rendered: 2026-05-13 11:42

## YouTube Description

{这里留空 / 或塞一段 AI 生成的简介—— v0 留空，让用户手填}

## Chapters

00:00:00 开始
00:00:08 介绍
00:02:30 主要话题
00:08:15 总结

## Tags

{暂无 tag 体系——v0 留 placeholder}

## Adapted SRTs

- subtitles_zh.srt
- subtitles_en.srt
```

**关键**：Chapters 段直接是 YouTube description 章节格式（`HH:MM:SS Title`，一行一个，首行必 00:00），用户 ctrl+a / ctrl+c 整段粘到 YouTube description 框里就行。

### 2. 切片 — 一个 `index.md` + 每切片一个 `clip_NNN.md`

#### `derivatives/clip/<instance>/index.md`（**总览**，解决"开 vscode 找编号"）

```markdown
# {项目名} — Clips Index ({instance})

> 12 clips · rendered 2026-05-13

| #   | Title                          | Duration | Score | File |
|-----|--------------------------------|----------|-------|------|
| 001 | "AI 是不是泡沫？" 段子          | 0:45     | 9     | [clip_001.mp4](clip_001.mp4) |
| 002 | 老黄笑场                       | 1:12     | 8     | [clip_002.mp4](clip_002.mp4) |
| 003 | 数据中心电费暴论                | 0:38     | 7     | [clip_003.mp4](clip_003.mp4) |
...
```

→ 用户打开这一个文件就能扫一眼知道每个编号是什么。

#### `derivatives/clip/<instance>/clip_001.md`（**发布稿**，解决"X 平台抄稿子"）

```markdown
# {suggested_title}

**Duration**: 0:45 · **Score**: 9/10

## Hook

{hook 文案}

## Caption (X / TikTok ready)

{suggested_title}

{transcript 全文}

{#hashtag1 #hashtag2 #hashtag3}

## Outro

{outro 文案}

## Why this clip

{why_viral}

---

Source: clip_001.mp4 · {start_sec}-{end_sec} of source · {project.meta.source.title}
```

**Caption 段是单独成区**——用户 ctrl+a 一段直接粘到 X 发文框就完事，原对白 + 标题 + hashtag 一次性。

## 数据流修复

**Bug**: `clip_NNN.json` 当前没保留 `transcript` 和 `why_viral`。clip_tool.py:1901-1912 只挑了 title/hashtags/hook/outro/score。修一下，把这两个字段也存进去——下游 publish.md 才能直接读 sidecar，不用回头再 join hotclips.json。

## 实现拆分

1. **C1**：`core/publish_sidecar.py` 新模块。两个纯函数：
   - `render_bilingual_publish(project, instance_dir, chapters, titles, srt_paths) -> str` 返回 markdown 文本
   - `render_clip_publish(project, clip_sidecar, instance_dir) -> str` 单个切片
   - `render_clip_index(project, instance_dir, clip_sidecars) -> str` 总览
   纯函数好测，不用 mock UI

2. **C2**：clip_NNN.json 字段补全（加 `transcript`, `why_viral`），clip_tool.py 改一处

3. **C3**：烧录 hook 进 publish.md 生成
   - subtitle_tool.py 烧录成功后调用 publish_sidecar.render_bilingual_publish + 写盘
   - 章节来自源 `<lang>.chapters.json`（如果存在）
   - 标题取 `project.meta.source.title`

4. **C4**：切片 hook 进 publish.md 生成
   - clip_tool.py 每次单个切片渲染成功后写 clip_NNN.md
   - 全部切片渲染完后/或每次更新后重写 index.md（增量也行——instance 目录下扫所有 *.json 即可）

5. **C5**：i18n keys（Markdown 模板里的固定文本：章节标题、Source、Duration、Score 等）。**所有 publish.md 内容用源项目的语言写**，不跟 UI 语言走——发布稿要跟视频语言匹配，不是用户 UI 偏好。

## 设计决议（要先对齐）

1. **publish.md 是 v0 模板**：先把数据组装起来落盘，**不做 AI 生成 description/标签**。AI 调用本来就慢、贵、不可控，发布稿这种东西用户多半要自己改。后续如果用户觉得有价值，可以加个"AI 优化发布稿"按钮单独触发。
2. **publish.md 不可逆覆盖**：每次烧录/切片成功就覆盖一次。**不保留历史**——理由：用户改过的 description 应该在 YouTube 上，不该回流到这里；这里永远是"最新一次渲染产物对应的发布模板"。
3. **publish.md 内容语言**：跟随源项目 `language.source`（zh → 中文文案；en → English；其他 → fallback 英文）。同上一条，跟 UI 语言无关。
4. **index.md 用 Markdown 表格 vs YAML/JSON 列表**：表格——Markdown 渲染器（GitHub、VSCode 预览、Obsidian、所有平台）都支持，扫起来快。
5. **是否在 Hub sidebar / 工作台里加打开按钮**：v0 不加，文件落盘就够；用户在 Explorer 里打开 .md 文件是已知行为。后续可以加一个"打开发布稿"按钮如果需要。
6. **生成失败的处理**：失败不影响主渲染流程——publish.md 写盘 try/except wrapper，失败只记 log，不报错给用户。视频已经渲染出来了，sidecar 是 nice-to-have。

要不要按这个干？还是先调具体方案某个点？
