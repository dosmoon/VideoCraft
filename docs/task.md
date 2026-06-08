# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ✅ 出厂状态(2026-06-08）= 三轮 dogfood 全通过 + 已打包，无遗留 bug

> 最近 installer = `desktop/release/VideoCraft-0.3.5-setup.exe`（**2026-06-08 00:52**，174.9MB，HEAD `1059db6`）。
> working tree 干净。**注意**：installer 之后又落了 2 个本地 cleanup commit（未 push、未重打包）：`bc641dc` i18n 孤儿清扫、`0c17cac` env-screen 4 项修复（都是非打包改动，不影响出厂二进制）。诊断/实现细节在各 commit message + 记忆 + 下方归档。

已 dogfood 通过的三轮（详情见 [`_archive/task-archive-02`](_archive/task-archive-02_2026-06-05_2026-06-08.md)）：
- **06-06**：7 项真机修复（嵌入 AI/路由/质检/翻译/ClaudeCode 默认勾选/覆盖装保 user_data/点 source 不崩）+ **60fps AV1 导出死锁破案修复**（`ClipReader` 环淘汰策略，被 3000ms 超时伪装成"慢"；单测钉死）。
- **06-07~08**：clip/news_desk 4 项（编辑框冻结→乐观更新 / 新增「居中留边」letterbox 模式 / 原样下比例·短边置灰 / news_desk 恢复「按章节分割视频」）+ 候选页切模式实时更新。

---

## ▶ 下一任务（新对话先读）= P3 收尾（CI/签名）+ 一轮干净打包态终验

> **权威方案 = [`packaging-design.md`](draft/packaging-design.md)**（§8 步骤、§9 待决、§10 发布 checklist）。P3 steps 1-7（seam + 冻结 sidecar + NSIS + 嵌入 AI/GPU opt-in）+ step 8（ffmpeg 随包 ✅、品牌图标 ✅ 窗口/安装包、env 页 bundled 呈现 ✅）实质完成。

**▶ 真正剩下的（都不阻塞日常）**：
1. **CI（GitHub Windows runner）** —— runner 有符号链接权限，可去掉 `win.signAndEditExecutable:false`，恢复 **exe 内嵌图标 + 代码签名**（见下方 winCodeSign 坑）。
2. **backlog**：~~`src/i18n` Tk 孤儿大扫除~~ ✅ 2026-06-08（`bc641dc`，2156→28；AST 全量核验 tr() 调用点+字面量安全网，存活键只剩 subtitle.check/env.label/creation/material）；~~env-screen 打磨~~ ✅ 2026-06-08（`0c17cac`，扫描修 4 项：sticky error 清除 / detect_all 增量逐行 / 删 dead env.detect / node 版本解析）。env-screen 后续若有**具体痛点**再开（无具体锚点不做开放式优化，见 [[feedback_open_ended_llm_optimize]]）。
3. **录播自动剪辑方向**（下一大功能候选）：source 加录播 → ASR → AI 全自动剪裁/章节/切废段/过渡；per-品类插件。见 memory [[project_recorded_autoedit]]。

**⚠️ winCodeSign 坑（CI 必读）**：electron-builder 在 Windows eager 解压 winCodeSign（含 macOS 符号链接），非 admin/无 Developer Mode 建符号链接失败 → build 挂；现用 `win.signAndEditExecutable:false` 绕过（代价：exe 默认图标 + 不签名；窗口/安装包图标已是品牌图标）。CI runner 有符号链接权限可去掉这个 flag。

**纪律**：[[feedback_pre_alpha_no_legacy]] 不留兼容层；改 Python 整重启 sidecar；每步 build-green（pytest + desktop typecheck/vitest/build）；**冻结态 bug 不能只在 dev 验**（用驱动真 `core_rpc.exe` 的冻结 E2E 复现，见 [[feedback_frozen_bug_repro]]）；**renderer 性能/卡顿 bug 先装探针拿数据再改，整秒级的"慢"先比对代码里的 timeout/budget 常量，renderer 改动必 `dev.ps1` 整重启**（[[feedback_measure_dont_guess_renderer]]）；**Tk→新壳"缺口"恢复前先 grep docs 查是否故意删的**（[[feedback_parity_gap_not_bug]]）；**外部/远端写操作前先只读核对**（[[feedback_external_actions]]）。

---

## 📦 已归档历史

> 已完成会话记录移出本文件，按时间分两卷：
> - [`_archive/task-archive-01_2026-05-19_2026-06-05.md`](_archive/task-archive-01_2026-05-19_2026-06-05.md)：FastAPI 传输重构、P3 打包/Tk 退役、续 6~37 OTIO/Electron 迁移史。
> - [`_archive/task-archive-02_2026-06-05_2026-06-08.md`](_archive/task-archive-02_2026-06-05_2026-06-08.md)：三轮 dogfood（点 source 崩 / 60fps 导出死锁 / clip·news_desk 4 项 + 候选页跟随）。
>
> 需要历史背景接力时去那里查；本文件只保留**仍在进行**的任务。
