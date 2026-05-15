# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## news_desk N-字幕 / N-水印 渲染 + 预览 — 已收尾上线

HEAD: `60bb0f0` (已 push origin/main)，workspace clean。

### 本次会话核心变化

#### 过期文案清扫（60bb0f0）

N-字幕/N-水印上线后,组件 docstring + UI hint label + zh/en i18n 仍说"前 2 条字幕、首个水印"——对用户和未来 Claude 都是误导。

- subtitle.py: 模块 + `_to_render_fragment` docstring 改写;property panel 底部的 `render_hint` Label 删掉
- text_watermark.py / image_watermark.py: docstring 改写为"全部走 extra_watermarks"
- i18n zh/en: 删除 `tool.news_desk.subtitle.render_hint` key

#### 渲染层 N-字幕 / N-水印（d1ea5da）

推翻"前 2 字幕→sub1/sub2，首个水印→style.watermark，其余丢弃"的限制。news_desk 工作台里组件的多实例承诺真正兑现到端到端。

**render.py:**
- 新 dataclass `ExtraSubtitleSpec`（srt_path + line + position + block_margin_pct），每条独立锚（无共享 track_gap），匹配 news_desk 组件模型
- `CompositionRequest` 加 `extra_subtitles` / `extra_watermarks` 列表
- 老 `source_srt` / `source_srt_secondary` + `style.watermark` 不动 — clip + bilingual subtitle burn 继续走 2 轨共享布局路径
- `_named_overlay_jobs` 每条 extra subtitle 发独立 libass job（自带 MarginV/Alignment），每个 extra watermark 发 drawtext/overlay job

**news_desk_tool:**
- `_build_render_inputs` 不再 first-2/first-1 截断，全部走 N-track
- sub1/sub2 + style.watermark 留禁用

**WebView 预览（composition_preview.html + preview.py）:**
- 新 `setExtraSubtitles` / `setExtraWatermarks` JS API，跟渲染同构
- `drawSubtitleLine` / `drawSingleWatermark` 抽出复用 helper
- `drawSubtitles` 不再 sub1+sub2 都 null 时早 return（不然 extras 走不到）
- 图片水印用 `new Image()` + file:// 真加载，缓存按 path；加载中才显示占位框

### 上次会话遗留（仍生效）

#### 1. news_desk v0.4 components-based 重构（76a65e4）

推翻了 v0.3 的"全片属性 vs 时间组件 (A/B 类)"假分类。整个工作台收敛到一个原语：**组件**。

UI 三栏：list / preview / property panel。绝不再加折叠组、按类型分组、"默认样式"框。

4 个组件实现：
| kind | 实例数 | 数据源 | 视觉 |
|---|---|---|---|
| chapter | singleton | analysis.json chapters | top_strip / start_card 多选 |
| subtitle | N | 各 1 SRT | 1 |
| text_watermark | N | 字面值 | 1 |
| image_watermark | N | 图片路径 | 1 |

延后：**名牌**（等 context.json 真有结构化发言人数据）

详见 `[[project_news_desk_status]]`、`[[feedback_no_code_structure_in_ux]]`。

#### 2. context.json 升级（fe8b3d1）

basic_info.json 重新定位为**用户给 AI 的线索（可能错）**，context.json 是**AI 校正后的权威版本**。
- SourceContext 加 5 个 anchor 字段（host / host_bio / event_date / event_location / episode_topic）
- 总 15 字段
- AI 必须搜索核实并输出权威值（"Vance" → "JD Vance"）
- combined_dict 优先级翻转：context 非空胜 basic_info
- 下游统一读 combined_dict

#### 3. AI 输出层简化（76c7342）

`subtitle.pack` 任务从"一锅 5+ 分钟"降到 "2.1 分钟"：
- key_points 从 list[dict{text, start_sec, end_sec}] **回退**到 list[str]（移除时间戳要求）
- 章节组件砍掉 `key_points_popup` 视觉模式
- ClaudeCode 提供商加 `--effort low` lean 模式（subtitle.post 走它）
- 实测全片 53 分钟 SRT：Sonnet + low effort + 简化 prompt = **125.9s, 29 章节, 90 key_points**

经验：不要让单次 AI 调用做太多事；不要硬要 AI 做"程序工种"（如逐 cue 找时间戳），AI 会逃避或思考爆炸。

### 当前打开的任务（按优先级）

- **#13 / #18 / #19 / #20 / 文案清扫** ✓ 已完成
- **#21 [P3]** 章节"结尾小结"模式 + 段落 overlay 渲染

### 名牌组件（延后）

#13 完成后，context.json 有了 host/host_bio/host_affiliation。但仍缺**多发言人结构化数据**（speakers 列表 + 出场时段）。等到 AI 提取多发言人或新数据 schema 出现时再做。

参见 `[[project_news_desk_status]]` 关于"名牌延后"原因。

### 下一步候选

1. **真实使用攒反馈** — N-字幕/N-水印 + AI 简化版连用几天，看预览/烧录有没有边界 bug
2. **#21 P3** 章节"结尾小结"模式
3. **章节组件其它视觉模式** v0.4 砍了 `key_points_popup`，可能要补别的章节呈现方式
4. **组件框架推广** clip_script / bilingual_video 用同一 components-based 重构（大工程，先观察 news_desk 几周再决定）
5. **多发言人结构化数据 → 名牌组件** 等 AI 提取多发言人或新数据 schema 时再做

让用户决定。

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 修 ComponentSpec 改组件原语前回看 `[[feedback_no_code_structure_in_ux]]`
- AI 任务设计前看 `[[feedback_ai_call_budget]]` + `[[reference_claude_cli_options]]`

---

## 不在本任务范围（备忘）

- v0.3 设计文档 `docs/draft/news_desk-ux-v0.3.md` **已被 v0.4 模型推翻**——A/B 分类、模式选择那部分错了
- timeline 拖拽编辑——v0.4 砍掉了，列表顺序 = z-order，足够
- 名牌 / PullQuote / 引文 / 数据卡 等新组件——等需求清楚再加
