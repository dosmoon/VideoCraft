# VideoCraft 内嵌 AI 技术选型

> 本文只覆盖 VideoCraft 自身进程内置（portable）形态的 AI 能力选型。
> aistack 网关、云 API 是另外两条平行产品线，详见 §2 三层定位。

## 1. 项目背景与目标

VideoCraft 现在已经能通过 aistack / 云 API 拿到 ASR / TTS / 翻译能力，但二者都有门槛：

- aistack 需要用户自己跑 Docker + GPU 配置
- 云 API 需要 key + 网络 + 付费

本期目标：让普通自媒体用户**点开 exe → 不配置任何外部服务 → 完整跑通 YouTube → 字幕 → 翻译 → 烧录**，质量达到可发布水准。

## 2. 三层定位（与 aistack / 云 API 的关系）

| 形态 | 目标用户 | 部署 | 默认质量 | 切换条件 |
|---|---|---|---|---|
| **VideoCraft 内嵌（本文）** | 普通自媒体用户 | exe portable，零外部依赖 | 中高（4060 Laptop 基线） | 默认 |
| **aistack 网关** | 进阶 / 工作室 | Docker + GPU | 生产级（Qwen3-TTS 0.6B 等） | 用户配置 base_url |
| **云 API** | 顶配质量需求 | 网络 + key | 最高 | 用户配置 key |

三层在 VideoCraft 上层完全对等可切换，详见 §7 抽象层。

## 3. 硬件基线

**4060 Laptop（8GB VRAM, 16GB RAM）** —— 自媒体用户最低配。

由此带来的选型差异：

- 默认档位直接给中高质量模型，不做"弱机器降级"路径
- llama.cpp / sherpa-onnx 走 CUDA 加速
- 词级时间戳、整段翻译这类计算密集任务都按 GPU 推理预算
- 8GB VRAM 装不下"全部模型同时驻留"，需要 §8 的调度策略

## 4. 核心约束

- 用户零外部依赖（不要求 Docker / Python / 单独 runtime）
- Windows 优先（macOS / Linux 后续，不是本期阻塞项）
- 离线优先，隐私安全
- 安装包 ~200 MB（受 GitHub Release 单文件 2 GB 上限约束；模型走首启下载向导）
- MIT 兼容
- 中英双语为主

## 5. 技术选型总览

| 能力 | 选型 | 协议 |
|---|---|---|
| ASR | sherpa-onnx + Whisper（强制开启 word timestamps） | sherpa: Apache 2.0 / Whisper: MIT |
| TTS | sherpa-onnx + Kokoro | sherpa: Apache 2.0 / Kokoro: Apache 2.0 |
| VAD | sherpa-onnx + Silero VAD | Apache 2.0 / MIT |
| 翻译 | llama-cpp-python + Qwen3 | MIT / Apache 2.0 |
| 模型分发 | 按需下载 + ModelScope / hf-mirror / HF fallback | — |

## 6. 模型档位（4060 Laptop 基线）

档位术语统一用三档，避免"默认"二义：

- **首启档**：首次启动**强引导下载**（约 1.8 GB），下完即可跑通含翻译的端到端；可跳过——VideoCraft 还有大量非 AI 功能（YouTube 下载、剪辑、烧录、PPT 合成、切片稿等）不需要这些模型也能用
- **推荐档**：4060 Laptop 基线下的目标质量，首启档下完后引导用户继续下载（约 7 GB），可跳过
- **顶配档**：质量优先，用户手动选（按需下载）

> 模型不打进安装包是被动选择：GitHub Release 单文件硬上限 2 GB，留 buffer 必须 < 1.8 GB；行业（ComfyUI / Ollama / LM Studio / DaVinci Resolve）都走"瘦安装包 + 首启下载"模式，自媒体用户对此有心理预期。

### 6.1 ASR

