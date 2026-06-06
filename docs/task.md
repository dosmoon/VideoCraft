# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ▶▶ 本会话(2026-06-05 续→06-06)= 打包前预修 + 重打 installer + dogfood 抓修「点 source 崩」(✅ 全 push,`ef397f3`→`44ac68f`;installer 02:22 重打)

> 接上一轮(FastAPI 传输)。先做 3 个打包前预修 → 重打 installer → 用户真机 dogfood 抓出「点 news source 直接崩」→ 定位+修复+验过。全部 commit+push 到 `origin/main`(HEAD `44ac68f`)。**下次 = 用户开新对话跑完整 dogfood。** task.md 只留路标,诊断细节在各 commit message + 记忆。

- **`ef397f3` ClaudeCode 默认勾选**:`_DEFAULT_PROVIDERS["ClaudeCode"].enabled` False→True(claude CLI 自己管 auth、无需 key,没理由像 Custom 那样默认关;Custom 仍默认关)。只在全新安装暴露。
- **`4126a13` 用户数据绿色化(P1)= 覆盖/更新安装不再抹 user_data**:① `keys_dir()` 冻结态→`user_data/keys`(原 `__file__`-relative 落 sealed `_internal/keys`、随包抹;dev 仍 `<repo>/keys`,不迁凭据)② 新 `desktop/build/installer.nsh` `customRemoveFiles` 宏:卸载时 user_data 挪同卷兄弟目录→清 `$INSTDIR`→挪回(electron-builder 自动从 buildResources 收;`.gitignore` 加 `!installer.nsh`)。**真机验**:种 models/keys/settings/py-extra→跑装好的卸载器→app 删净、user_data 全留。权威 packaging-design.md §4;memory [[reference_nsis_userdata_preservation]]。**⚠️ 只护「带宏的 build」往后;首次覆盖 pre-fix 旧版仍抹 → fixed build 先干净装一次**。
- **`44ac68f`「点 news source 直接崩」真因+修复(本会话主战)**:根因 = **Win11 26200 sandbox 间歇崩**,**不是** AV1 / 不是装版专属 / 不是某 commit(走了几轮弯路才定位——血泪:dev/装版/unpacked/codec 全被错排查过,最后靠 `ELECTRON_ENABLE_LOGGING` 抓到 `child-process(Utility) exit -2147483645`)。机制:点 source 开 `<video>` 预览 → Chromium 音视频解码 Utility 子进程间歇撞 sandbox 不兼容 → 旧的「崩了被动 `--no-sandbox` 重启」把整 app 中途重启=丢现场=用户眼里的「崩」。修:main.ts **启动即主动 `--no-sandbox`**(`build>=26200` via `os.release()`)+ 持久化 `user_data/no-sandbox.flag` 自愈 + 旧被动重启留兜底。**真机验**:重装后正常启动点 source 不崩。memory [[project_electron_version_policy]] 已更新(此 bug 运行时点视频预览触发、伪装成崩、抓日志法)。
- **`3f07a9d` 源下载钉 H.264/AAC —— ⚠️ 半成品,新对话重议,先冻结别动**:当初当成崩因钉的(实为 sandbox)。H.264 比 AV1 大~33%(本视频 314MB vs 236MB,高速画面差更大)→ 下载变慢。**保留的真理由只剩音频 AAC**(YouTube 默认 Opus 塞进 mp4,浏览器易没声);视频档 H.264 对 4060(本就 AV1 硬解)好处弱。**新对话决策**:先查合成器/导出能否吃 AV1 源 → 能则视频档回退 `AV1+AAC` 省 1/3 下载、不能则 H.264 保持。用户拍板「先这样,dogfood 后再说」。
- **installer 重打**(`build_sidecar`+`fetch_ffmpeg`+`build:win`,02:22,174.9MB):带上面全部 + 上一轮传输/i18n/路由/质检修复。HTTP 烟测 + 真机均过。

**▶ 下一任务(新对话先做)= 用户跑完整 dogfood**(重打的 installer 已装)。逐项验:① 嵌入 AI 装+ASR **不卡死** ② 路由**不列禁用 provider** ③ 质检**本地化+点 #N 跳转** ④ 翻译选禁用 provider **报清晰错** ⑤ ClaudeCode **默认勾选** ⑥ **覆盖安装不丢 user_data** ⑦ 点 source **不崩**(已验,复测即可)。dogfood 中顺带定 `3f07a9d` 的 H.264↔AV1 取舍。**之后**回下方「P3 收尾(CI/签名)」。

---

## ▶ 下一任务(新对话先读)= P3 收尾(CI/签名)+ 一轮干净打包态终验

> **权威方案 = [`packaging-design.md`](draft/packaging-design.md)**(§8 步骤、§9 待决、§10 发布 checklist)。**P3 steps 1-8 实质完成,push 时 HEAD `7148483`;之后本会话(2026-06-05)又叠了传输重构+4 修复到 `fd7edbf`(见最上方)。** steps 1-7 = seam + 冻结 sidecar + NSIS + 嵌入 AI/GPU opt-in;step 8 已做:**ffmpeg 随包**(✅)、**品牌图标**(✅ 窗口/安装包图标;exe 内嵌图标待 CI)、env 页 bundled 呈现收口(✅)。

**▶ 真正剩下的(都不阻塞日常)**:
1. **CI(GitHub Windows runner)** —— runner 有符号链接权限,可去掉 `win.signAndEditExecutable:false`,恢复 **exe 内嵌图标 + 代码签名**(见下方 winCodeSign 坑)。
2. **一轮干净打包态终验 = 见最上方本会话块「欠/下一步」**(现在它要带的不只 env 标签 + renderer,还有传输重构 + i18n 数据 + parent-watch + 路由/质检修复 —— 必须 `build:win` 重打才进 win-unpacked)。
3. **backlog**:`src/i18n` Tk 孤儿大扫除(VLC 已清,还有别的;注意≠本会话的 i18n **打包**修复,那是把 JSON 打进冻结包,孤儿清扫是删死 key);env-screen 其它打磨。

**⚠️ winCodeSign 坑(CI 必读)**:electron-builder 在 Windows eager 解压 winCodeSign(含 macOS 符号链接),非 admin/无 Developer Mode 建符号链接失败 → build 挂;现用 `win.signAndEditExecutable:false` 绕过(代价:exe 默认图标 + 不签名;窗口/安装包图标已经是品牌图标)。CI runner 有符号链接权限可去掉这个 flag。

**纪律**:[[feedback_pre_alpha_no_legacy]] 不留兼容层;改 Python 整重启 sidecar;每步 build-green(pytest + desktop typecheck/vitest/build);**冻结态 bug 不能只在 dev 验**(本会话血泪:clip 死锁只在「冻结 + 长 cut」现,dev/短视频/非冻结全测不出——要用驱动真 `core_rpc.exe` 的冻结 E2E 复现,见下方本会话块);**外部/远端写操作前先只读核对**([[feedback_external_actions]])。

---

## 📦 已归档历史

> 2026-05-19 ~ 2026-06-05 的全部**已完成**会话记录已移出本文件,见
> [`_archive/task-archive-01_2026-05-19_2026-06-05.md`](_archive/task-archive-01_2026-05-19_2026-06-05.md):
> FastAPI 传输重构(06-05 大轮)、P3 打包/Tk 退役(06-04/06-03)、续 6~37 OTIO/Electron 迁移史。
> 需要历史背景接力时去那里查;本文件只保留**仍在进行**的任务。
