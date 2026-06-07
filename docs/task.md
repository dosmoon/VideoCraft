# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ▶▶ 本会话(2026-06-07 dogfood round 2)= clip/news_desk 4 项(✅ 全 dogfood 通过 + push `e0080ca` + installer 11:24 重打)

> 用户第二轮 dogfood 抓出 4 项。全部修复+真机复验通过+commit+push origin/main(HEAD `e0080ca`)+ 重打 installer(11:24,174.9MB,复用未变冻结 sidecar+ffmpeg,仅重打 renderer/main/preload)。细节在 commit message,这里只留路标。

- **#1 clip 编辑框偶发"点不动、过会儿好"** = 属性面板/勾选框在 `updateComponent` 往返期间被 `savingId` 整体 `disabled` 冻结(sidecar 一慢就锁)。修:[ClipWorkbench.tsx](../desktop/src/renderer/workbenches/clip/ClipWorkbench.tsx) 改**乐观更新**(本地 deepMerge 立即生效、后台静默存、失败 resync),删 disable-during-save。注:并行 agent 给的"await 阻塞主线程"理论是**错的**(await 让出事件循环;预览已是非阻塞 frameAt)。
- **#2b 原样(passthrough)下比例/短边置灰** —— 它们在 passthrough 本就不生效(输出=源尺寸),置灰+悬停提示,消除"原样+9:16 没反应"困惑。
- **#2a 新增第三种模式「居中留边」(letterbox/contain)** —— 整 16:9 居中进 9:16 上下留黑边,解左右并排素材没法裁竖屏。export(target aspect+不裁+contain)+ preview(画布按 target aspect 重排,preview≡render)+ 类型贯通 + 中英文案。**parity 查证 = 全新功能(原 Tk 无),用户点名要求新建**(非误删恢复)。
- **#3 news_desk 恢复「按章节分割视频」** —— **查证 = 刻意 deferred(写在 `src/creations/news_desk/export.py` docstring + electron-migration-design.md),非误删**。恢复:主进程 [ffmpeg.ts](../desktop/electron/ffmpeg.ts) 新 `splitChapters`(对 output.mp4 按章节 `-c copy` 流拷贝、关键帧对齐、逐段失败只跳过)+ IPC/preload/类型 + 导出页**默认关**勾选框(无章节灰) + 纯逻辑 `chapterSegments` 4 单测。实际切分走主进程**随包 ffmpeg**(dev 需 PATH 有 ffmpeg)。
- **后续修复(dogfood)= 候选页切模式不更新**:clip 三 tab 各持**独立** `useClipPreview`;候选页缺 `active`+激活 reload(导出页早有),改模式后候选预览停在旧 mode。修:[ClipsTab.tsx](../desktop/src/renderer/workbenches/clip/ClipsTab.tsx) 加 `active`+激活 `reload()`,[ClipWorkbench.tsx](../desktop/src/renderer/workbenches/clip/ClipWorkbench.tsx) 传 `active`。dogfood 通过。
- 全程 build-green:typecheck(renderer+electron)+ 224 vitest + electron-vite build。

---

## ▶▶ 本会话(2026-06-06 dogfood)= 一串真机修复(✅ push)+ ✅ **60fps 导出慢已破案+已修+单测钉死+真机 dogfood 复验通过**

> 用户跑 dogfood 抓出一串 bug。**已修+push 的见下;唯一悬而未决 = 60fps AV1 导出 ~0.5fps。** ⚠️ **本轮血泪**:我在 60fps 问题上反复瞎猜(错怪 AV1→backgroundThrottling→ring→硬解→队列背压,全错),直到装探针拿数据才排除。**纪律(务必遵守)**:遇到「dev 正常/装版异常」或「改了没反应」**先上探针拿数据,别猜**;**renderer 改动必须 `desktop/dev.ps1` 整重启**(本环境 HMR 发旧 bundle,Ctrl+R 一直在喂旧代码、害我对着旧 bundle 瞎调)。

