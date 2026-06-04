# P3 打包 / 分发设计

> **状态**:草案 / 2026-06-03 · 承接 [`electron-migration-design.md`](electron-migration-design.md)「剩余工作计划」P3 + §3.2 + §7.3
> **前置**:ADR-0008 终态(三插件零插件专属 Python)已达成;P0~P2 + P6 全完成。**当前 = 纯 dev 模式,零分发产物。**
> **决策已锁(2026-06-03 用户拍板)**:① sidecar = **PyInstaller onedir**(非 onefile)② **瘦装包 + 引导下载**。
> **纪律**:Windows-first([architecture-vision §3]);用户数据全部 install-local,绝不 %APPDATA%([[feedback_portable_data]]);非 AI 功能不被下载门槛堵死([[feedback_no_forced_downloads]]);早期=严谨锁定可演化基础([[feedback_early_stage_foundation]]);每步 build-green。

---

## 0. 现状摸底(实测,定方案的依据)

| 事实 | 实测来源 | 对打包的含义 |
|---|---|---|
| **`myenv` = 7.0 GB,严重污染** | `du -sh myenv` | **绝不能整包 ship。** 装了 `requirements.txt` 明令移除/不该有的:`nvidia` 2.0G(CUDA wheels)、`torch` 823M(requirements 明令 DO NOT install)、`sherpa_onnx` 288M(记忆称 2026-05-10 已删)、`onnxruntime`/`wandb`/`pandas`/`pyarrow`/`transformers`/`llvmlite`/`sympy` 等。myenv ≠ requirements.txt。 |
| **`requirements.txt` 才是真实运行时闭包** | 读 | 非 AI 核心:yt-dlp/requests/srt/google-genai/fish-audio-sdk/openai/json-repair/edge-tts/Pillow/pywin32(基本纯 Python + 轻量)。嵌入 AI(opt-in):faster-whisper(CTranslate2 原生)+ llama-cpp-python(CPU 档 wheel,**非 myenv 里那个 785M CUDA 版**)。 |
| **引导下载模式已落地** | `user_data/{runtimes,models}` 存在 + `core/env` + `core_rpc/methods/{env,models,gpu}.py` | Node 运行时引导(`runtimes`)、AI 模型下载(`models`)、GPU CUDA wheels 安装(`gpu`)都已有机制可复用。 |
| **sidecar 硬依赖 repo 布局** | `electron/sidecar.ts:73`、`main.ts:54` | spawn `<repoRoot>/myenv/Scripts/python.exe -m core_rpc.server`,cwd=repoRoot;`repoRoot = resolve(__dirname,"../../../")`。**打包态此假设全部不成立**——核心改造点。 |
| **ffmpeg 已有 packaged-aware 雏形** | `electron/ffmpeg.ts:52-64` | 优先 `process.resourcesPath/ffmpeg.exe`,否则 PATH。bundle ffmpeg 即生效,无需改这块。 |
| **userData 已 repo-local** | `main.ts:97` `app.setPath("userData", resolve(here,"../../user_data"))` | 打包态需改成 install-local(见 §4)。 |
| **sidecar 自己 bootstrap `src/` 上 sys.path** | `core_rpc/server.py:26-29` | `_REPO=dirname(dirname(__file__))`、`_SRC=_REPO/src`。打包后 `src/` 必须随 `core_rpc/` 一起进 onedir,保持相对布局。 |
| 无 electron-builder / 无 PyInstaller spec / 无构建脚本 | `package.json` + glob | Tk 的 `build_portable.py`/`build-portable.yml` 已在 P2 删;P3 从零搭。 |

---

## 1. 目标产物