| 档位 | 模型 | 大小 | 说明 |
|---|---|---|---|
| 首启档 | Whisper small | ~480 MB | 首启下载，立刻可跑通 |
| **推荐档** | Whisper large-v3-turbo | ~1.6 GB | 4060 上接近实时，质量接近 large-v3 |
| 顶配档 | Whisper large-v3 | ~3 GB | 最强精度，速度慢一档 |

silero-vad（~2 MB）所有档位都装，用于段落切分 + 防 Whisper 幻觉。

**句子级时间戳必须有**（segments[] 完整）；**词级时间戳尽量开**（后端支持就开，不支持就空数组）。注意：标准发布的 sherpa-onnx Whisper int8 模型**没有** cross-attention export，词级时间戳出不来——这影响"按词高亮"等高级特效，不影响主流程。cue-sizing 由烧录层做。详见 `feedback_asr_no_client_cue_sizing`。

### 6.2 TTS

| 档位 | 模型 | 大小 | 说明 |
|---|---|---|---|
| 首启档 | Kokoro mini（精简音色） | ~150 MB | 首启下载 |
| **推荐档** | Kokoro 多语言版 | ~330 MB | 一个模型覆盖中英 + 多音色 |
| 备选 | Piper huayan + libritts | ~180 MB | 极简 fallback |

> **Kokoro 中文音色质感 vs aistack 的 Qwen3-TTS 0.6B 有明显差距**。这是内嵌形态的天然上限。
> UI 必须给用户清晰的"本地够用 / aistack 高质量 / 云 API 顶配"三档入口，让有质量需求的用户知道升级路径。

### 6.3 翻译 LLM

| 档位 | 模型 | 大小 | 量化 | 4060 期望 |
|---|---|---|---|---|
| 首启档 | Qwen3-1.7B | ~1.2 GB | Q4_K_M | 首启下载，质量够日常字幕 |
| **推荐档** | Qwen3-8B | ~5 GB | Q4_K_M | prefill ≥ 50 tok/s |
| 备选 | Qwen3-4B | ~3 GB | Q4_K_M | VRAM 紧张时自动降档 |
| 顶配档 | Qwen3-14B | ~9 GB | Q4_K_M | 16GB+ VRAM 用户手动选 |

8GB VRAM 同时驻留 Whisper-large-v3-turbo + Qwen3-8B 较紧张，靠 §8 串行调度解决。

### 6.4 首启与升档流程

**第一阶段：首启强引导下载（可跳过）**

```
欢迎使用 VideoCraft
建议下载基础 AI 模型（约 1.8 GB，预计 X 分钟）以解锁字幕生成 / 翻译 / 配音：

  Silero VAD            (  2 MB)
  Whisper small         (480 MB)
  Kokoro mini           (150 MB)
  Qwen3-1.7B Q4_K_M     (1.2 GB)

下载源：[ ModelScope（国内推荐） ▼ ]   切换 ▶

[ 跳过，先用非 AI 功能 ]   [ 开始下载 ]
```

跳过后用户仍可用：YouTube 下载 / 剪辑 / 烧录（无字幕）/ PPT 合成 / 切片稿 / 调用 aistack 或云 API（如已配置）等。
任何 AI 入口被点击时再次弹出此引导。下载完成后即可完整跑通"YouTube → 字幕 → 翻译 → 烧录"。

**第二阶段：升档引导（可跳过）**

```
检测到你的显卡：NVIDIA GeForce RTX 4060 Laptop GPU (8GB)
推荐下载「推荐档」模型集（约 7 GB，预计 X 分钟）以获得最佳质量。

[x] Whisper large-v3-turbo  (1.6 GB) — ASR 质量提升明显
[x] Qwen3-8B Q4_K_M         (5.0 GB) — 翻译质量提升明显
[x] Kokoro 多语言版          (0.3 GB) — 音色丰富度提升

[ 跳过，先用首启档 ]   [ 后台下载 ]
```

用户可随时在「设置 → 模型管理」重新触发升档或切档。

