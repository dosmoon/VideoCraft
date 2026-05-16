# ADR-0003: 派生作品全面解耦——上游=数据准备，下游=独立编辑器

- **状态**: Active
- **决定日期**: 2026-05-16

## 决定

VideoCraft 形态正式切分两层：

1. **数据准备层（source）**：源视频 + 字幕（SRT）+ AI 分析产物（analysis.json / hotclips.json）+ 节目背景（context.json）。职责是把"一份原始素材"加工成**可被多个下游消费的标准化数据**。
2. **编辑器层（derivative）**：news_desk、clip_script、bilingual_video 等。**不再是"派生作品"**——它们是**独立的视频编辑功能模块**。每个模块**显式从数据层导入**所需材料，导入后**只读自己的本地副本**，跟上游解耦。

「派生作品」这个 UI 词汇保留（用户已习惯），但架构语义和代码上把它当作**独立编辑器**对待。

## 为什么

之前没说清楚边界，结果同一个模块内部出现风格分裂：

- **news_desk/chapter 组件**：导入即快照（`_import_from_analysis` 把章节复制进 `instance["schedule"]`）。✓ 解耦
- **news_desk/subtitle 组件**：只存 SRT 路径，渲染时**实时读** upstream 文件。✗ 还在引用
- **news_desk/text_watermark**：文字写死在组件里。✓ 解耦
- **news_desk/image_watermark**：图片路径引用用户文件。✗ 还在引用（灰区，可接受）

字幕的引用模式踩出的具体问题：

- 用户在 news_desk 里给章节做了本地修改，但字幕还是上游版本——派生作品并不是真正"作品"
- 上游 SRT 改动（重新翻译、重切句子）会**静悄悄影响**未关闭的派生作品，对再生产能力（reproducibility）破坏
- 字幕编辑功能想做也没地方做——上游字幕是多个派生作品共用的，在 source 层编辑会影响所有下游
- 导出对话框得回头扫 `subtitles_dir/*.srt` 列可用语言（2026-05-16 那个 bug 的根因），违反"导出从 instance 状态派生"的直觉

合并到一个原则下解决：**编辑器模块导入即拥有；上游改动跟我无关，除非我主动重新导入。**

## 如何应用

**派生作品创建/编辑时**：
- 凡是要用到的上游数据，必须**显式导入**到 `<instance_dir>` 内（或组件 instance dict 内的可序列化字段）
- 导入按钮 UI 上要清楚是"快照动作"，不是"绑定动作"
- 提供 [↻ 重新导入] 让用户主动从上游同步（同时警告本地编辑会被覆盖）

**派生作品渲染/导出时**：
- **只读** `<instance_dir>` + 组件 instance dict
- 不准回头读 source 层任何文件（`subtitles_dir`、`analysis.json`、`hotclips.json` 等都禁止）
- 例外：`source_dir/basic_info.json` + `source_dir/context.json`（节目元数据，本来就属于"全派生共享的项目级元信息"，不是派生需要快照的内容）

**导出对话框**：
- 完全从派生 instance 状态派生 UI（有哪些组件、组件状态是什么）
- 不需要"选哪份 SRT" / "用哪个 analysis.json"——派生 instance 内已经决定了

**`<instance_dir>` 内布局约定**：

```
<project>/derivatives/<editor_type>/<instance>/
  config.json                  # 组件实例列表 + 顶层配置
  subtitles/
    <comp_id>.srt              # 字幕组件快照（一组件一文件）
  output.mp4                   # 主视频产出
  publish.md                   # 导出 sidecar
  ...
```

config.json 里组件的 `srt_path` 等字段存**相对 `<instance_dir>` 的路径**，不是绝对路径也不是项目相对路径。

**例外清单**：
- 文字水印的 `text` 字段：本来就在 instance 里 ✓
- 图片水印的 `image_path`：暂时允许指向用户文件系统的图片（一来上游不变化，二来复制大图片到 instance_dir 收益不明显）。**复议触发条件**：哪天用户报告"换了一张图发现旧派生作品的图片也跟着变了"，再做快照
- 节目元数据（host/event_date 等）：在 source 层，所有派生**共享读**，因为它是项目级真相，不是派生级决策

## 迁移路径

- subtitle 组件改造 → 2026-05-16 Phase 1（本 ADR 落地的首个改动）
- 现有 instance config 里指向 source 层 SRT 的 `srt_path` → 首次打开时自动 snapshot 到 `<instance_dir>/subtitles/<comp_id>.srt`
- 其他组件按需逐个迁移；不一定一次性全转完，但**新组件必须遵守本 ADR**

## 软件形态的连锁影响

承认了这个决策，VideoCraft 的形态实质上是：

- **数据准备工坊**（左侧 / source）：把一段原始视频转成多份标准化数据资产
- **N 个独立编辑器**（右侧 / derivatives）：news_desk、clip_script、bilingual_video、（未来更多形态）

每个编辑器从工坊"领料"（导入），然后独自完成编辑+导出。编辑器之间互不影响，编辑器跟工坊也没有运行时耦合。

这跟 memory `project_phase` 提到的「Phase = 视频编辑器（timeline+tracks）」是同一形态——只是 Phase 是**单一通用时间线**，而 VideoCraft 是**多种垂直形态各管一种节目**。未来 Phase 真做起来时，也只是**第 N+1 个编辑器模块**。