- **单一 Windows 安装包**(electron-builder NSIS)+ 可选便携 zip。
- 装完**开箱即用的范围** = 项目管理 + 三插件(clip/news_desk/news_video 素材的非 AI 部分)+ 视频导出(WebCodecs,GPU 在 renderer)。**视频功能不依赖任何下载。**
- **首次/按需引导**(强引导可跳过):Node 运行时(yt-dlp JS 挑战)、嵌入 AI 运行时(faster-whisper/llama-cpp)、AI 模型、CUDA GPU 档。
- 体积目标:**基线装包 ~250–400 MB**(不含嵌入 AI 重依赖与模型)。

---

## 2. sidecar 打包(PyInstaller onedir)

### 2.1 干净依赖闭包(打包输入)—— 先决步骤

> **2026-06-04 更新**:依赖管理迁正统 uv 项目(`pyproject.toml` 单源 + `uv.lock`),`requirements*.txt` 已退役。权威 = **[ADR-0009](../adr/0009-uv-project-dependency-management.md)**。

**不碰污染的 myenv。** 冻结输入 = **base 档**(`pyproject.toml` 的 `[project.dependencies]`),从 `uv.lock` 装(传递依赖全锁、可复现):

- **三档模型**(详见 ADR-0009):
  - **base(随包冻结)** = `[project.dependencies]`:yt-dlp/requests/srt/google-genai/fish-audio-sdk/openai/json-repair/edge-tts/Pillow/pywin32 + `pip`(--vc-pip 要)。
  - **embedded-ai / gpu(运行时按需装,不进冻结)** = `[project.optional-dependencies]` extras:faster-whisper + llama-cpp-python(CPU)/ nvidia-* CUDA wheels。装进运行时可写 `py-extra`(见 §5.3),避冻结体积 + 封死 sealed site-packages 更新。
  - **build/dev 工具** = `[dependency-groups]`:pyinstaller(build group)/ pytest(dev)。永不进 `[project]` ⇒ 冻结天然排除。
- 构建脚本 `packaging/build_sidecar.ps1`:`uv venv .build/sidecar-venv --clear` → `uv sync --frozen --no-default-groups --group build`(base + pyinstaller,无 extras/dev)→ PyInstaller。
- **绝不**让 torch/sherpa/nvidia/wandb/pandas 进 base(extras 才有 nvidia;torch 永禁,见 ADR-0009 gotchas)。dev myenv 经 `UV_PROJECT_ENVIRONMENT=myenv uv sync --extra embedded-ai` 净化重建。

### 2.2 PyInstaller spec(`packaging/core_rpc.spec`)
- 入口 = `core_rpc/server.py`(entry,`python -m core_rpc.server` 的等价)。
- `onedir`(非 onefile,避免每次启动解压到 temp,§3.2)。
- **datas**:把 `src/` 整树纳入(server.py 运行时按 `_REPO/src` 找;打包后用 `sys._MEIPASS` 解析,见 §5.1 对 server.py 的小改),保持 `core_rpc/` 与 `src/` 的相对布局。
- **hiddenimports**:`methods/__init__.load_plugins()` 动态 import 插件 + provider 域,PyInstaller 静态分析抓不全 → **用 `collect_submodules` 整包收** `core`/`creations`/`materials`/`core_rpc`(比手列稳)。**实测全收成功**:三插件注册 + core 数据 + env 注册表都在。
- **入口 wrapper(实测必需)**:冻结后入口脚本以 `__main__` 运行、无父包上下文 → `server.py` 的相对 import(`from .dispatch import`)全断。spec 入口改 `packaging/sidecar_entry.py`(`from core_rpc.server import main`,把 sidecar 当包导入),**server.py 一行不改**、dev `-m` 路径不受影响。
- **原生 DLL 收集**:pywin32(`pywin32_system32`)、CTranslate2(若 base 含)——base 不含嵌入 AI 时这块最小化,是选 lean 的附带好处。
- 输出 `dist/core_rpc/`(含 `core_rpc.exe` + `_internal/`),打进 Electron `resources/sidecar/`。