## 7. 抽象层：复用现有 provider 模式

VideoCraft `core/ai/` 已经有成熟的 provider 体系（aistack / lemonfox / claude_code / fish_audio / gemini / openai_compat），事实抽象层就是它，本期不另起炉灶。

### 7.1 现有契约

每个 provider 是一个 module，暴露顶层函数：

```python
# core/ai/providers/<name>.py
def transcribe(audio_path, *, model_name, language, on_event, cancel_token, ...) -> dict
def synthesize(text, output_path, *, model_name, voice_id, ..., cancel_token) -> None
```

返回的 dict 是 verbose_json shape（与 aistack `/v1/audio/transcriptions` 响应同形）：

```python
{
    "language": "en",
    "duration": 17.18,
    "text": "...",
    "segments": [{"id": 0, "start": 0.81, "end": 7.14, "text": "..."}, ...],
    "words":    [{"start": 0.81, "end": 0.99, "word": "The"}, ...],
}
```

`router.py` 按字符串 provider 名分发，配置层（`config.py` / `tiers.py`）决定用哪个。**这就是 VideoCraft 的事实抽象层**——dict shape 是契约，模块函数签名是 ABI。

### 7.2 与 aistack 语义对齐（不引入 Pydantic）

- 字段名、segments / words 双层结构、language / duration 等**已经**对齐 aistack `integration.md` §4
- 错误统一走 `core/ai/errors.py` 的 `AIError(Kind, provider, message)`，`Kind` 已映射 aistack envelope 的 5 种 kind
- 不引入 Pydantic types.py / Protocol class——会和事实 dict 契约形成两套平行类型系统，无收益

### 7.3 本期新增 provider

- `core/ai/providers/sherpa.py`：in-process sherpa-onnx，暴露 `transcribe` / `synthesize`
- `core/ai/providers/llama_cpp.py`：in-process llama-cpp-python，暴露翻译入口（具体接口形态参考现有翻译模块再定）

### 7.4 与现有架构的衔接

- 必须走 `from core import ai`（参考 refactor M1~M6）
- prompt 必须经 `core.prompts.get`（不直接拼字符串）
- 错误统一抛 `AIError`，Kind 沿用现有枚举
- on_event 回调命名沿用现有 provider 习惯（`request_summary_local` / `state_processing` / `state_done` / `stream_warning` 等）

## 8. VRAM 调度

8GB VRAM 装不下 "Whisper-large-v3-turbo + Qwen3-8B + Kokoro" 全驻留。策略：

- pipeline 默认串行执行：ASR 完 → 释放 → 翻译完 → 释放 → TTS
- 模型懒加载 + LRU 释放
- 提供"全部驻留模式"给 16GB+ VRAM 用户（速度优先）
- 显存不足时自动降档 Qwen3-8B → 4B 并明确提示用户

## 9. 模型分发

### 9.1 路径（portable 原则：一切在 repo 内）

**统一存放：`<repo>/user_data/models/`**

VideoCraft 是 portable 应用，**绝不**把模型 / 缓存 / 用户数据扔到 `%APPDATA%` / `%LOCALAPPDATA%` / `~/Library` / `~/.config` 等系统目录。理由：

- 自媒体用户 C 盘普遍紧张，几 GB 的 AI 模型不能凑热闹挤系统盘
- 用户卸载 / 迁移 / 备份 VideoCraft 应该是「整个目录拷走」一步完成，不能有散落状态
- 用户能直接打开模型目录眼见为实，删旧模型释放空间是 file explorer 一拽的事

子目录约定：
- `user_data/models/sherpa/`（sherpa-onnx 系列）
- `user_data/models/llama/`（llama-cpp-python GGUF）
- `user_data/models/hf/` / `modelscope/` / `nemo/` / `torch/`（已存在的各 ML 框架缓存，复用）

可通过设置 → 模型目录改写到外置盘（适合 4060 笔记本 SSD 较小、把模型搬到机械盘的场景）。`router.set_models_dir(path)` 已具备此能力。

