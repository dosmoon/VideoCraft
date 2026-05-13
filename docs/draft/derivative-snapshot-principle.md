# 派生层快照原则

> 状态:活文档 v1.0 / 2026-05-13
> 范围:`derivatives/*` 所有派生类型的上游依赖处理约定
> 关联:`composition-style.md`(阶段一/二 composition 设计)、`project-restructure.md`(项目模型基础)

---

## 一句话

**派生 = 上游决策的瞬间承诺。**派生创建时,把所有"决策性"上游产物复制到自己目录;后续渲染只读自己快照,**永远不读当前上游**。上游怎么变都不会污染派生。

## 为什么这是个问题

VideoCraft 的项目模型:

```
<project>/
├── source/video.mp4
├── subtitles/
│   ├── <lang>.srt              # ASR / 翻译产物,可重新生成
│   ├── <lang>.hotclips.json    # AI 主观选片,可重新生成
│   ├── <lang>.chapters.json    # AI 章节,可重新生成
│   ├── <lang>.titles.json      # AI 标题,可重新生成
│   ├── <lang>.transcript.md    # 从 SRT 算的非 AI 产物
│   └── ...
└── derivatives/
    ├── clip/<inst>/             # 消费 hotclips + SRT
    ├── bilingual_video/<inst>/  # 消费 SRT
    └── (未来:摘要/解读/对话/剧场/...)
```

任何一份 `subtitles/*` 产物都可能被用户在主界面"重新生成"覆盖:
- 重跑 ASR → SRT 变(timing/punctuation 可能完全不同)
- 重跑 hotclips → AI 选片结果完全不同(切片数量、起止、hook 全变)
- 重跑 chapters → 影响 chapter_transcript / chapter_refined 级联

**而派生层往往用"位置索引"等隐式契约引用上游内容**——比如 clip 派生用 `clips_overrides[3]` 给 hotclips 第 3 条 clip 配 crop / hook 覆盖。上游变了之后,索引 3 指向的就是完全不同的 clip,**用户辛苦做的覆盖被静默套到无关 clip 上**。这是产物侧最危险的 silent corruption。

## 解决思路对比

| 方案 | 思路 | 复杂度 | 兜底 |
|---|---|---|---|
| A. fingerprint keying | 给每条 hotclip 算内容指纹,overrides 按指纹存,上游变化时按指纹重对应,失配项标 orphan | 高(每个 cascade 点都要做) | 中(改名/字段微调还是会失配) |
| B. 覆盖前警告 | 重新生成时检查"是否有派生绑定本文件",有则弹窗让用户决定覆盖/取消 | 中 | 弱(用户没意识到关联;UI 链路长) |
| C. **派生快照上游(本 doc)** | 派生创建时复制依赖产物到自己目录,渲染只读快照 | 低 | 强(架构层消除问题,根本不会跨派生污染) |

**选 C**。

## 原则细则

### 该快照的(决策性上游)

| 产物类型 | 快照名 | 派生消费者 |
|---|---|---|
| `subtitles/<lang>.srt` | `source-subtitles.<lang>.srt` | clip / bilingual_video / 未来文字稿派生 |
| `subtitles/<lang>.hotclips.json` | `source-hotclips.<lang>.json` | clip |
| `subtitles/<lang>.chapters.json` | `source-chapters.<lang>.json` | 未来 摘要 / 解读派生 |
| `subtitles/<lang>.titles.json` | `source-titles.<lang>.json` | 未来 上传脚本派生 |
| `subtitles/<lang>.chapter_refined.md` | `source-chapter-refined.<lang>.md` | 未来 解读派生 |

命名规则:`source-<上游类型>.<lang>.<原扩展>`,放在 `derivatives/<type>/<inst>/` 目录根下。

### 不快照的

| 类型 | 原因 |
|---|---|
| `source/video.mp4` | 文件巨大(GB 级);视频换源 = 项目级语义变,派生应失效要求重建,而不是自动跟随 |
| `subtitles/<lang>.transcript.md`、`<lang>.chapter_transcript.md` | 非 AI,deterministic;只要 SRT 已快照,派生内现场重算即可 |
| `.videocraft/project.json` | 共享元数据 |
| `source/context.json` | 用户主动编辑,稳定;改了应该影响所有派生(brand 一致性) |

### 快照时机

**lazy + 写入即落盘**:

- 派生第一次需要某项依赖时复制一次(用户切语言下拉 → 触发该语言的所有快照)
- 已快照的文件**不重复复制**,上游变化不影响已快照
- 操作幂等:`_ensure_snapshot(lang)` 反复调用安全

### 用户视角的行为

| 操作 | 结果 |
|---|---|
| 用户重新生成上游 hotclips/SRT | **已建立的派生完全不变**,因为读自己快照 |
| 用户想用新上游做新切片 | 建一个新派生(`clip/v2`),它快照当下最新上游 |
| 上游产物被用户手动删除 | 派生还在 + 仍可工作,因为快照独立 |
| 用户在派生里改 overrides | 全部基于本派生的快照内容,索引永远稳定 |
| 用户想把派生"重新关联"到当前上游 | (未实现 / 未来 feature)手动按钮触发,带 override 丢失警告 |

## 实施进度

| 派生 | 状态 | 备注 |
|---|---|---|
| `clip` | ✅ 已落地(2026-05-13) | hotclips + SRT 双快照,`tools/clip/clip_tool.py:_ensure_snapshot` |
| `bilingual_video` | ⏳ 待办(阶段二) | 跟 subtitle_tool → composition 迁移一起做;老 instance 加一次性 backfill |
| 未来 4 种节目稿派生 | 📝 设计阶段直接铺 | 摘要 / 解读 / 对话 / 剧场,创建时按各自依赖列表快照 |

## 派生类型新增 checklist

新加派生类型时,先回答:

1. 这个派生消费哪些上游产物?(列出来)
2. 列出来的每一项,**是否决策性**(AI 主观 / ASR 主观 / 易变)?决策性的必须快照
3. 在 `core/derivative_types.py:REGISTRY` 加注 `snapshot_inputs: list[str]`(将来考虑加这个字段,统一抽象;现在每个派生自己管也行)
4. 派生工作台 `__init__` 或第一次进入时调用快照逻辑
5. 所有读上游的代码点改成读快照
6. 测试:第一次创建 → 看 instance 目录有快照;改上游 → 派生继续用旧的;新建第二个 instance → 它快照当下新版

## 边界 / 不在本原则范围

- 跨派生共享上游(SRT 在不同派生里**各自快照一份**,不去重)— 简单可靠,空间代价可接受
- 多份快照同步问题(派生 A 和派生 B 都快照了 SRT,后来用户在派生 A 里编辑了字幕)— 派生间不互通,**每个派生只对自己负责**
- 用户主动改派生快照(直接编辑 `source-subtitles.<lang>.srt`)— 允许,这就是"派生自治"的合理操作

## 相关文档

- `composition-style.md` — composition core 设计,阶段一/二的样式 + 渲染层
- `ai-clip-redesign.md` — 切片两层架构(分析层 + 派生层)
- `project-restructure.md` — 项目模型基础
