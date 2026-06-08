# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ✅ 当前状态(2026-06-09）= 已打包，working tree 干净，无遗留 bug

> 最近 installer = `desktop/release/VideoCraft-0.3.5-setup.exe`（**2026-06-08 21:10**，~175MB，HEAD `63a801d`，含 news_desk 剪裁）。全部 commit+push 到 origin/main。
> 已关闭会话记录全部归档（见下「📦 已归档历史」）：三轮 dogfood → archive-02；i18n 清扫 / env 修复 / news_desk 剪裁(crop-on-Clip, ADR-0011) → archive-03。实现细节在各 commit message + ADR + 记忆。

---

## ▶ 下一任务（新对话先读）= P3 收尾（CI/签名）+ 一轮干净打包态终验

> **权威方案 = [`packaging-design.md`](draft/packaging-design.md)**（§8 步骤、§9 待决、§10 发布 checklist）。P3 steps 1-7（seam + 冻结 sidecar + NSIS + 嵌入 AI/GPU opt-in）+ step 8（ffmpeg 随包 ✅、品牌图标 ✅ 窗口/安装包、env 页 bundled 呈现 ✅）实质完成。

**▶ 真正剩下的（都不阻塞日常）**：
1. **CI（GitHub Windows runner）** —— runner 有符号链接权限，可去掉 `win.signAndEditExecutable:false`，恢复 **exe 内嵌图标 + 代码签名**（见下方 winCodeSign 坑）。
2. **录播自动剪辑方向**（下一大功能候选）：source 加录播 → ASR → AI 全自动剪裁/章节/切废段/过渡；per-品类插件。见 memory [[project_recorded_autoedit]]。（注：crop-on-Clip 已落地多段裁剪的 IR 地基，见 [ADR-0011](adr/0011-spatial-crop-clip-transform.md)）

**⚠️ winCodeSign 坑（CI 必读）**：electron-builder 在 Windows eager 解压 winCodeSign（含 macOS 符号链接），非 admin/无 Developer Mode 建符号链接失败 → build 挂；现用 `win.signAndEditExecutable:false` 绕过（代价：exe 默认图标 + 不签名；窗口/安装包图标已是品牌图标）。CI runner 有符号链接权限可去掉这个 flag。

**纪律**：[[feedback_pre_alpha_no_legacy]] 不留兼容层；改 Python 整重启 sidecar；每步 build-green（pytest + desktop typecheck/vitest/build）；**冻结态 bug 不能只在 dev 验**（用驱动真 `core_rpc.exe` 的冻结 E2E 复现，见 [[feedback_frozen_bug_repro]]）；**renderer 性能/卡顿 bug 先装探针拿数据再改，整秒级的"慢"先比对代码里的 timeout/budget 常量，renderer 改动必 `dev.ps1` 整重启**（[[feedback_measure_dont_guess_renderer]]）；**Tk→新壳"缺口"恢复前先 grep docs 查是否故意删的**（[[feedback_parity_gap_not_bug]]）；**外部/远端写操作前先只读核对**（[[feedback_external_actions]]）。

---

## 📦 已归档历史

> 已完成会话记录移出本文件，按时间分卷：
> - [`_archive/task-archive-01_2026-05-19_2026-06-05.md`](_archive/task-archive-01_2026-05-19_2026-06-05.md)：FastAPI 传输重构、P3 打包/Tk 退役、续 6~37 OTIO/Electron 迁移史。
> - [`_archive/task-archive-02_2026-06-05_2026-06-08.md`](_archive/task-archive-02_2026-06-05_2026-06-08.md)：三轮 dogfood（点 source 崩 / 60fps 导出死锁 / clip·news_desk 4 项 + 候选页跟随）。
> - [`_archive/task-archive-03_2026-06-08_2026-06-09.md`](_archive/task-archive-03_2026-06-08_2026-06-09.md)：i18n 孤儿清扫 / env-screen 修复 / news_desk 剪裁 + crop-on-Clip 重构（ADR-0011）。
>
> 需要历史背景接力时去那里查；本文件只保留**仍在进行**的任务。