### 2.3 体积预期
base 冻结(无 faster-whisper/llama/CUDA)≈ Python 运行时 + 上述纯/轻依赖 ≈ **80–150 MB**。嵌入 AI 运行时装时再落 user_data。**bundled ffmpeg/ffprobe(各 ~85MB,§6)使 NSIS 安装包从 ~137MB → ~182MB**(LZMA 压缩后 +45MB)。

---

## 3. Electron 打包(electron-builder)

- 加 `electron-builder` devDep + `package.json` build 配置(或 `electron-builder.yml`)。
- target:`nsis`(安装包)+ `portable`(可选 zip)。Windows x64。
- `extraResources`:`resources/sidecar/`(PyInstaller onedir)+ `resources/ffmpeg.exe` + `resources/ffprobe.exe`(见 §6)。
- electron-vite `build` 产 `out/{main,preload,renderer}` → builder 收 `out/` + extraResources。
- `appId` / 产品名 / 图标 / 版本(`package.json` version 现 `0.0.0` → 对齐 `pyproject.toml` 的 `0.3.5` 或独立版本线,待定)。
- **Win11 26200 sandbox 兜底**已在 `main.ts`([[project_electron_version_policy]]),打包态保留;`disable-gpu-sandbox` 的 dev concession(`main.ts:103`)打包前复审是否仍需。

**✅ 实测落地(2026-06-03,step 5)**:`VideoCraft-0.3.5-setup.exe` 127.7MB(NSIS)+ `release/win-unpacked/` 447.7MB,sidecar 正确随包 `resources/sidecar/core_rpc.exe`。`files` 只打 `out/**`+`package.json`(electron/ 零第三方运行时依赖,renderer 依赖 vite 已 bundle → 不打 node_modules,绕 pnpm 软链坑)。
- **⚠️ winCodeSign 符号链接坑(CI 必读)**:electron-builder 在 Windows eager 解压 `winCodeSign`(签名工具,归档含 macOS `.dylib` 符号链接);**非 admin / 无 Developer Mode 的机器** 7za 建符号链接失败(`SeCreateSymbolicLinkPrivilege` 缺)→ 整 build 挂,`--dir` 也不能幸免。**绕法 = `win.signAndEditExecutable:false`**(关签名 + rcedit 编辑 → 不再需要 winCodeSign)。代价:exe 用默认 Electron 图标、不签名。真图标 + 签名留 step 8 / CI(GitHub Windows runner 有符号链接权限,或开 Developer Mode)。
- **step 6 已折叠**:NSIS `perMachine:false` → 装 `%LOCALAPPDATA%\Programs\VideoCraft`(可写),paths.ts 的 exe 旁 `user_data` 无需 admin 即写,portable-data 满足。§9 的 userData 待决就此解决(便携包另算,但 NSIS per-user 已够)。

---

## 4. 路径解析:dev ↔ packaged(核心代码改造)

单一 seam:`app.isPackaged`。新增 `electron/paths.ts` 统一解析,`main.ts`/`sidecar.ts` 消费。

| 资源 | dev | packaged |
|---|---|---|
| sidecar 可执行 | `<repoRoot>/myenv/Scripts/python.exe -m core_rpc.server`(cwd=repoRoot) | `<resourcesPath>/sidecar/core_rpc.exe`(无需 python/cwd=repoRoot 假设) |
| `repoRoot`(src/core_rpc 根) | `resolve(__dirname,"../../../")` | 不再需要(冻结包自带 src/;sys._MEIPASS) |
| userData | `resolve(__dirname,"../../user_data")`(repo-local) | install-local:安装目录旁 `user_data/`(便携);NSIS 装到 Program Files 时该处只读 → 落 `<exeDir>/../user_data` 或显式可写的安装根。**待定:便携 zip vs NSIS 的可写根策略**(便携=exe 旁;NSIS=需选可写位置或退 `%LOCALAPPDATA%` 例外?与 portable-data 铁律冲突 → 倾向只出便携包 + NSIS 装到用户可写目录)。 |
| ffmpeg/ffprobe | PATH(`core/env` 检测) | `<resourcesPath>/ffmpeg.exe`(`ffmpeg.ts` 已支持) |

