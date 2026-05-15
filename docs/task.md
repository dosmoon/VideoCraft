# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## news_desk v0.4 + AI 输出层简化 — 已收尾上线

HEAD: `76c7342` (已 push origin/main)，workspace clean。

### 本次会话核心变化

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

参见任务系统：
- **#13** ✓ 已完成
- **#18 [P2]** 渲染层支持 N 条字幕（解锁 subtitle 组件多实例真正发挥）
- **#19 [P2]** 渲染层支持 N 个水印
- **#20** 已收尾（按"简化版"路线落地，非原计划"加时间戳"）
- **#21 [P3]** 章节"结尾小结"模式 + 段落 overlay 渲染

### 名牌组件（延后）

#13 完成后，context.json 有了 host/host_bio/host_affiliation。但仍缺**多发言人结构化数据**（speakers 列表 + 出场时段）。等到 AI 提取多发言人或新数据 schema 出现时再做。

参见 `[[project_news_desk_status]]` 关于"名牌延后"原因。

### 下一步候选

1. **#18 / #19** —— 渲染层 N-字幕 / N-水印，让 v0.4 多实例承诺真正兑现
2. 真实使用 v0.4 + AI 简化版几天，攒反馈
3. 拓展到其它工作台（clip_script、bilingual_video 用同一组件框架重构？）

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
