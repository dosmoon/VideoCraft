# VideoCraft Backlog

> 开发计划看板（权威）。优先级：🔴 P1 必须做 / 🟡 P2 重要增强 / 🟢 P3 体验提升；状态：`[ ]` 待开始 / `[~]` 进行中。
> **当前任务接力**看 [`task.md`](task.md)；已完成 / 已失效 / 历史裁决全文在 [`_archive/backlog-archive-01_2026-04_2026-06.md`](_archive/backlog-archive-01_2026-04_2026-06.md)（2026-06-10 拆出）。

---

## ▶ 下一大功能

**录播自动剪辑**：source 加录播 → ASR → AI 全自动剪裁 / 章节 / 切废段 / 过渡；per-品类插件；OTIO 多段装配的真实需求来源（crop-on-Clip 已落地 IR 地基，[ADR-0011](adr/0011-spatial-crop-clip-transform.md)）。从设计稿起步，见 [`task.md`](task.md)「下一任务」。

---

## 待办

| 优先级 | 状态 | 功能 | 说明 |
|--------|------|------|------|
| 🟡 P2 | [~] | 派生层快照原则普及到所有派生类型 | 原则见 [docs/design/derivative-snapshot-principle.md](design/derivative-snapshot-principle.md)。**已落地**：clip（hotclips + SRT 双快照）、news_desk（chapter schedule + titles + SRT 全快照）。**待办**：(a) 未来节目稿派生（摘要 / 解读 / 对话 / 剧场）设计时按各自依赖列表铺；(b) news_desk image_watermark 还在引用模式（用户文件路径，未本地快照）—— ADR-0003 灰区，等用户报"换图旧产品跟着变"再做 |
| 🟡 P2 | [ ] | AI Router Auto 模式必要性审视 | 2026-05-14 修掉静默 fallback 后，只有用户主动选 `⚡ Auto` 才走 candidate 循环。但 Auto 槽位本身是否还有存在必要？翻译/字幕后处理用户实际都指定具体 provider。考虑：(a) 评估各 task 用 Auto 的真实场景 (b) 无价值则下线，简化 task_routing schema (c) 保留则在 UI 明示"Auto = 授权自由换 provider" |
| 🟡 P2 | [ ] | 内嵌 AI：首启 / 升档 UI | 首启可跳过下载向导（强引导非强制，[[feedback_no_forced_downloads]]）；推荐档升档对话框 |
| 🟡 P2 | [ ] | AI 控制台加 GPU 状态 pane | 显示 cuda_status() 输出（device_name / VRAM / wheel）让用户清楚走的 CPU 还是 GPU |
| 🟢 P3 | [ ] | ASR / TTS Test 真实施 | AI 控制台 Lemonfox / Fish Audio 的 Test 目前缺位。需要：(a) ASR — 内置 1 秒静音样本 wav，Test 拿它打 provider；(b) TTS — provider 配置加 `test_voice_id` 字段，Test 调短文本合成 |
| 🟢 P3 | [ ] | 节目形态扩展：摘要 / 解读 / 对话 / 剧场 | 4 种未来创作插件（旧 core/program「稿子层」方案已废，按创作插件 + OTIO composition 架构重新设计，见归档卷「旧节目生成规划」）。对话形态的多角色 TTS 依赖已具备 |

---

## 探索方向（记录，暂不实现）

| 功能 | 说明 |
|------|------|
| 合成视频高级功能 | 音效叠加、多层视频叠加，如背景音乐、B-roll 覆盖等 |
| AI 智能排版融合 | 自动字幕排版、智能场景切换建议等 |
| CLI / AI 对话驱动视频合成 | 通过 AI 对话调用既有素材与工具合成视频，类 agent 驱动的视频生产线 |
| 新闻档案 AI 迭代会话 | `source_context_ai.extract()` 当前单次替换（无状态）。若要"针对某字段再深挖"的交互式优化：(a) Responses API 多轮 session（xAI 支持 `previous_response_id`）(b) UI 加对话区 (c) token 预算。眼前不做 —— 单次质量够用，迭代收益不抵成本 |

---

## 需求池子（未评估，先记录）

| 需求 | 说明 |
|------|------|
| subprocess 编码规范持续观察 | 2026-04-18 统一修过 13 处后，新增外部进程调用须显式传 `encoding="utf-8", errors="replace"`。观察：(a) 是否再冒 `_readerthread UnicodeDecodeError`；(b) 若反复出问题，抽 `core/shell.py` 统一 wrapper。当前刻意不做 wrapper |
| 全工程中文注释英文化 | 存量 .py 中文注释统一改英文（新代码已按规范英文） |
| 开发规范文档整理 | 代码风格、文档规则、命名规范等，待产品稳定后统一整理 |
| 字幕文件命名规则优化 | ASR/翻译产出的中英文 SRT 文件名存在可读性或冲突问题，需重新梳理（后缀语义、与烧录输出的区分） |
| i18n：en.json 翻译质量打磨 | 当前 en 为"够用即可"水准，待有真实英文用户反馈后统一 review 用词、语气、术语一致性 |
| Buffer 多平台发布中转集成 | 经 Buffer GraphQL API 扩展发布到 11 平台，绕过 X 官方 API 17 条/天硬上限。详见 [docs/draft/buffer-publishing-integration.md](draft/buffer-publishing-integration.md) |

---

## 暂缓 / 不做

> 短版备忘，**完整理由与裁决日期见[归档卷](_archive/backlog-archive-01_2026-04_2026-06.md)**——翻案前先读全文。

| 功能 | 一句话原因 |
|------|------|
| 云化 / SaaS | 算力 / 并发 / 成本三重问题 |
| Docker 分发 | 目标用户无 Docker 背景 |
| 跨平台（短期） | Windows-first，Mac 需求出现再议 |
| 批量处理 | 先做单文件质量 |
| PPT / Slidev 转视频 | 受众错位；要做也另起新软件（与 media-segment-composer 草稿是两回事） |
| AI 响应缓存 (X4) | 无重复输入 loop 场景；等 agent 类功能再补 |
| 拆出独立仓库 easy-ytdlp | yt-dlp 留作内部组件支撑一站式体验；出问题再重启讨论 |
