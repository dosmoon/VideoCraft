# ADR-0009: Python 依赖管理 = 正统 uv 项目（pyproject 单源 + uv.lock）

- **状态**: Active
- **决定日期**: 2026-06-04

> 实施细节（档模型、build_sidecar 流程、dev 重建命令、发布 checklist）在
> [`docs/draft/packaging-design.md`](../draft/packaging-design.md) §2.1 / §5.3 / §10。
> 本 ADR 只钉决策的 why + 边界 + 不变量 + 保留的 gotchas。

## 决定

VideoCraft 的 Python 依赖管理迁到**正统 uv 项目**：**`pyproject.toml` 做全部版本 pin 的单一权威源**，`uv.lock` 锁死整个传递闭包，`uv sync` 同时驱动 dev 环境与 PyInstaller 冻结输入。退役 `requirements.txt` + `requirements-base.txt`。

依赖分三档，按用途映射到 pyproject 的不同段：

| 档 | pyproject 位置 | 装到哪 | 谁装 |
|---|---|---|---|
| **base**（冻进 exe） | `[project.dependencies]` | PyInstaller onedir | `build_sidecar.ps1` 经 `uv sync --frozen --no-default-groups --group build` |
| **embedded-ai / gpu**（运行时 opt-in） | `[project.optional-dependencies]` extras | `user_data/runtimes/py-extra` | 运行时 `core.runtime_extras`（packaged）/ `uv sync --extra`（dev） |
| **dev / build 工具** | `[dependency-groups]`（PEP 735） | myenv | `uv sync`（dev 默认含 `dev` group；`build` group = pyinstaller） |

`pip==26.1` 留在 base（冻结后 `--vc-pip` 运行时装 extras 要它）。`package = false`（VideoCraft 从 `src/` 跑，不是可安装包）。

## 为什么

两个真问题触发本决策（2026-06-04，由「内置 yt-dlp 可更新」延伸出来）：

1. **冻结闭包不可复现**：旧 `requirements-base.txt` 只 `==` 钉死**直接**依赖，**传递**依赖（openai 带的 pydantic/httpx 等）在 build 时浮动到 latest-compatible。同一份 requirements，今天和下月 build 出的冻结包可能不同。`uv.lock` 锁死全闭包根治（实测 92 包全锁，pydantic 钉到 2.13.4）。
2. **版本 pin 散在 3+ 处手动同步**：`faster-whisper==1.2.1` / `llama-cpp-python==0.3.22` 既在 `requirements.txt` 又在 `embedded_ai_install.py` 常量；`requirements-base.txt` 又跟 `requirements.txt` 锁步；`gpu_install.py` 的 nvidia-* 干脆没钉版本。pyproject 做单源消除人肉同步。

被否决的替代：
- **`uv pip compile` 出 `.in/.lock` 双文件**（BACKLOG 原设想）——改动小，但仍是「requirements 风格」，没拿到正统 uv 项目的 `uv sync` 一致性（dev↔freeze 同一 lock）。用户拍板走正统。
- **运行时档（embedded-ai/gpu）也由 uv sync 在 packaged 装**——不可行：packaged 装进 `py-extra` 用 `pip --target`（冻结解释器 sealed，§5.3），不走 uv；且 cu124 llama-cpp 与 cpu llama-cpp 不能同处一个 lock。
- **运行时档 pin 不入 pyproject**（R3，只迁 base+dev）——没达到单源；选了 R2（见「如何应用」§2）。

## 如何应用

改依赖、build 脚本、运行时安装器前先读本 ADR。不变量：

1. **pyproject 是唯一 pin 权威**。升级任何依赖 = 改 `pyproject.toml` → `uv lock` → commit `uv.lock`。绝不再手写 requirements 文件。
2. **运行时档 pin = 镜像 + 测试防漂移（R2）**。`embedded_ai_install._PACKAGES` / `gpu_install._TOP_LEVEL` 保留硬编码常量（运行时代码最简、不往冻结里塞生成物），但 **`tests/core/test_dependency_pins.py` 断言它们 == pyproject 对应 extra**，漂移即红。index URL（abetlen cpu/cu124）是安装机制不是版本，留安装器常量。
3. **冻结只含 base**。`build_sidecar.ps1` 用 `uv sync --frozen --no-default-groups --group build`：恒装 `[project.dependencies]`，去掉默认 `dev` group，只加 `build`（pyinstaller），不传 `--extra` ⇒ embedded-ai/gpu 天然不进冻结。
4. **dev = myenv，经 `UV_PROJECT_ENVIRONMENT=myenv uv sync --extra embedded-ai`**。环境仍在 `myenv/`、仍用 `myenv/Scripts/python.exe`（记忆 project_venv 不变）；不建 `.venv` 兄弟环境。GPU dev 用 `--all-extras` 取回 nvidia 档。
5. **yt-dlp 发布前 bump latest**。它是唯一必须追新的包（追 YouTube 变化）；保留精确 pin，每次切发布版手动顶到 latest（packaging-design.md §10 checklist）。「可更新」的运行时入口（环境页更新按钮 → py-extra）是逃生口，但首发那份必须新鲜。

### 从退役的 requirements.txt 抢救的 gotchas（别丢）

- **绝对禁止把 `torch` 装进 AI venv（base 或 embedded-ai）**：`ctranslate2.converters.transformers` 有 `try: import torch`，装了就 eager 加载它捆的 cudnn DLL，与我们 PATH 上的 `nvidia-cudnn-cu12` 冲突（Error 127）。faster-whisper 本身不需要 torch（converters 是离线用）。
- **`llama-cpp-python` wheel 在 PyPI 外**：Windows 上源码构建会因 vendored llama.cpp 路径超 MAX_PATH 失败。必须用 abetlen 预编译索引——CPU 档 `…/whl/cpu`（`pyproject [tool.uv.sources]` 已配，dev+lock 走它）；GPU 档 `…/whl/cu124`（运行时 `--force-reinstall --no-deps` 替换 CPU 那份，纯运行时操作，不入 lock）。
- **nvidia-* ABI 敏感**：cublas/cudnn 大版本须配 CTranslate2 的构建版本（当前钉的 4 个版本对 ctranslate2 4.7.1 验过）。升 ctranslate2 时同步 bump pyproject `gpu` extra + `gpu_install._TOP_LEVEL`（mirror 测试会提醒）。
