# ADR-0011: 空间裁剪 = per-clip `Clip.crop` 变换（退役 DrawDeps 渲染旁路）

- **状态**: Active
- **决定日期**: 2026-06-08

## 决定

空间裁剪 / 取景（reframe）是 OTIO IR `Clip` 上的一等可选字段 **`Clip.crop: CropRect`**（归一化源矩形 `{x,y,w,h}∈[0,1]`，仅媒体 clip，缺省 = 整源）。共享 compositor 逐 clip 读取它。**退役**原先把 crop 当全局渲染旁路的 `DrawDeps.cropRect`。clip 与 news_desk 用同一字段表达，新增 IR 不变量 #7 钉死其取值（见 [composition-otio-foundation §2.5](../draft/composition-otio-foundation.md)）。

## 为什么

- **视频标准这么定义**：OTIO / 各 NLE（Premiere Motion、FCP Transform+Crop、DaVinci Transform、剪映裁剪）一致把空间变换放在 **Clip 层**——它绑定具体视频片段，既不是往画面叠加东西的**组件**，也不是整条 timeline / 整个 app 的**全局属性**。与 [[project_ir_nle_standard]]「OTIO 式标准多轨、差异只在编辑面」一致。
- **旧旁路的两个硬伤**：原实现 `config → planRender → DrawDeps.cropRect → 盖到每个 video layer`，crop 游离在时间线之外。① 一条 timeline 只能有一个全局 crop——多视频轨 / 按段裁剪根本无法表达；② 这是 CapCut 式自创机制的苗头，违背「严禁绕开 OTIO」。落到 `Clip` 上同时消除这两点，并让未来多段装配（录播自动剪辑）天然可逐段裁剪。
- **避免两插件各做一套**：news_desk 要加同样的剪裁能力。与其复制旁路，不如把 crop 提升成 IR 契约——两插件共享 compositor 读取，几何 / 编辑器层也共享，重复与旁路瓦片一起消失。

## 如何应用

- **改 IR `Clip` schema、compositor 的 video 绘制、或任何 per-clip 空间变换前先读这条。**
- **不变量 #7**：`Clip.crop` 若有，各分量有限、`w,h>0`、归一化矩形 ⊆`[0,1]`；`validateTimeline` 强制（foundation §2.5）。
- **共享件**：几何（`centerCropRect` / `clampCropRect` / `targetDimsForAspect` / `parseAspect`）= `desktop/src/composition/crop.ts`（`CropRect` 与 IR 同源）；拖框编辑器层（`paintEditorLayer` / `canvasDimsFor`）= `desktop/src/renderer/workbenches/shared/cropEditorLayer.ts`，clip 与 news_desk 的 preview 共用。
- **渲染语义（三模式）**：`reframe` → 设 `crop`（GPU cover，采样裁切窗口映射到输出帧）；`letterbox` → 无 `crop` + fit `contain`（黑边）；`passthrough` → 无 `crop` + 输出尺寸=源（属 ExportTab 输出尺寸层，IR 不可见）。
- **preview ≡ render**：预览画整源 + 拖框提示（亮框=成片），**预览不做 GPU 裁切**；真正裁切只在导出经 `Clip.crop` 发生。绝不能让预览改成 GPU 裁。
- **未来的 per-clip 空间变换（缩放 / 位移 / 旋转 / 不透明度）照此模式落到 `Clip` 上，不要再走渲染旁路。**
- **落地**：commit `3894fd7`（2026-06-08）。clip 行为逐字节不变（同 rect、同 shader，只换载体）；news_desk 默认 `passthrough` = 整源直出，与改动前一致。