### 9.2 下载源 fallback 顺序

1. ModelScope（国内默认）
2. hf-mirror.com
3. HuggingFace 官方
4. 用户自定义 URL

自动探测网络可达性，失败按顺序切换。

### 9.3 工程清单（单独排期，不能漏）

- [ ] 断点续传（aria2c 子进程 / 自实现 multi-part）
- [ ] SHA256 校验 + 损坏自动重下
- [ ] 多线程下载进度合并 UI
- [ ] 磁盘空间预检
- [ ] 模型版本 metadata + 升级策略（旧版保留 / 删除）
- [ ] 首启引导（推荐档位 + 一键下载）
- [ ] 模型占用统计 + 一键清理
- [ ] 「在 file explorer 中显示模型目录」按钮
- [ ] 模型目录搬家工具（把整个 models/ 移到外置盘并更新配置）

预估工时：1~2 周。

## 10. 关键功能实现

| 功能 | 实现要点 |
|---|---|
| 视频分句 | Whisper segment 时间戳（words 后端支持就给）；cue-sizing 在烧录层 |
| 防幻觉 | VAD 预处理 + 重复文本检测 + temperature fallback |
| 中英混合识别 | Whisper 自动检测 + 用户可手动指定 |
| 风格预设 | Whisper initial_prompt + Qwen3 翻译 system prompt |
| 长文本 TTS | 自行切分 + 拼接 + 段间停顿 |
| 翻译一致性 | Qwen3 整段输入 + 术语表上下文 |
| 字幕长度约束 | 烧录层 cue-sizing + Qwen3 prompt 约束双保险 |

## 11. 不在本期范围

- 实时流式 ASR / TTS（aistack 已经做了，本地不重复）
- 声音克隆 / 情感 TTS（属于 aistack / 云 API 的差异化能力）
- 说话人分离（diarization）
- SSML

## 12. 风险与对策

| 风险 | 对策 |
|---|---|
| llama-cpp-python Windows CUDA wheel 安装麻烦 | 内置 CPU fallback；GPU 加速包提供一键安装脚本 |
| sherpa-onnx 段错误拖死主进程 | 本期接受；未来若成痛点，再加进程隔离（同协议 in-process → 子进程） |
| Kokoro 中文音色被嫌弃 | UI 第一时间引导 aistack / 云 API 升级路径 |
| 8GB VRAM 装不下双模型 | §8 串行调度；自动降档 Qwen3-4B |
| HuggingFace 下载慢 | ModelScope / hf-mirror 自动 fallback |
| 模型文件占用磁盘 | 统计 + 一键清理 UI |
| Whisper-large-v3-turbo 输出质量回退 | 提供"切回 large-v3"开关 |

## 13. 安装包预估

| 组成 | 大小 |
|---|---|
| 应用代码 + Tk + pywebview | ~80 MB |
| sherpa-onnx 二进制 | ~30 MB |
| llama-cpp-python（含 CUDA 运行时分发） | ~50 MB |
| **总计（安装包）** | **~200 MB** |

模型不进安装包，全部走首启下载向导：

| 阶段 | 体积 | 来源 |
|---|---|---|
| 安装包（GitHub Release） | ~200 MB | 用户下载 |
| 首启强引导下载（首启档，可跳过） | ~1.8 GB | ModelScope / hf-mirror / HF |
| 升档可选下载（推荐档） | ~7 GB | 同上 |
| 顶配按需 | +9 GB | 同上 |

> **硬约束**：GitHub Release 单文件上限 2 GB，安装包必须远低于此（留 buffer 给二进制升级）。
> 这也对齐 ComfyUI / Ollama / LM Studio / DaVinci Resolve 等同类工具的"瘦安装包 + 首启下载"模式，自媒体用户对此有心理预期。

## 14. 决策记录