- **✅ task.md 拆分归档**(`8cd8b89`):完成会话挪 `docs/_archive/`(本块的"已完成"部分以后也归档)。
- **✅ 预览 60fps 卡 —— 真修,已验**(`13b0dc5`):clip/news_desk 预览**误用了导出专用的阻塞 `frameAtExact`**(三元 `frameAtExact?…:frameAt` 因 ClipReader 永远有该方法而恒走阻塞分支),应改用非阻塞 `frameAt`(导出走 [draw.ts](../desktop/src/renderer/engine/compositor/draw.ts) 的 `exact` 标志,不受影响)。30fps 解码跟得上没暴露,60fps 暴露成每 10s 一帧。
- **✅ AV1 无辜,保留**(`d9e5223`):源下载 H.264 解钉→AV1+AAC。后续证明 **AV1 不是任何问题的根**(30fps AV1 预览+导出一路都好);别再 revert AV1。
- **✅ 候选标题入 publish.md**(`f0a3afa`):章节导入漏拷信封 `titles[]` → 章节组件无 `titles` → publish 无候选标题段。**已有实例需重新导入章节**才回填。
- **✅ 模型路径「更改」无效**(`ed1d145`):冻结态 keys-dir 漂移(`paths` 读封死 `_internal/keys`、`config` 写 `user_data/keys`)→ 收进 `core.user_data.keys_dir` 单源。memory [[reference_frozen_file_path_drift]]。
- **✅ 更改路径提示**(`24e025f`)+ **backgroundThrottling 试了又撤**(`a3669ff`/`acf066a`,与卡顿无关)。
- **✅ 导出进度计数器 + 撤队列背压**(`3ce7e0b`):导出按钮旁显示 `framesDone/framesTotal`(旧的四舍五入 0% 让慢渲染像卡死);撤掉我加的 `MAX_DECODE_QUEUE`(下述)。

### ✅ 已破案 = `ClipReader` 环缓冲淘汰策略 vs 高帧率源的**解码泵死锁**(被 3000ms 超时伪装成"慢")
- **真因(代码静态分析 + Plan agent 对抗复核 + 确定性单测三重确认)**:[ClipReader.ts](../desktop/src/renderer/engine/source/ClipReader.ts) 环只存 `RING_CAPACITY=8` 帧,`frameAtExact` 保留 `TRIM_BEHIND_US=200ms` 历史窗口。环里是**源 native pts 帧**,200ms 窗口内帧数 = `0.2×源fps`:30fps=6<8 ✓;**60fps=12>8 ✗**。当 `frameAtExact` 需越过 >8 帧才够到目标(seek 落在 keyframe 远处、或解码器瞬时落后)时,满环全落在 200ms 内 → `trimBefore` 一个都不丢、不 `signalSpace` → 泵卡 `awaitSpace()` → 循环爬到 `EXACT_WAIT_BUDGET_MS=3000` 返回滞后帧 ≈ **2-4s/帧**。**临界点 = 40fps**(0.2×40=8),完美对上 30 好/60 炸。**是死锁被超时伪装,不是解码慢**——正应用户"慢到离谱一定是很严重的错误"。之前瞎猜(AV1/帧池/队列/ring 24)全错;"ring 24 没用"不可信(疑 HMR 旧 bundle)。
- **修复(治本,对任意源 fps 鲁棒,~20 行;3 处)**:① [FrameRingBuffer.ts](../desktop/src/renderer/engine/source/FrameRingBuffer.ts) 新增 `dropOldest()`;② `frameAtExact` 等待循环:满环且仍落后目标时丢最旧帧打破死锁(前向导出永不回看,最旧帧必在目标后、可安全丢);③ 取帧后改用 `trimBefore(candidate.timestamp)`(而非 200ms 窗口)恢复 lookahead。**不加大 RING_CAPACITY**(只挪阈值+帧池耗尽风险),**不重加 `MAX_DECODE_QUEUE`**(`hasSpace()` 已是输出背压)。预期 0.5fps → 解码器吞吐上限(软解 AV1 1080p ~30-100fps)。
- **单测钉死(对齐 engine-test-initiative;此前 ClipReader/FrameRingBuffer 零测试)**:`FrameRingBuffer.test.ts`(4) + `ClipReader.test.ts`(3)。**确定性复现**:mid-GOP seek 测在 revert Part 2 后**失败于 3074ms(=3000ms budget)返回滞后帧 26 而非目标 30** —— 真 guard 非 tautology。typecheck + 全 220 测绿。
- **✅ 真机 dogfood 复验通过**(2026-06-06,用户确认导出已正常)。**待办**:进装版需 `build:win` 重打(随下一轮 dogfood)。兜底"下载限 fps<=30"已不需要。