`sidecar.ts` 改:`SidecarOptions` 从 `{repoRoot}` 改成注入解析好的 `{command, args, cwd}`(packaged 走 exe,dev 走 python -m),其余收发逻辑不动。

---

## 5. sidecar 在打包态的运行时调整

### 5.1 `server.py` 的 `_REPO/_SRC` 解析
打包态 `__file__` 在 `_internal/` 下,`dirname(dirname())` 不再是 repo 根。改:冻结态(`getattr(sys,"frozen",False)`)用 `sys._MEIPASS` 作根;dev 态保持现状。src/ 经 spec 的 datas 进同一根。

### 5.2 native warmup
`core/ai/warmup.py` 的 `_NATIVE_MODULES`(ctranslate2/faster-whisper/llama_cpp)在 base 冻结里**不存在** → warmup 的 try/except 已容错(`server.py:103`)。装了嵌入 AI 后才需预热;预热模块解析要能看到 §5.3 的运行时 site。

### 5.3 嵌入 AI / GPU 运行时安装(opt-in)—— ✅ 已实现(step 7,2026-06-04)
冻结 onedir 的 site-packages 是 sealed/只读 → 运行时 pip 装的 faster-whisper/llama-cpp/CUDA wheels 不能进那里。**根因**:`gpu_install`/嵌入 AI 装包跑 `sys.executable -m pip`,冻结态 `sys.executable`=`core_rpc.exe`,它不解析 `-m pip` 而反起第二个阻塞 sidecar →「安装中…」卡死。

**实现方案(两个分叉用户拍板,见 task.md 本会话块)**:

1. **统一 py-extra seam = `core/runtime_extras.py`(单一所有者)**:
   - 安装目标恒 `user_data/runtimes/py-extra/`(走 `core.user_data.path`,与 `runtimes/node` 同级 = **运行时依赖跟着 install 走**)。**注意:不是 `models_dir`** —— `models_dir()` 可被 `keys/providers.json` 的 `models_dir` override 指到外置盘,py-extra 故意不跟随它(运行时绑 interpreter,数据才可漂移)。可写 + 随安装迁移,[[feedback_portable_data]]。
   - `ensure_on_sys_path()` 启动时 prepend py-extra 到 `sys.path[0]` + `os.add_dll_directory`(顶层 DLL 解析);idempotent;空目录 no-op。
   - `pip_command(args)` = 唯一 dev↔frozen 命令分叉:dev `[python, -m, pip, …]` / frozen `[core_rpc.exe, --vc-pip, …]`(**Fork A = 双入口自生子进程**:`packaging/sidecar_entry.py` 先查 argv,带 `--vc-pip` 就 `runpy` 跑 bundled pip 然后退出,**绝不进 main()**;复用现成 Popen 流式/取消逻辑;pip 与长驻 server 进程隔离)。
   - `install()` = `pip install --target <py-extra> --upgrade --only-binary :all: …`(`--only-binary :all:` 关键:冻结态避免 PEP517 sdist build 反起 `sys.executable`)。`uninstall()` = pip 不支持 `--target` 卸载 → 自己读 `*.dist-info/RECORD` 删文件 + 剪空目录。
   - **Fork B = dev+frozen 都装 py-extra + 恒 prepend**:dev 走的就是打包路径,消除「dev 正常/打包炸」盲区([[feedback_default_flip_vs_persisted_config]]),myenv 不被 opt-in extra 污染。
