# sherpa-onnx 弯路复盘

**日期范围**: 2026-05-08 ~ 2026-05-10
**结论**: sherpa-onnx 在 VideoCraft 内嵌 AI 层全量回退;ASR 改用 faster-whisper (CTranslate2),TTS 改用 edge-tts。
**移除提交**: 2026-05-10 (本笔记同提交)

> 这不是技术批判 — sherpa-onnx 是 k2-fsa 的高质量项目,在嵌入式 / 移动 / 纯 ONNX runtime 场景仍是首选。
> 这只是记录 VideoCraft 这条具体路径上为什么不合适,以及途中得到的几个一般性教训。

---

## 1. 当初为什么选 sherpa-onnx

VideoCraft 的内嵌 AI 层定位是**零配置 / 零云 key / Windows portable**。技术选型时的核心约束:

- 不能依赖 PyTorch (~2.5 GB, CUDA 版更大,Windows 打包噩梦)
- 必须能 CPU/GPU 双栈,GPU 当作 nice-to-have
- ASR 要支持 Whisper 系 (主流模型生态最广)
- TTS 要本地、零 key、多语言

sherpa-onnx 在每一项都是看起来最匹配的:
- 纯 ONNX Runtime,不带 torch
- 同一份 wheel 切 CPU / +cuda 后缀就支持 GPU
- 官方 export 了 Whisper int8 / fp32 全套 + Kokoro / MeloTTS
- 中文社区成熟

→ 决定: ASR 用 sherpa Whisper,TTS 用 sherpa Kokoro。

---

## 2. 具体踩到的坑

### 2.1 sherpa Whisper 的 RTF 天花板

GPU 优化做了一整轮 (8 个步骤迭代),最终在 RTX 4060 Laptop / Whisper-small 上拿到的是:

| 阶段 | 配置 | RTF |
|---|---|---|
| 初版 | int8 + CUDA EP | 4.7× (大量 op fall back 到 CPU) |
| 切 fp32 | fp32 + CUDA EP | 8.9× |
| float16 模式 | fp16 EP | 10.6× |
| 上 batch_size=8 | 同上 | **10.6× (没动)** |

batch 上去 RTF 不动是核心问题。看了 sherpa 的 C++ `OfflineRecognizer::DecodeStreams`,发现它对 Whisper 的实现是**串行迭代** streams,batch_size 只是 API 形状上的批,内核里没有真的并行。这是架构层面的事,不是参数能改的。

切到 faster-whisper / CTranslate2:

| 阶段 | 配置 | RTF |
|---|---|---|
| 默认 | small + fp16 | **35.8×** |

→ 同样的硬件,同样的模型规模,3.4× 提升。CTranslate2 对 encoder/decoder 都做了真正的 batched kernel。

### 2.2 int8 + CUDA EP 的隐性陷阱

ONNX Runtime CUDA EP 对 int8 op 的覆盖是部分的。我们的 int8 Whisper 在 CUDA 设备上跑,**大部分 op 静默 fall back 到 CPU**,只有少数算子真在 GPU 上。表现就是 GPU 利用率个位数,但日志不会报错,看起来在跑。

这种"看起来在 GPU 但实际半 CPU"的状态非常难诊断,因为 RTF 不是零、温度也升、但就是没有该有的速度。

### 2.3 Kokoro / MeloTTS 的质量上限

- **Kokoro int8 multi-lang v1.0**: 50+ voice,中文播新闻 → 用户实测"完全不可用"。基本属于"能听出是中文,但播不了新闻"的水准。
- **MeloTTS zh_en**: 比 Kokoro 强一档,但仍然"哪能播新闻呢?"。MyShell 的 demo 页面比我们装在本地跑出来的好一些 — 可能是后端有额外处理,sherpa-onnx 的 vits 推理路径丢了一些东西。

最后转到 **edge-tts (Microsoft Read-Aloud)**:同样免 key、零本地模型,YunxiNeural / XiaoxiaoNeural 直接达到广播级。用户验证"已经非常好了,就这个了"。

→ TTS 这条线根本不需要本地模型 — 在线免 key 方案的质量上限远高于当前可获得的本地开源模型。本地 TTS 的价值仅在"完全离线"场景,VideoCraft 不优先支持。

### 2.4 download_all 的 200+ 文件

