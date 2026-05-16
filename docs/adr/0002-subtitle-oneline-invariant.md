# ADR-0002: 字幕单行不变量

- **状态**: Active
- **决定日期**: 2026-04（VideoCraft 0.3 之前长期生效，2026-05-16 入 ADR）

## 决定

烧录字幕时，**每条 cue 在画面上必须只占一行**：

- `sub1`（通常 CJK） = 1 行
- `sub2`（通常 Latin） = 1 行
- bilingual 双轨 = 上下 2 行（每轨各 1 行）
- **永远不允许"一条 cue 视觉换行成 2 行"**

超长 cue 的处理方式是**沿时间轴切短**，不是视觉换行成多行。

## 为什么

用户长期验证：1+1（双轨各 1 行）在 1080p 16:9 帧底部只占约 12% 高度，给章节卡 / lower-third / 台标 / 视频主体留充足空间。

若允许 2 行视觉换行，bilingual 立刻吃掉 24%+ 帧高度，跟 news_desk 这类多 overlay 派生强冲突——overlay 设计的位置约束都建立在"字幕区永远只占 12%"这条假设上。

## 如何应用

执行机：

- `core.subtitle_ops.process_srt_split` 在烧录前按字符数切 cue
- `core.composition.style.compute_subtitle_max_chars` / `effective_max_chars` 计算每个 cue 的最大字符数
- max_chars 控住每个 cue 字符数 → 超长 cue 被时间轴切割
- libass `force_style` **不要**加 `WrapStyle=0` 之外的设置（0 = smart wrap，有 max_chars 兜底实际不会触发）

**未来若有人（包括 AI）提议"放宽到 2 行视觉换行"**，先 review 这条 ADR，确认无 news_desk / lower-third / 多 overlay 派生需要让位再动。这是个跨派生形态的全局约束，不是局部偏好。