2. **bundle pip 进冻结包**:`pyproject.toml` 的 `[project.dependencies]` 含 `pip==26.1`(uv venv 默认无 pip);`core_rpc.spec` 加 `collect_submodules("pip")` + `collect_data_files("pip")`。
3. **gpu.py / gpu_install.py 认 py-extra**:`gpu._nvidia_roots()` 同时扫 `py-extra/nvidia` + dev venv site-packages(import 优先序);`ensure_cuda_dlls`/`cuda_available`/`gpu_install.is_installed` 全经它,CUDA wheels 装到 py-extra 后 providers 仍能在 load 时找到 DLL。
4. **嵌入 AI 装包 = `core/embedded_ai_install.py`**(镜像 `gpu_install`):装 `faster-whisper==1.2.1` + `llama-cpp-python==0.3.22`(CPU,`--extra-index-url …/whl/cpu`)到 py-extra;版本镜像 `pyproject` 的 `embedded-ai` extra(`tests/core/test_dependency_pins.py` 防漂移,ADR-0009)。
5. **RPC + UI**:`core_rpc/methods/embedded_ai.py`(status/install/uninstall jobs,镜像 gpu.py,流式 `progress.embedded_ai.<action>`)+ ModelManager `EmbeddedAiCard`(镜像 GpuCard)+ client.ts `embeddedAi*` + i18n zh/en。

**配套地基修复(step 7 顺带,packaged 必需)= sidecar user_data 注入**:packaged 态 Python `user_data_dir()` 原 `__file__`-relative → 落在 sealed/更新即抹的 `resources/` 下(models/settings/py-extra 全跟着丢)。修:`desktop/electron/paths.ts` 经新 `SidecarLaunch.env` 注入 `VC_USER_DATA`(packaged=`<exeDir>/user_data` 与 Electron userData 统一;dev=`<repo>/user_data` 保持现状),`sidecar.ts` 合并进子进程 env,`core/user_data.py` 优先认该 env。**这才让「py-extra 可写 + 随 install 迁移」在打包态真成立**(注:跟 install 走,不是跟可 override 的 `models_dir`)。

**测试**:`tests/core/test_runtime_extras.py`(命令构造 dev/frozen · py-extra 路径 · prepend idempotent · install 命令含 `--target/--only-binary/--extra-index-url` · dist-info 检测名归一 · uninstall 删 RECORD 文件)+ `tests/core_rpc/test_embedded_ai.py`(status/install 流式/非零退出失败,镜像 test_gpu)。pytest 108 / desktop typecheck + 212 vitest + build / i18n 494×2 全绿。

**打包态验证(命令行,2026-06-04 做完)**:重打包(`build_sidecar.ps1` + `pnpm build:win`)→ `VideoCraft-0.3.5-setup.exe` 130.6MB + `win-unpacked/resources/sidecar/core_rpc.exe`。**冻结 `--vc-pip install` 决定性验证通过**:打包产物 `core_rpc.exe --vc-pip install six --target X --only-binary :all:` → exit 0、six.py 落 X。**坑修**:撞 `DistlibException: Unable to locate finder for 'pip._vendor.distlib'`(pip 内置 distlib 按包 `__loader__` 类型查 resource finder,PyInstaller 冻结 loader 不在注册表)→ `sidecar_entry.py` 在 `--vc-pip` 跑 pip 前注册冻结 loader(传 loader 实例;onedir 下 distlib data 物理在 `_internal`)。`build_sidecar.ps1` 加 `uv venv --clear`(防复用 stale venv 漏掉新 pin)。

**⚠️ 剩余打包态终验(GUI/真机盲区)**:① 真包 faster-whisper/llama-cpp 到 py-extra(six 已证 pip 机制;真包额外验 llama-cpp CPU wheel 从 abetlen 索引、ctranslate2 binary wheel 在冻结 interpreter tag 匹配)② 装后 ASR/本地 LLM 真能跑(py-extra prepend + warmup import 链)③ CUDA wheels 装 py-extra 后 `nvidia/*/bin` DLL 解析。装 installer 后 GUI 走一遍。

---

