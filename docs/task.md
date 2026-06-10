# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ✅ 当前状态(2026-06-09）= 已打包，working tree 干净，无遗留 bug

> 最近 installer = `desktop/release/VideoCraft-0.3.5-setup.exe`（**2026-06-08 21:10**，~175MB，HEAD `63a801d`，含 news_desk 剪裁）。全部 commit+push 到 origin/main。
> 已关闭会话记录全部归档（见下「📦 已归档历史」）：三轮 dogfood → archive-02；i18n 清扫 / env 修复 / news_desk 剪裁(crop-on-Clip, ADR-0011) → archive-03。实现细节在各 commit message + ADR + 记忆。

---

## ▶ 下一任务（新对话先读）= 录播自动剪辑方向（CI/签名已收口）

> **权威方案 = [`packaging-design.md`](draft/packaging-design.md)**（§8 步骤、§9 待决、§10 发布 checklist）。P3 steps 1-8 实质完成（含 CI，见下）。

**✅ CI（GitHub Windows runner）已落地 + 验证绿（2026-06-09）**：
- `.github/workflows/build-windows.yml`：`workflow_dispatch` + `v*` tag 触发 → setup-uv 冻结 sidecar（`build_sidecar.ps1`）→ 拉 ffmpeg（`fetch_ffmpeg.ps1`）→ pnpm `electron-vite build` + `electron-builder --win`，**CI 就地把 yml 的 `signAndEditExecutable: false` flip 成 true**（本机 yml 默认仍关，CI 才开；**不能用 `-c.win...=true` CLI override**——点号短形式被 yargs 当 config 文件路径 ENOENT，首跑就栽这）→ rcedit 嵌品牌图标 → installer 传 artifact，`--publish never`。
- **首验结果**：run `27191231392` 全绿 4m3s；winCodeSign 被拉下、edit/sign 管线对 `VideoCraft.exe` 跑过（图标内嵌确认生效）；artifact `VideoCraft-0.3.5-setup.exe`（183MB）下载验过 = `NotSigned`（符合预期，无证书）。
- ✅ **build 标识 + CI 端到端验过（2026-06-10, run #3 sha 4c7930c）**：`generate_build_info.ps1` → `build-info.json` 随包（实测包内 `{"build":"3","commit":"4c7930c",…}`）+ Windows FileVersion `0.3.5.3`（BUILD_NUMBER=run_number，经 signAndEditExecutable flip 生效）+ exe 版权 `© 2025-2026 OldApeTalk`。版本号规则见 [`../versioning.md`](../versioning.md)。
- ✅ **Node 20 弃用尾巴已清（run #4）**：action 全升 node24 大版本（checkout@v6 / setup-node@v6 / upload-artifact@v7 / pnpm@v6 / setup-uv@v8.2.0——后者无浮动 major tag 故钉精确）+ `runs-on: windows-2025`（脱离 `windows-latest`）。Node 20 公告消失。**残留 windows 公告**（`windows-2025`→`-vs2026` 镜像 6/15 刷新）纯信息性、任何标签都躲不掉、构建照常绿，不管。
- ⏸ **真签名（Authenticode）deferred**：用户选「先只要图标，暂不签名」。exe 当前 unsigned，SmartScreen 会警告。拿证书后接（方案见 packaging-design §10）。

**▶ 下一大功能候选 = 录播自动剪辑方向**：source 加录播 → ASR → AI 全自动剪裁/章节/切废段/过渡；per-品类插件。见 memory [[project_recorded_autoedit]]。（注：crop-on-Clip 已落地多段裁剪的 IR 地基，见 [ADR-0011](adr/0011-spatial-crop-clip-transform.md)）

**⚠️ winCodeSign 坑（历史背景）**：electron-builder 在 Windows eager 解压 winCodeSign（含 macOS 符号链接），非 admin/无 Developer Mode 建符号链接失败 → 本机 build 挂；本机 yml `win.signAndEditExecutable:false` 绕过（代价：exe 默认图标 + 不签名；窗口/安装包图标已是品牌图标）。**CI runner 有符号链接权限 → 已就地 flip 回 true 拿到 exe 内嵌图标（见上）。**

**纪律**：[[feedback_pre_alpha_no_legacy]] 不留兼容层；改 Python 整重启 sidecar；每步 build-green（pytest + desktop typecheck/vitest/build）；**冻结态 bug 不能只在 dev 验**（用驱动真 `core_rpc.exe` 的冻结 E2E 复现，见 [[feedback_frozen_bug_repro]]）；**renderer 性能/卡顿 bug 先装探针拿数据再改，整秒级的"慢"先比对代码里的 timeout/budget 常量，renderer 改动必 `dev.ps1` 整重启**（[[feedback_measure_dont_guess_renderer]]）；**Tk→新壳"缺口"恢复前先 grep docs 查是否故意删的**（[[feedback_parity_gap_not_bug]]）；**外部/远端写操作前先只读核对**（[[feedback_external_actions]]）。

---

## 📦 已归档历史

> 已完成会话记录移出本文件，按时间分卷：
> - [`_archive/task-archive-01_2026-05-19_2026-06-05.md`](_archive/task-archive-01_2026-05-19_2026-06-05.md)：FastAPI 传输重构、P3 打包/Tk 退役、续 6~37 OTIO/Electron 迁移史。
> - [`_archive/task-archive-02_2026-06-05_2026-06-08.md`](_archive/task-archive-02_2026-06-05_2026-06-08.md)：三轮 dogfood（点 source 崩 / 60fps 导出死锁 / clip·news_desk 4 项 + 候选页跟随）。
> - [`_archive/task-archive-03_2026-06-08_2026-06-09.md`](_archive/task-archive-03_2026-06-08_2026-06-09.md)：i18n 孤儿清扫 / env-screen 修复 / news_desk 剪裁 + crop-on-Clip 重构（ADR-0011）。
>
> 需要历史背景接力时去那里查；本文件只保留**仍在进行**的任务。
