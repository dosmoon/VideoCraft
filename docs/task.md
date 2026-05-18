# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 下次会话主题：clip 重构 Step 5 + 6（组件化 + Style 物理迁移）

**先读** [[project_clip_refactor_debt]] —— 该记忆是 clip 跟 news_desk 现行标准的偏差清单 + 推荐重构顺序 + 验收标准。Step 1-4 已完成，Step 5-6 还在欠债。

### 一句话

clip 现在已经走 NewsVideoModel + ClipInstanceConfig 单 writer + set_timeline 单桥 + god 模块切成 5 个子模块，**但 hook/outro/subtitle/watermark 还不是 ComponentSpec**——没和 news_desk 的 component 抽象对齐。

### 已完成（本轮会话，2026-05-18）

7 个 commit，clip_tool 2208 → 1135 行（-49%），新增 5 个子模块：

| Commit | Step | 主题 | clip_tool 行数 |
|---|---|---|---|
| `ba76a86` | 1 | 素材访问全走 NewsVideoModel；删 `_nv_paths` 8 处 callsite | 2208 → 2208 |
| `4f39650` | 2 | `ClipInstanceConfig` dataclass 单 writer（mirror news_desk） | 2208 → 2137 |
| `6eee4fa` | 3 | preview 走 `set_timeline` 单桥；删 set_cues/set_cues_secondary/set_clip_meta；hook/outro wrap parity 测试 | 2137 → 2117 |
| `4ed2676` | 4.1 | 拆 `candidates.py` —— `HotclipsRepo` 纯 IO 层 | 2117 → 2137（清完是 2137 但拆后实际 -71） |
| `5252826` | 4.2 | 拆 `render_queue.py` —— `RenderQueue` 线程封装 | 2137 → 2117 |
| `148d710` | 4.3 | 拆 `clip_editor.py` —— `ClipDetailPanel` 详情面板 | 2117 → 1835 |
| `fada901` | 4.4 | 拆 `style_panel.py` —— Tab 1 完整 UI + form vars + preset 菜单 | 1835 → 1135 |

最终模块布局：
```
clip_tool.py      1135  入口 + tabs orchestration + render pipeline + 候选/导出
style_panel.py     799  Tab 1 全部（StylePanel）
clip_editor.py     387  Tab 2 详情面板（ClipDetailPanel）
render_queue.py    139  threading worker（RenderQueue）
candidates.py      138  hotclips data layer（HotclipsRepo）
config.py          136  config.json single owner（ClipInstanceConfig）
```

### Step 5 — Component 化（最大一步）

把 hook/outro/subtitle/watermark 各拆成 `ComponentSpec`，clip UI 改成 component list（参考 news_desk）。

**目标**：clip 跟 news_desk 共享同一个 `ComponentSpec` 注册表机制 + `ProjectContext` 协议，未来 subtitle / text_watermark / image_watermark 可以双方复用。

**重点考量（detail discussions 见 task.md 老主题 1）**：
- clip 是「一对多」（长视频→N 短视频），news_desk 是「一对一」。组件抽象能否承载？
- hook/outro 是 1 个组件还是 2 个？hotclips 列表是组件吗？
- 哪些 news_desk 组件可直接复用？（subtitle / text_watermark / image_watermark 几乎肯定可以）

**预期改动**：
- `build_clip_timeline` 删——改成 `ComponentDictAdapter` 喂 `compile_timeline()`（同 news_desk）
- `StylePanel` 改造或拆出 component-aware UI（clip 的 form 跟 news_desk 的 component list 差距大，可能需要保留 form 同时新加 component sidecar）
- `ClipInstanceConfig` 加 `components: list[dict]` 字段（mirror NewsDeskInstanceConfig）

**最大风险点**：clip 当前用单个 `CompositionStyle` dataclass 驱动 hook/outro/subtitle/watermark；改成 N 个 component dict 后样式系统重排。需要逐组件渐进迁移（subtitle 先迁，watermark 次之，hook+outro 最后）。

### Step 6 — Style 物理迁移（纯关系性整理）