## 6. 二进制依赖

| 依赖 | 策略 | 依据 |
|---|---|---|
| ffmpeg / ffprobe | **✅ 随包(用户拍板 2026-06-04)** | `packaging/fetch_ffmpeg.ps1` 构建前拉 pinned gyan.dev essentials(7.1.1,含 libx264/h264_nvenc)抽 `ffmpeg.exe`+`ffprobe.exe` 进 `desktop/resources/`(gitignore);`electron-builder.yml extraResources` 复制到 `<app>/resources/`;`paths.ts` 的 `extraPath=process.resourcesPath` 经 `sidecar.ts` 大小写正确地 prepend 到 sidecar PATH → Python 侧 `shutil.which` + **yt-dlp FFmpegMerger(1080p DASH 合并)**都认到。**为什么 bundle 不托管下载**:ffmpeg 是主线 YouTube 1080p 的硬依赖(分离流合并),又是 stable 包(不像 yt-dlp 追 YouTube)、几乎不用更新——一次性 +45MB(压缩后)换"永远在、不用管"。详见 ADR-0009 §10 的稳定性/更新论证。 |
| Node.js(yt-dlp JS 挑战) | **引导**到 `user_data/runtimes`(已落地) | 仅 yt-dlp 部分链接需要;`core/env` 已有 Node 下载安装。 |
| 嵌入 AI 运行时(faster-whisper/llama-cpp) | **opt-in 引导**装 `user_data/runtimes/py-extra`(§5.3) | AI 重依赖,opt-in([[feedback_no_forced_downloads]])。 |
| AI 模型 / CUDA wheels | **绝不随包**,运行时下载 user_data(已落地) | 铁律 + 体积。 |
| 字体 | 系统 `C:/Windows/Fonts`(现状) | §3.2 既定。 |

---

## 7. 构建管线

- `packaging/` 新目录:`build_sidecar.ps1`(`uv sync --frozen` 建 base env → PyInstaller → 产 `resources/sidecar/`)+ `core_rpc.spec`。依赖单源 = repo 根 `pyproject.toml` + `uv.lock`(ADR-0009)。
- `desktop/package.json` 加脚本:`build:win`(electron-vite build → electron-builder)。
- 顺序:`build_sidecar.ps1`(uv sync 冻结 sidecar)→ `fetch_ffmpeg.ps1`(拉 pinned ffmpeg 进 resources,幂等)→ `pnpm build:win`(electron-vite build + electron-builder)。
- CI:GitHub Actions Windows runner(P2 删的 `build-portable.yml` 是 Tk 的;这是全新 Electron 管线),**先本地跑通再上 CI**。

---

## 8. 实施步骤(增量、每步 build-green、低风险优先)

> **原则**:路径 seam 与构建管线解耦——seam 可在无任何打包产物时就写好并经 dev 回归;构建管线产物后再端到端验。**TS 替代/seam 测好前不破坏 dev 启动。**