Kokoro multi-lang 包含 ~375 个文件 (espeak-ng phoneme 表 + jieba 字典 + ONNX 权重)。最初我手填 `filenames=()` 漏了一堆,启动报错。解决方案是加 `download_all=True` + HF tree API + ThreadPoolExecutor 并行下载 — 这个机制本身保留下来了 (catalog.py 仍支持),哪怕现在 catalog 里没有 entry 用它。

### 2.5 CUDA DLL 冲突 (Error 127 / 1114)

sherpa-onnx 的 CUDA wheel 自带 onnxruntime,torch 也带 onnxruntime + cudnn。两个都在进程里时:

- 装了 nvidia-cudnn-cu12 9.22 → torch 自带的 cudnn 9.1 LoadLibrary 失败 → Error 127
- ai_console 检测代码 `import onnxruntime` 单独探测 → 在 sherpa 加载它自己的 ORT 之前先加载,Error 1114 DLL_INIT_FAILED

最后的稳态方案是:**别装 torch**。ctranslate2.converters.transformers 有 `try: import torch`,装了就加载,不装就跳过。requirements.txt 现在显式禁止 torch 进 venv (注释)。

教训: Windows 上多个独立 wheel 都自带 CUDA DLL 时,版本要么完全一致,要么少一个。

---

## 3. 一般性教训

### 3.1 API 名字不能信,得测

`OfflineRecognizer.decode_streams(streams: list)` 的签名暗示 batch,实际 C++ 串行。光看 Python 接口和文档无法判断。教训:**性能相关的特性必须跑 benchmark 验证**,不能假定 API 形状 = 实际并行度。

### 3.2 "看起来在 GPU"不等于"在 GPU"

ONNX Runtime CUDA EP 的 fallback 是静默的。需要用 nvidia-smi 看 GPU 利用率、对比 CPU-only RTF 来判断,不能光看日志里的 `provider=cuda`。

### 3.3 在线免 key 不该被低估

VideoCraft 的"零云 key"原则原意是"用户不需要去注册 key",不是"必须本地运行"。edge-tts 这种**免 key 在线服务**完美满足前者,质量还远高于本地可选项。
后续有相似选型 (例如某些只云端有的能力),应优先考虑"免 key 在线"档,不要默认排除。

### 3.4 不要对硬件上限做悲观假设

我们一开始默认"4060 Laptop + Whisper small ≈ 10× RTF 已经不错了" — 因为这是 sherpa 给的上限。直到换 backbone 才发现 35× 是同样硬件的真实潜力。教训:**当你接近某个 backbone 给的天花板时,优先考虑换 backbone,不是优化参数**。

### 3.5 文件级核查比"问 LLM 帮估算"靠谱

途中犯过两次错: 用估算的文件大小填 catalog,用 LLM 想当然的 filename 填 catalog,都被用户怼回来 ("为啥不拉取列表?为啥要瞎猜?")。最终方案是 HF tree API 实时拉真实文件清单 + lfs.oid 当 sha256。

→ 凡是 repo metadata,**永远查 API,不要查记忆 / 估算 / 猜**。

### 3.6 移除上游依赖前要查整个集成面

sherpa 删除时漏了几处: gpu.py 还在用 `version("sherpa-onnx")` 探测 CUDA,i18n 还有 `tool.router.local_tts_*` 系列 key,catalog.py 还在引用 `target_subdir="sherpa/..."`。教训: 删依赖时 grep 范围要包含 i18n / 注释 / 目录路径,不只是 import。

---

## 4. 当前态 (作为对照)

- ASR: faster-whisper (CTranslate2), 35× RTF on 4060 fp16, built-in silero VAD
- TTS: edge-tts (Microsoft Read-Aloud), 免 key, 在线
- LLM: llama-cpp-python (Qwen3-1.7B Q4_K_M GGUF), 70 tok/s on GPU
- GPU 检测: `core/gpu.py` 现在通过 `nvidia/*/bin` 目录 + `nvidia-smi` 双重检测

catalog 从 8 entries 缩减到 4 (faster-whisper-small / large-v3-turbo + qwen3-1.7b/8b)。

silero VAD 也不需要单独下载了 — faster-whisper bundle 里已经带。

---

## 5. 不是 sherpa 的错

再强调一次,sherpa-onnx 的目标场景是嵌入式 / 移动 / kaldi 兼容 / 纯 ONNX 部署 — 在那些场景它仍是最佳选择之一。
我们的场景是 Windows 桌面 + RTX GPU + 追求 RTF + 复用 HF 生态,这条路上 CTranslate2 / GGUF / edge-tts 各自更专精。
