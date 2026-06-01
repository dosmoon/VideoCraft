# ADR-0007: 组件编辑 UI = 引擎独占的 FieldSpec 元数据

- **状态**: Active
- **决定日期**: 2026-06-01
- **关联**: ADR-0006（compile→OTIO 契约）、ADR-0004（三层插件架构）；落地 `composition-otio-foundation.md` §4.5 里"组件 = ① 编辑 UI + ② compile"的 ①。

## 决定

一个视频组件的**编辑 UI**（属性面板）由引擎独占的**字段元数据**描述：每个组件在
`desktop/src/composition/components/*.ts` 导出 `fields: FieldSpec[]`（纯数据，无
React），renderer 的单一 `<ComponentEditor>` 解释它来画面板。clip 与 news_desk
**共用同一个编辑器**；per-plugin 只保留"挑哪些组件 + 分析→config 映射 + preset +
workbench"。

配套把 news_desk 的 wire 配置**归一到与 clip 一致的规范形状**（全 float 分数 +
规范字段名），消除两插件对同一逻辑字段的单位/命名分叉。

## 为什么

- 迁移时 ① 一直没建，临时用一个通用 `PropertyPanel` 直接编辑各插件原始 wire
  dict：从运行期值类型猜控件、从字段名 `/opacity/i` 猜步进（分数字段取到 0 或
  1.0 就退化成步进 1）、把 snake_case 内部名当标签显示（违反"UI 不露内部名"）。
  dogfood 连环踩雷（小数打不进、箭头 +1、position 是自由文本而非 anchor 下拉）。
- 根因是"没有字段语义元数据"。元数据属于组件本身（引擎），不属于某个 workbench；
  这正是 §4.5 早已拍板、只是没落地的 ①。**不是**在"框架+插件"之上造新抽象
  （见 `feedback_no_universal_standard`）——组件库含其编辑 UI 本就是 composition
  框架契约的一部分。
- 两插件单位分叉（clip 存 0.025 / news_desk 存 2.5 + mapping `/100`）使"统一编辑器"
  不可能：同一字段在两插件显示不同。pre-alpha 无 legacy，直接归一最干净。

## 如何应用

- **加/改组件字段** → 改该组件的 `fields: FieldSpec[]`（不是改编辑器）。`FieldSpec`
  见 `composition/components/fieldSpec.ts`。
- **FieldSpec.key 是持久化的 wire snake_case key**（编辑器编辑的是 sidecar 持久化的
  snake dict，经 `creation.update_component` 浅合并）。这是对"composition 层一律
  camelCase canonical"的**有意例外**：camelCase `*Instance` 只是 compile 期内部形状，
  由各插件 `mapping.ts` 产出，编辑器不碰。
- **clamp/归一只在 `mapping.ts`**（ADR-0006 单点不变量）。FieldSpec 的 `min/max`
  仅作步进/UX 提示——preset / AI 导入绕过编辑器，权威 clamp 必须在 mapping。
- **kind 前缀解析归编辑器**：`canonicalKind()` 把 `clip_image_watermark` → 裸
  `image_watermark`，两插件 kind 解析到同一份 fields。
- **字段集不对称**：同一组件在两插件字段集可不同（clip 字幕有 language/bold；
  news_desk 有 bg_enabled）。编辑器只渲染该实例上实际存在的字段（取交集）。
- **嵌套字段（chapter）**用 `FieldSpec.path` + `visibleWhen`；提交经
  `shared/nestedPatch.ts` 整子对象重发以对抗浅合并。
- 新组件务必在 `fieldSpec.ts` 注册表登记；未登记的 kind 编辑器显示"无字段"。
