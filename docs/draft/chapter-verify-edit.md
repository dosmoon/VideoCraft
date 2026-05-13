# 章节验真 + 编辑 Plan（Phase B）

> 上下游：Phase A 已落地（首章自动补 `00:00`，commit `1cc0824`）。
> 本 plan 解决用户痛点：章节生成后**无法在 Hub 内验真**（要另开分割工作台跳点），**也无法修正错误时间戳**。

## 目标

Hub 右栏 preview tab 0 单击 `chapters.json` artifact 时：

1. 看到章节列表（已有，read-only）
2. 旁边带 WebView 视频预览，点章节 → 视频 seek 到章节起点
3. 可以微调章节起点时间戳，回写 `chapters.json`
4. 改动立刻反映到 sidebar / 派生工具，不依赖 2s 轮询

**非目标**（本期不做）：
- 章节增删（只编辑现有章节）
- 章节回写源 manifest 之外的位置
- 导出端 `publish.md` sidecar（单独开 plan，承接"优化两个派生"主线）

## 落点

```
src/ui/subtitle_analysis_preview.py  ── _render_chapters()
   └→ 重写为 split-view（左列表 + 右 WebView+控件）
```

复用：
- `src/ui/web_preview.py` 的 `WebPreviewFrame`（已在 source/composition preview 用过）
- `src/ui/composition_preview.html` 的 video + JS 桥（或新建轻量版）
- `src/core/subtitle_analysis_runners.py` 的 `_atomic_write_json`（**改成公开**，跨模块复用）
- `src/project.py` 的 `Project.source_video_path`

新增：
- `src/core/chapters_io.py`（轻量）—— 读/写 chapters.json，统一处理 end_sec 重算

## 交互

### 布局（建议：水平 split，左 35% 列表 / 右 65% 预览）

```
┌──────────────────┬───────────────────────────────┐
│  章节列表         │  [视频 WebView]                │
│  ──────────────  │   ▶ ⏸  当前: 00:02:15         │
│ ▶ 00:00:00 开始   │                                │
│   00:00:08 标题1  │  [编辑控件]                   │
│   00:02:30 标题2  │   起点: [00:02:30] 🎯当前秒    │
│   00:08:15 总结   │   [💾 保存] [↺ 撤销]          │
│                  │                                │
└──────────────────┴───────────────────────────────┘
```

- ▶ 标记当前选中章节
- 单击章节行 → WebView seek 到该章节起点（不自动播放，避免吵）
- 双击章节行 → seek + 播放（可选）

### 编辑（用户已选 a + b 双轨）

**a. 拖动预览 → 按"🎯当前秒"按钮**
- WebView 的 `<video>` 暴露 `currentTime` 经 JS bridge 回读
- 按钮文案就是当前秒数，点击 = 把这一秒写入起点输入框

**b. inline 输入框**
- 文本框接受 `HH:MM:SS` 或 `MM:SS`，复用 `_parse_time_str`
- 输入合法时实时 seek 预览（debounce 300ms），让眼睛能验"这个时刻是不是该章节起点"
- 输入非法时输入框红边，禁用保存按钮

### 保存

- 点保存 → 写回 chapters.json
- **end 字段需要重算**：被编辑章节的 `end = 下一章 start`，**前一章的 `end = 本章新 start`**
- 调用 `chapters_io.save_chapters(path, edited_list)` 内部完成 end 重算 + 时长重算 + 原子写
- 写完立刻调 Hub 的 `refresh_sidebar()`，不等 2s 轮询
- 写入前后 chapters.json 的 schema 不变（`schema_version: 1`）

### 撤销

- 内存里留一份 baseline（载入时的 chapters）
- 撤销 = 重新载入 baseline，不读盘
- 已保存到磁盘的不可撤销（不做版本历史）

## 边界条件

1. **首章是 auto-inserted 的 `开始`/`Intro`**（Phase A 产物）
   - 起点固定 `00:00:00`，禁用编辑（输入框 disabled）
   - 如果用户编辑下一章使其 start = 00:00:00，保存时检测到首章退化（end ≤ start），**自动删除首章** intro
   - 反之，如果保存后首章 start > 0，**自动重新插入 intro**——复用 Phase A 的 `_intro_chapter_title()`，保持运行时与生成时一致

2. **顺序约束**
   - 编辑后的章节列表必须保持 start 单调递增
   - 保存时校验：若违反则提示哪两个章节冲突，不保存

3. **越界**
   - start < 0 → clamp 0
   - start > 视频总时长 → 报错不保存（需要从 source video 拿 duration；已有 ffprobe 调用？查 `src/core/probe.py` 或类似）

4. **chapters.json 不存在**
   - 该路径下不可能被点到（artifact 必须存在才在 sidebar 显示），不处理

## 实现拆分

1. **小步骤 B1**：把 `_atomic_write_json` 从 runners 提到 `core/io_utils.py` 或暴露成模块级公开符号
2. **小步骤 B2**：新建 `core/chapters_io.py`，提供 `load_chapters(path)` / `save_chapters(path, chapters)`，负责 end/duration 重算 + intro 自动维护
3. **小步骤 B3**：重写 `_render_chapters()` 为 split-view 容器，左侧把现有 read-only 列表改为可选行 Treeview
4. **小步骤 B4**：右侧挂 `WebPreviewFrame`，载入 `source_video_path`，封装 `seek(sec)` / `get_current_time()` 经 JS bridge
5. **小步骤 B5**：编辑控件（输入框 + 当前秒按钮 + 保存/撤销）+ 与 Treeview / WebView 联动
6. **小步骤 B6**：标题 inline 改名（Treeview cell edit）走同一保存路径
7. **小步骤 B7**：保存路径调用 chapters_io.save + 刷 sidebar；i18n key 加 zh/en

每个小步骤可独立 commit。

## 设计决议（已对齐）

1. **源视频未就绪**：不处理。字幕由源视频识别而来，没源视频就没字幕也没章节，根本走不到这个面板。
2. **章节标题改名**：开。双击标题进入 inline edit，回车 / 失焦保存。跟时间戳走同一条保存路径。
3. **导出 sidecar**：本期不做，独立 plan，承接"优化两个派生作品"主线。