`core/composition/style.py` 的 `CompositionStyle/SubtitleStyle/WatermarkStyle/HookOutroStyle` 搬到 `creations/clip/style.py`。`core/composition/style.py` 只剩 `OutputGeometry`。

clip 是 `CompositionStyle` 的唯一消费者；最近 Step 3 已经让引擎 API 不再依赖它（`drawtext_filter` 吃 dict）。这步是纯文件移动，不改行为。

如果 Step 5 走得动，这步可能在过程中自然完成（组件化后样式 dataclass 也可拆到对应 component 里）。

### 验收（每步重构后）

- 270+ 测试全绿
- 9 goldens byte-equal
- 该步对应的架构 grep guard 加上（tests/test_arch_clip.py）
- preview ≡ render 不变量（ADR-0006 #6）通过 wrap-parity 测试

### 起点 HEAD

`fada901` —— "clip: extract StylePanel to style_panel.py (refactor step 4.4)"，已 push origin/main。270 测试全绿；9 goldens byte-equal。

### 不在 Step 5/6 范围内

- AI clip 切片逻辑（hotclip 候选生成）
- 拆 WatermarkStyle / HookOutroStyle 成窄 primitive Style（PR 5 deferred 第 3 项）
- bilingual_video 阶段二（已规划但跟 clip 平行）

---

## 已完成（迁移整轮 + 后续补完，2026-05-17）

### Timeline 迁移（5 PR 全 land）

- PR 1：timeline IR 脚手架（`c555449`）
- ADR-0006 立项（`39c4fda`）
- PR 2：news_desk_overlays.py 解构 + 7 primitive 落地（`66cd2c0`）
- PR 3：`compile_timeline()` 真实现 + news_desk 4 component compile()（`37b4e71`）
- PR 4：news_desk → timeline 端到端（`04c11f1`）
- PR 5：clip → timeline + 老 5 通道删 + 架构 guard（`4dd932b`）

### 迁移后补完（同会话）

- 引擎 API 跟 CompositionStyle 解耦（`84ad0b2`）
- preview≡render 字幕 wrap 分裂修复（`ba9d584`）
- ADR-0006 加不变量 #6（`949faf3`）

---

## 老主题（已被 timeline 设计取代，仅留作上下文）

下面这些是 2026-05-17 上半段的待办，**已经在 timeline 设计 + 本轮 clip 重构中被消解或部分覆盖**：

### 主线 1 — 验证 news_desk 抽象组件逻辑在 clip 模块的可用度

**部分进入 Step 5**。已知 clip 是非组件化对照组，需要做 component 化判定。

调研要点（保留供 Step 5 参考）：
- clip 的核心语义是"长视频 → N 段短视频"，跟 news_desk 的"一对一带 overlay"不同。组件抽象能否承载"多输出"形态？
- clip 现有元素（hook / outro / subtitle 主副 / watermark / hotclip 候选列表）拆成组件后是什么形状？
  - hook_outro 应该是一个组件（一对开/收文案）还是两个（hook 组件 + outro 组件）？
  - hotclips 候选列表是组件吗？还是更高一层的"切片任务集合"？
- ProjectContext 在 clip 场景下需要哪些字段？多输出场景下"instance_dir"语义如何变？
- 哪些 news_desk 组件可以直接复用到 clip？（subtitle / text_watermark / image_watermark 几乎肯定可以）

### 主线 2/3 — composition 引擎边界 / 组件归属

**仍未处理**。`core/composition/news_desk_overlays.py` + Chapter/LowerThird/TopicStrip 类还挂在 core 里，是已知 wart。Step 5 之后或独立 ADR 处理。

---

## 仍生效的开发约定

- prompt 改动必须 git commit
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json`（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作**任何**新代码必须遵守 [[ADR-0003]] / [[ADR-0004]] / [[ADR-0005]]
- 创作插件访问素材数据**必须**经 Material Model（[[feedback_material_via_model_only]]）
- 每个创作的 config.json **必须**有单一内存所有者（[[project_creation_config_owner]]）
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）