| 决策 | 替代方案 | 选择理由 |
|---|---|---|
| sherpa-onnx 而非 whisper.cpp + piper | 也是单二进制方案 | 一个引擎搞定 ASR+TTS+VAD |
| 抽象层走 in-process（语义对齐 aistack） | 起本地 HTTP server 复刻 aistack | portable 打包简单、零序列化开销，单用户桌面不需要 HTTP |
| 数据类型在 core/ai/types.py 自维护 | 抽独立 pip 包 VideoCraft+aistack 共享 | 两边节奏不同步，强共享反而卡住一方 |
| 推荐档 Qwen3-8B 而非 4B | 4B 体积小 | 4060 Laptop 跑 8B 没压力，质量明显更好 |
| 模型不进安装包，走首启下载向导 | 内置首启档进安装包 | GitHub Release 单文件 2 GB 上限；ComfyUI / Ollama 等同类工具都这样做，用户预期正常 |
| 首启档下载 ~1.8 GB（含 Qwen3-1.7B） | 不下翻译模型，等推荐档 | 首启就要能跑通"含翻译"端到端，否则首启体验残缺 |
| 首启下载是强引导可跳过，不强制 | 强制下载完才能用 | VideoCraft 还有大量非 AI 功能；强制会劝退只想用剪辑/下载/烧录的用户 |
| 三档术语（首启/推荐/顶配）而非"默认/顶配" | 沿用"默认" | "默认"二义：是装好就有还是推荐目标？三档术语清晰 |
| 词级时间戳尽量开（不强求） | 硬要求 | 标准 sherpa Whisper int8 模型不导出 cross-attention，词级出不来；句子级够主流程，词级影响"按词高亮"等高级特效 |
| Whisper 而非 Zipformer 默认 | Zipformer 时间戳更准 | Whisper 多语言更稳，且开 word timestamps 后已够用 |
| 本地 LLM 翻译而非 NMT 模型 | NMT 模型更小 | LLM 翻译质量明显更好，4060 上速度也够 |
| Kokoro 而非 Piper 默认 | Piper 体积小 | Kokoro 质量明显更好，体积差距可接受 |
| 沿用现有 provider 模式（dict + 模块函数） | 新建 Pydantic types.py + ASRBackend Protocol | 现状已是事实抽象层；新建会形成两套平行类型系统、无收益还要双倍维护 |

## 15. 实施路线

1. 实现 `core/ai/providers/sherpa.py` 的 `transcribe`，端到端跑通一段样片（含 word timestamps，对齐现有 dict shape）
2. router / config / tiers 注册 sherpa provider，UI 加入"内嵌"档
3. 实现 `core/ai/providers/sherpa.py` 的 `synthesize`（Kokoro）
4. 实现 `core/ai/providers/llama_cpp.py`（Qwen3 翻译入口，对齐现有翻译 provider 形态）
5. 模型分发系统（§9 工程清单）单独排期
6. UI 三层定位入口完善（首启/升档对话框、设置→模型管理）

## 16. 参考链接

- sherpa-onnx: <https://github.com/k2-fsa/sherpa-onnx>
- sherpa-onnx 文档: <https://k2-fsa.github.io/sherpa/onnx/>
- llama.cpp: <https://github.com/ggml-org/llama.cpp>
- llama-cpp-python: <https://github.com/abetlen/llama-cpp-python>
- Whisper 模型: <https://huggingface.co/ggerganov/whisper.cpp>
- Kokoro 模型: <https://huggingface.co/hexgrad/Kokoro-82M>
- Qwen3 模型: <https://huggingface.co/Qwen>
- ModelScope 镜像: <https://modelscope.cn/>
- aistack 协议（权威）: 见上游 repo `docs/api/integration.md`

---

**文档版本：** v2.0（基于 v1.0 草稿评估后重写）
**状态：** 待实施
**下一步：** 实现 `core/ai/providers/sherpa.py` 的 `transcribe` → 跑通 word-level 端到端样片