---

## ▶▶ 本会话(2026-06-05 续→06-06)= 打包前预修 + 重打 installer + dogfood 抓修「点 source 崩」(✅ 全 push,`ef397f3`→`44ac68f`;installer 02:22 重打)

> 接上一轮(FastAPI 传输)。先做 3 个打包前预修 → 重打 installer → 用户真机 dogfood 抓出「点 news source 直接崩」→ 定位+修复+验过。全部 commit+push 到 `origin/main`(HEAD `44ac68f`)。**下次 = 用户开新对话跑完整 dogfood。** task.md 只留路标,诊断细节在各 commit message + 记忆。

- **`ef397f3` ClaudeCode 默认勾选**:`_DEFAULT_PROVIDERS["ClaudeCode"].enabled` False→True(claude CLI 自己管 auth、无需 key,没理由像 Custom 那样默认关;Custom 仍默认关)。只在全新安装暴露。
- **`4126a13` 用户数据绿色化(P1)= 覆盖/更新安装不再抹 user_data**:① `keys_dir()` 冻结态→`user_data/keys`(原 `__file__`-relative 落 sealed `_internal/keys`、随包抹;dev 仍 `<repo>/keys`,不迁凭据)② 新 `desktop/build/installer.nsh` `customRemoveFiles` 宏:卸载时 user_data 挪同卷兄弟目录→清 `$INSTDIR`→挪回(electron-builder 自动从 buildResources 收;`.gitignore` 加 `!installer.nsh`)。**真机验**:种 models/keys/settings/py-extra→跑装好的卸载器→app 删净、user_data 全留。权威 packaging-design.md §4;memory [[reference_nsis_userdata_preservation]]。**⚠️ 只护「带宏的 build」往后;首次覆盖 pre-fix 旧版仍抹 → fixed build 先干净装一次**。
- **`44ac68f`「点 news source 直接崩」真因+修复(本会话主战)**:根因 = **Win11 26200 sandbox 间歇崩**,**不是** AV1 / 不是装版专属 / 不是某 commit(走了几轮弯路才定位——血泪:dev/装版/unpacked/codec 全被错排查过,最后靠 `ELECTRON_ENABLE_LOGGING` 抓到 `child-process(Utility) exit -2147483645`)。机制:点 source 开 `<video>` 预览 → Chromium 音视频解码 Utility 子进程间歇撞 sandbox 不兼容 → 旧的「崩了被动 `--no-sandbox` 重启」把整 app 中途重启=丢现场=用户眼里的「崩」。修:main.ts **启动即主动 `--no-sandbox`**(`build>=26200` via `os.release()`)+ 持久化 `user_data/no-sandbox.flag` 自愈 + 旧被动重启留兜底。**真机验**:重装后正常启动点 source 不崩。memory [[project_electron_version_policy]] 已更新(此 bug 运行时点视频预览触发、伪装成崩、抓日志法)。
- **`3f07a9d` 源下载钉 H.264/AAC —— ✅ 已调查+已实施(2026-06-06,commit `d9e5223`):视频解钉换 AV1、音频 AAC 留;dev 已验过(2026-06-06)保留**:当初当崩因钉的,**实为 26200 sandbox**(已由 `44ac68f` `--no-sandbox` 修),H.264 钉的原始理由(防崩)就此推翻。**代码三条消费路径全支持 AV1**:① 源预览 `<video>`([SourceTab.tsx:179](../desktop/src/renderer/workbenches/material/SourceTab.tsx#L179))= 原生 Chromium AV1 软/硬解;② 合成器预览+导出解码([Demuxer.ts:51](../desktop/src/renderer/engine/source/Demuxer.ts#L51) `isSupportedCodec` 显式列 `av01` + `buildDescription` 处理 av1C + 解码前 `VideoDecoder.isConfigSupported` 守门;ClipReader **不强制** `hardwareAcceleration`,可软可硬);③ 导出编码([webcodecsSink.ts:149](../desktop/src/renderer/engine/export/webcodecsSink.ts#L149))**输出恒 H.264+AAC、与源 codec 无关**(源 AV1 也是解码→GPU→重编码)。**音频 AAC 钉死不动**:[AudioReader.ts:46](../desktop/src/renderer/engine/source/AudioReader.ts#L46) 走浏览器 `decodeAudioData`,Opus-in-mp4 在此易"没声"(高风险,注释自承 esds 路径 silently no-output 才改用它),AAC 稳且音频流仅几 MB、省不了下载。**落地改法(`d9e5223`)**:[source_acquire.py:294](../src/core/source_acquire.py#L294) format 去掉 `[vcodec^=avc1]`、保留 `[ext=m4a]` → `bestvideo[height<=1080]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best`(省 ~1/3 视频下载;test 同步改成「AAC 音频优先 + 视频不钉」,6 passed)。**风险**:AV1 在 sandbox 修复后从没单独复验过(当初两事混查)。**✅ dev 验证已过(2026-06-06)**:dev 下一条 AV1 链接源 —— 点 source 不崩 + clip/news_desk 工作台预览能放 + 导出有画面有声,四项全正常(AV1 解码纯在渲染层,dev≡打包态,故 dev 足以 de-risk;冻结-only 规则只管 Python sidecar 死锁,不管渲染层 codec)。**保留 AV1(已确认与卡顿无关,别再 revert)**。dogfood 一度怀疑 AV1/60fps 致 clip/news_desk 预览卡(每 ~10s 一帧),**实为两个渲染层 bug,与 codec 无关**:① 预览错用导出专用的阻塞 `frameAtExact`(死等≤3s/帧;30fps 解码跟得上故无感,1080p60 暴露)— 修 `13b0dc5` 改用非阻塞 `frameAt`;② pump 只对 8 帧输出环背压、不管解码器输入队列 → 60fps 下 `decodeQueueSize` 涨到 GB — 修(`MAX_DECODE_QUEUE` 输入背压)。**教训**:断崖式(30fps 完美/60fps 崩)+ 同源原生 `<video>` 流畅 = 渲染逻辑 bug,非 codec/吞吐;且**改 renderer 必须 `dev.ps1` 整重启**(HMR 发旧 bundle,Ctrl+R 害我对着旧代码瞎调)。
- **installer 重打**(`build_sidecar`+`fetch_ffmpeg`+`build:win`,02:22,174.9MB):带上面全部 + 上一轮传输/i18n/路由/质检修复。HTTP 烟测 + 真机均过。

**✅ 完整 dogfood 通过(2026-06-06 20:16 installer,174.9MB,`5ec594c` HEAD)**:7 条全过 —— ① 嵌入 AI 装+ASR 不卡死 ② 路由不列禁用 provider ③ 质检本地化+点 #N 跳转 ④ 翻译选禁用 provider 报清晰错 ⑤ ClaudeCode 默认勾选 ⑥ 覆盖安装不丢 user_data ⑦ 点 source 不崩;另 **60fps AV1 导出在装版复验通过**(本块头部死锁修复)。AV1 解钉保留。**本轮 dogfood 收口,无遗留 bug。下一任务 = 下方「P3 收尾(CI/签名)」。**

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