1. **路径 seam(纯 dev 可验)**:新增 `electron/paths.ts`(`app.isPackaged` 分发 sidecar command/args/cwd + userData + resources)。`sidecar.ts` 改吃注入式 `{command,args,cwd}`。`main.ts` 接线。**dev 行为字节不变**,typecheck + build + dev 启动回归。
2. **server.py 冻结态根解析**(§5.1):`sys.frozen`/`_MEIPASS` 分支;dev 不变;pytest 不受影响(非冻结)。
3. **拆 requirements-base.txt** + `packaging/build_sidecar.ps1` + `core_rpc.spec`;本地跑出 `resources/sidecar/core_rpc.exe`,命令行手验它能起 stdio loop(echo 往返)。
4. ✅ **ffmpeg 随包(2026-06-04)**:`fetch_ffmpeg.ps1` 拉 pinned gyan essentials 进 resources;extraResources 复制到 `<app>/resources/`;sidecar PATH 注入(`paths.ts extraPath`)→ 命令行 E2E 验过 frozen sidecar 经注入 PATH 认到 ffmpeg 7.1.1 + ffprobe。
5. **electron-builder 配置** + `build:win`;出 NSIS;**安装到干净目录端到端跑一遍**(开项目→clip/news_desk 导出 mp4→素材建实例)。
6. **userData install-local 落位**(§4 待定项定夺)+ 便携/NSIS 可写根策略。
7. ✅ **嵌入 AI / GPU opt-in 安装**(§5.3,2026-06-04):py-extra seam(`core/runtime_extras.py`)+ `--vc-pip` 双入口 + sys.path prepend + gpu/embedded_ai 装包改道 py-extra + `embedded_ai.*` RPC/UI + `VC_USER_DATA` 注入。build-green。**打包态终验留最后一轮**(见 §5.3 末 ⚠️)。
8. **打磨**:图标/版本/产品名;`disable-gpu-sandbox` 复审;CI;最后重打包做打包态终验(含 §5.3 的 AI/GPU 安装真机验 + ffmpeg 1080p 合并 GUI 验)。

---

## 9. 待决 / 风险

- ✅ **userData 可写根**(§4/§5.3):step 6 NSIS `perMachine:false` 装 `%LOCALAPPDATA%` 可写;step 7 `VC_USER_DATA` 注入让 Python sidecar user_data 与 Electron 统一落 `<exeDir>/user_data`(install-local + 更新存活)。便携 zip 另算但 NSIS per-user 已够。
- **PyInstaller × 动态插件加载**:`load_plugins()` 全靠 hiddenimports 列全,漏一个则该域运行时 ImportError。需逐域核对(creations/materials/ai providers)。
- ✅ **嵌入 AI / py-extra sys.path 注入 + nvidia DLL 路径**(§5.3):已实现并单测(dev),`core/runtime_extras.py` + `gpu._nvidia_roots()` 同时认 py-extra。**剩打包态真机验**(wheel 真能装 + 装后能跑,见 §5.3 末)。
- ✅ **冻结闭包可复现 + 依赖单源**(2026-06-04):迁正统 uv 项目,`pyproject.toml` 单源 + `uv.lock` 锁全传递闭包,`build_sidecar.ps1` 走 `uv sync --frozen`。详见 [ADR-0009](../adr/0009-uv-project-dependency-management.md)。
- **版本线**:`package.json 0.0.0` vs `pyproject 0.3.5` vs VideoCraft `0.3` tag — P3 出包前统一。

---

## 10. 发布 checklist(切发布版前)

> yt-dlp 是唯一必须追新的包(追 YouTube 变化);内置那份过期会让首次运行下载失败。环境页「更新」按钮(→ py-extra)是逃生口,但首发那份必须新鲜。其余依赖按 dep-update 周期主动 bump。

1. **bump yt-dlp 到 latest**:改 `pyproject.toml` `[project.dependencies]` 的 `yt-dlp==<latest>`。
2. `uv lock` → 提交 `uv.lock`(其余 pin 顺带刷新可复现闭包)。
3. `myenv/Scripts/python.exe -m pytest tests/`(含 `test_dependency_pins` mirror)全绿。
4. `packaging/build_sidecar.ps1`(`uv sync --frozen` 重打冻结 sidecar)+ `packaging/fetch_ffmpeg.ps1`(幂等;clean checkout 时 resources/ 为空需拉,bump ffmpeg 版本时也跑)。
5. `pnpm build:win`(electron-builder NSIS + win-unpacked)。
6. **打包态终验**:`d:\tmp\e2e_ytdlp.py`(yt-dlp detect→install→detect)+ 嵌入 AI 安装 + GUI 真机过一遍(§5.3 末的 ASR/LLM/CUDA)。
- **`disable-gpu-sandbox`**(`main.ts:103`)是 dev concession,打包前复审。
