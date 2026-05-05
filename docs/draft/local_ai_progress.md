# 本地 AI 闭环 · 阶段进度

**目标**:把 VideoCraft 推广的最大阻碍 —— 必须配云端 API key 才能跑通最小闭环 —— 干掉。

**总览**:

| Phase | 范围 | 推理引擎 | 状态 | Commit |
|---|---|---|---|---|
| **L1** | LLM (翻译/字幕处理/切片排序) | Ollama (MIT) + Qwen3:4b | ✅ 已上线 2026-05-05 | `8823915` |
| **L2.1** | ASR 通用档 | faster-whisper (MIT) + Whisper small | ✅ 已上线 2026-05-05 | `c1e72f4` |
| **L1.5** | UX 收尾 | — | ✅ 已上线 2026-05-05 | `85db20f` |
| **L2.2 上半场** | ASR 欧语高质量档 | NVIDIA NeMo Parakeet TDT 0.6B v3 (CC-BY-4.0) | ✅ 已上线 2026-05-05 | `b1c1d7d` `4aa9f24` |
| **L2.2 下半场** | ASR 中日韩档 | Alibaba FunASR + SenseVoiceSmall (MIT) | ✅ 已上线 2026-05-05 | `bc3cd34` `8bae520` `2d3860c` |
| **基础设施** | 模型缓存重定向 / 语言路由 | `core/paths.py` + `router.asr().language_routing` | ✅ 随 L2.2 上线 | `b1c1d7d` |
| **L3 探索** | TTS (文本转语音) | Qwen3-TTS-12Hz-0.6B-CustomVoice + vLLM-Omni Docker | 🔬 推理引擎选定 + RTF 0.78 实测;Tier 2/3 综合测试待做 | `46cfa48` |
| **L4** | 首启自动化 / 一键安装 | — | ⏳ Backlog | — |

---

## L1 — Ollama LLM(已上线)

- **协议链路**:Ollama 自身 MIT,默认拉的 Qwen3:4b Apache 2.0 → 法律链路全干净
- **架构复用**:复用现有 `openai_compatible` provider type(Ollama 暴露 OpenAI 兼容协议在 `localhost:11434/v1`),不新建 provider adapter
- **关键扩展点**:provider config 新增 `auth_required: False` 字段。`config.has_auth()` 短路返回 True,`router._call/_call_json` 用占位 api_key `"ollama"` 调用 OpenAI SDK(本地服务忽略 Bearer 内容)
- **UX**:AI Console Edit 对话框检测 `is_local`,隐藏 API Key 行,加 Health Check 按钮 + Pick Models(走 `/v1/models`)
- **关键文件**:`src/core/ai/{config,router}.py`、`src/tools/router/ai_console.py`

## L2.1 — faster-whisper ASR(已上线)

- **协议链路**:MIT(faster-whisper)+ MIT(Whisper 模型)→ 干净
- **架构复用**:`router.asr()` 加 `elif provider == "faster_whisper"` 分支,跳过 key/base_url 校验。输出 normalize 到 LemonFox 的 `verbose_json` shape (`language/duration/text/segments[]/words[]`),下游零改动
- **关键决策**:`device="auto"` 默认 CPU。CUDA 路径要用户自己装 CUDA 12 Toolkit + cuDNN(否则推理时报 `cublas64_12.dll not found`)。这是 ctranslate2 wheel 的现实问题,不绕
- **enabled 语义对齐**:LLM `_complete_explicit` 不检查 `enabled`,但 ASR/TTS 严格要求 `enabled=True`,造成首次设置后报"provider disabled"。改成 ASR/TTS 也不检查 enabled(显式 task_routing 即视为启用)
- **关键文件**:`src/core/ai/providers/faster_whisper_local.py`(新)、`src/core/{asr,ai/__init__,ai/router}.py`、`src/tools/router/ai_console.py`、`requirements.txt`

**性能基线**:200 秒英文 mp3 / CPU 8 核 / Whisper small → 90 秒(RTF 0.45)。

---

## L2.2 上半场 — Parakeet TDT v3(已上线)

**协议**:CC-BY-4.0,商用允许。

**性能**:200 秒英文 / CPU 8 核 → **13 秒**(RTF 0.065),比 faster-whisper-small 快约 7×。

**实战质量(川普答记者问 3 分钟,与 LemonFox 和 faster-whisper-small 对比)**:
- 段落切分自然(72 段 vs faster-whisper 100 段碎切)
- 专有名词:naval blockade ✅(faster-whisper 错为 "naval Black Cave")、leader's gone ✅(faster-whisper 错为 "leader is God")
- 唯一对地名 Doral 略走音(Durell vs LemonFox 的 Dural)
- **结论**:英语新闻档明显胜出 faster-whisper-small,跟 LemonFox 接近

**关键架构决策**:
- 路由层加 `language_routing[iso] → provider` 映射(例 `en→parakeet`),`router.asr()` 拿到 language hint 时优先查这条
- master enable switch:`task_routing[*].language_routing_enabled=False` 默认。**避免**用户切回默认 provider 后旧路由偷偷劫持的反直觉。改 default 不影响 language overrides 的"被动存在",但需要显式勾 Enable 才生效
- AI Console "🌐 Lang (n)" 按钮按需添加,不强制每语言占行

**Windows 安装坑(已 pin)**:
- `pip install nemo_toolkit[asr]` 默认拉 `pyarrow 24` + `pandas 3.0` + `datasets 4.x`,Windows 上 pyarrow 24 C 扩展直接 access violation(faulthandler 抓到栈)
- `requirements.txt` 已 pin `pyarrow==19.0.1 / pandas==2.3.3 / datasets==3.6.0`
- **升级 NeMo 时必须重新验证这三个 pin**

---

## L2.2 下半场 — SenseVoice(已上线)

**协议**:模型 MIT、SDK Apache 2.0,商用允许。

**性能**:113 秒中文新闻 / CPU 8 核 → **4 秒**(RTF 0.035 ≈ 28× 实时),最快的本地 ASR。

**实战质量(英王查尔斯三世访美 80 秒,与 LemonFox 和 faster-whisper-small 对比)**:
- 准确率与 LemonFox 接近,**唯一一家正确识别"均表示"**(其他都错为"军/君")
- 标点规范、中英混合数字 ITN 处理好(250 周年 / 4月27日)
- 仅 Small 一个尺寸公开。Large 论文有提但阿里未开源(留作商用)

**关键架构决策(踩坑大头)**:

1. **不能用 FunASR 的一站式 AutoModel(model=SV, vad_model=fsmn-vad, ...)** —— 它把所有 VAD chunks 合并成单个 result,timestamp 字段丢失。结果是整段文本挤成一行 `00:00:00,000 → 00:00:00,000` 的废 SRT
2. **必须 VAD + SV 分开两个 AutoModel 实例**:手动跑 VAD 拿 `[start_ms, end_ms]`,再 slice audio 喂给 SV,timestamp 才能完整保留
3. **必须传 `output_timestamp=True`**:这是 FunASR 文档没怎么提的隐藏路径(在 `funasr/models/sense_voice/model.py:861` 的 inference body 里),走内部 `ctc_forced_align` 拿字级 [start, end]
4. **噪段过滤用模型自身信号,不用文字长度**:SV 每段输出 `<|zh|><|NEUTRAL|><|Speech|><|withitn|>` 等元 token。`<|nospeech|>` / 语言标签失配 / 事件标签 (`<|BGM|>` `<|Laughter|>`) 都是模型自己说"这段不是语音内容"的信号,据此 drop。比"丢掉短文本"靠谱多了
5. **VAD 自然 chunk 12-15s 太长做不了字幕**:用 SV 字级 timestamp + 标点(strong: 。!? / soft: ,,;)做**回溯切分** —— 当 buffer 超过 7s soft cap 时,**回头**在最新的 soft punct 处切(避免"早出现的逗号已错过"的失败模式)。详见 `_split_chunk_by_punctuation`,_MAX_SEGMENT_SECONDS=7 / _HARD_SPLIT_SECONDS=12

**Windows 安装坑(已 pin)**:
- `pip install funasr` **不会**拉 `torchaudio`,但 `funasr/utils/load_utils.py` 第一行就 import 它
- `requirements.txt` pin `funasr==1.3.1 + torchaudio==2.11.0`

---

## 基础设施 — 模型缓存重定向(随 L2.2 上线)

**问题**:NeMo / FunASR / Whisper / Transformers 各自默认下载到 `~/.cache/huggingface/`、`~/.cache/torch/`、`~/.cache/modelscope/`,**全堆 C 盘**。Portable 哲学被打破。

**修复**:`core/paths.py` 启动时(`VideoCraftHub.py` 顶部、所有 ML 库 import 之前)统一设环境变量:

```python
HF_HOME / HF_HUB_CACHE / TORCH_HOME / NEMO_CACHE_DIR / MODELSCOPE_CACHE
    → <repo>/user_data/models/{hf,torch,nemo,modelscope}/
```

`providers.json` 加 `models_dir` 顶层字段,允许用户改成共享池(如 `D:\AI_Models`),AI Console 暴露文本框 + 浏览按钮。

**Ollama 例外**:Ollama 自己管模型(`OLLAMA_MODELS` env var,需 OS 级设置),VideoCraft 不接管,只在 AI Console 提供"打开 Windows 系统环境变量"的引导按钮。

---

## 任务粒度差异 — 为什么 ASR/TTS 容易本地化,翻译/精修难

L2.2 跑通后做了 Ollama qwen3:4b vs ClaudeCode sonnet 的翻译质量对比,得到一个清晰规律:

> **任务越窄,越容易本地化;越靠通用智力,越难本地化。**

| 任务 | 性质 | 本地小模型胜率 |
|---|---|---|
| ASR | 窄任务,语音→文本同语种 | ✅ 高(SenseVoice 234M / Parakeet 600M 已能打 LemonFox) |
| TTS | 窄任务,文本→语音 | ✅ 高(开源 GPT-SoVITS / F5-TTS) |
| OCR | 窄任务 | ✅ 高 |
| **翻译** | 双语功底 + 世界知识 + 修辞理解 | ⚠️ 中(4B 跑通但翻译腔重) |
| 字幕精修 / 切片排序 / 文案改写 | 语境推理 + 风格判断 | ❌ 低(小模型经常跑偏) |
| 复杂 reasoning(数学/代码) | 通用智力 | ❌ 低(4B 几乎不能用) |

**翻译质量实测对比**(川普答记者问前 5 段,Parakeet en.srt 作源):

| EN | Ollama qwen3:4b | ClaudeCode sonnet | 评 |
|---|---|---|---|
| Doing very well with regard to ... **but** ... regard to Iran | 在几乎所有方面都表现优异,**但伊朗方面同样表现突出** ❌ | 在几乎所有方面都进展顺利,**尤其是在伊朗问题上**进展顺利 ✅ | C 对,O 错义("but" 对比关系翻丢了) |
| Again, they want to make a deal | **再次,他们又想**达成协议 | **再说一遍**,他们想要达成协议 | C 自然,O 翻译腔 |
| They're decimated | 他们已**几近覆灭** | 他们已经**元气大伤** | 都对,C 更地道 |

**速度**(同 25 段批):
- Ollama qwen3:4b 本地 CPU:~14s/段(且 25 条一批失败,需拆 batch)
- ClaudeCode sonnet via API:~0.5s/段,稳

**为什么翻译跌了一档**:翻译同时考验
- 两门语言的**语感**(4B 中文流畅但翻译腔)
- **世界知识**(Doral 是高尔夫球场这种,4B 不知道但 Claude 知道)
- **修辞捕捉**(微妙的对比/反讽,越微妙越差)

这些都吃**参数规模**,4B 在这维度跟旗舰差一个量级。

**给重度用户的本地升档路径**:
| 路径 | 大概要求 | 翻译质量估 |
|---|---|---|
| Qwen3-4B(当前默认) | CPU 也能跑 | 翻译腔,70 分 |
| Qwen3-8B / Llama3-8B | 16GB 内存 + 显卡更好 | 80 分 |
| Qwen3-32B / Qwen3-72B | 24GB+ 显存 | 接近 Claude Haiku,85~90 分 |
| Claude Sonnet via API | 按量付费 | 95 分 |

VideoCraft 当前 Portable + 单 CPU 友好定位,所以 4B 是合理默认。**给重度用户暴露"换大模型"的 UX 路径**(AI Console "Pick Models" 已支持)是后续可考虑的工作,不阻断核心闭环。

---

## L3 — TTS 本地化(探索阶段:推理引擎选定,综合测试待做)

**协议**:Qwen3-TTS Apache 2.0,商用允许;vLLM-Omni Apache 2.0,商用允许。

**模型选择回顾**:此前 `tts_local_selection_v4.md` 推荐 Qwen3-TTS 1.7B + Piper 兜底。本轮探索从 0.6B-CustomVoice 起步(显存压力小、含零样本声音克隆能力)。1.7B 与 Piper 留作后续 T3.4 / T3.5 验证。

**性能(2026-05-05 ~ 05-06 实测,4060 Laptop 8GB,Chinese 长文本约 23s 音频)**:

| 推理栈 / 配置 | RTF(稳态) | 含义 |
|---|---|---|
| qwen-tts pip 包(参考实现)+ sdpa | 2.08 - 2.22 | 比实时慢 2x |
| qwen-tts pip 包 + flash_attention_2 | 2.42 - 2.45 | flash-attn 反而拖累 TTS |
| qwen-tts pip 包 + 整体 torch.compile | 2.41 - 2.53 | 变长 TTS 用 reduce-overhead 回退 |
| **vllm-omni:v0.18.0** / mem_util=0.45 / 桌面 ~5GB 占用 | 0.72 - 0.86 | 切换推理栈即拿 3x 提升 |
| **vllm-omni:v0.18.0** / mem_util=0.85 / 桌面 GPU app 关 | **0.64 - 0.70** | 关应用 + 调 util 再拿 ~13%(vRAM 剩 20MB,极限) |
| **vllm-omni:v0.18.0** / mem_util=0.80 / 桌面 GPU app 关(**生产配置**) | 0.71 - 0.86 | 留 95MB 余量稳定运行 |
| 论文 Qwen3-TTS-12Hz-0.6B 单并发 | 0.288 | 未披露 GPU,推测 H100 / A100 |

---

### 关键决策(踩坑大头)

#### 1. **不要用官方 `qwen-tts` pip 包做生产推理 —— 它是参考实现,无任何论文优化**

最大教训。pip 包的 `Qwen3TTSModel.generate_custom_voice()` 只是 `transformers.AutoModelForCausalLM` 的薄封装,**论文里写的 vLLM 引擎 / torch.compile / CUDA Graph / triton SnakeBeta kernel 一个都没有**。

走这条路时实测 RTF 2.2,我们花了几小时折腾 flash-attn 编译、torch.compile、各种 attention 后端,**完全是错的方向**。

判断依据:HF 讨论区 #18 上有用户 1.7B 跑出 RTF 3x、GPU util 12%,跟我们症状一模一样;论文 Table 2 footnote 明说 "latency is measured on our internal vLLM engine (vLLM V0 backend) ... with optimizations applied via torch.compile and CUDA Graph acceleration to the decoding stage of the tokenizer"。

#### 2. **真正的路是 `vllm/vllm-omni` 官方 Docker 镜像**

vLLM 团队为多模态模型(TTS / ASR / 图像)单独维护的 fork(同 vLLM 主线版本号)。Qwen 团队 day-0 支持已合并(PR #895 + #968),**论文的全部优化栈在镜像里默认开启**:
- vLLM PagedAttention + 连续批处理
- CodePredictor torch.compile
- Code2Wav triton SnakeBeta kernel + CUDA Graph
- async_scheduling 默认开

接口:OpenAI 兼容 `/v1/audio/speech`,扩展字段 `task_type` / `voice` / `language` / `instructions` / `ref_audio` / `ref_text` / `max_new_tokens`。另有 `/stream` `/batch` `/voices` 三组扩展端点。

#### 3. **TTS 用 flash-attn 反而慢**

反直觉但真实(实测 sdpa 2.1 vs flash-attn 2.4)。原因:TTS token 序列短(几十个),flash-attn kernel launch 开销 > 计算节省。flash-attn 是为 LLM 长上下文设计的,TTS 这种短输入逐帧解码不在其优势区。

vLLM-Omni 内部会针对 attention 后端做更细的选择(对 LM 段用 paged attention,对 codec decoder 用 triton kernel),这种适配单靠 attn_implementation 切换做不到。

#### 4. **整体 torch.compile 对 TTS 推理没用**

变长输入输出(每段文本长度不同、每次合成音频长度不同)让 `mode=reduce-overhead` 频繁 recompile,抵消优化。论文做法是**只编译 tokenizer 解码段(8 token → 320ms 音频,形状静态)** + **CUDA Graph 复用**,不是包整个模型。

#### 5a. **桌面 GPU 应用基线占用显著影响 vLLM 可用显存**

8GB 4060 Laptop 上,Chrome / Edge WebView2(WhatsApp/Notion/Claude 桌面等内嵌)/ NVIDIA Overlay / Explorer 多实例 idle 就吃 5GB+ VRAM。关掉这些后桌面基线降到 ~440MiB,空闲 7.5GB 几乎全归 vLLM。

实测影响:同 0.6B 模型,关应用 + `gpu_memory_utilization` 0.45→0.85,RTF 从 0.78 → 0.68(13% 提升)。**生产部署该把"关 GPU 占用大的应用"写进 runbook**。

#### 5b. **1.7B Qwen3-TTS 在 8GB 4060 Laptop 上 vLLM-Omni 跑不动**

实测(2026-05-06 凌晨):

- 模型加载 3.6 GiB
- vLLM-Omni 多阶段管线(LM + code_predictor + token2wav + speaker_encoder)开销吃完剩余 ~3.7 GiB
- **KV cache = 0.0 GiB,引擎初始化失败**
- 试了 `gpu_memory_utilization` 0.85 / 0.90 / 0.92,加 `--enforce-eager` + `--max-model-len 1024` 全都救不回来

vLLM-Omni 是为云推理设计的多 worker 架构,单卡 8GB 没给它足够喘息。结论:

- 想本地跑 1.7B → 需要 **12GB+ 显存**(4070 Ti / 4080 起步)
- 或者走 **GGUF + llama.cpp** 量化路线(`HaujetZhao/Qwen3-TTS-GGUF` 社区项目宣称 RTX 5050 上 1.7B 跑出 RTF 0.35,4060L 估 0.45-0.6),作为后续 T3.4 备选

#### 5c. **`restart: unless-stopped` 会销毁 crash 日志**

容器 OOM/CUDA error/初始化失败后,docker-compose 默认行为是 30s 内自动重启,新实例覆盖旧容器,**前一次的 logs 全丢**。诊断初始化期间的崩溃必须临时改 `restart: "no"`,确认问题后再改回。

#### 6. **GPU util 不是 TTS 性能瓶颈的可靠指标**

nvidia-smi 跑合成时报 32-40% util,以为 GPU 没用满,误以为有调度优化空间。实际上 Windows Task Manager 看 3D engine 已 90%+ —— **WSL2 + CUDA 在 Windows 上经常被归到 3D engine 而非 Compute**,nvidia-smi 的"总 util"对短脉冲负载抓不准。

教训:TTS 这种 autoregressive 短脉冲负载,**用宿主机 Task Manager 验证**比 nvidia-smi 准。

---

### 工程设置(Windows + Docker Desktop + WSL2)

**前置安装链**:
1. Docker Desktop for Windows(带 WSL2 后端)
2. **WSL2 内核** —— Win11 26200 inbox `wsl.exe` 的存根版本太老,`wsl --install` / `wsl --update` 会循环报"未安装",需要管理员 PowerShell 跑 `wsl --install`(会装 Ubuntu 发行版,后续 Docker 集成里关掉避免 Permission denied)
3. **重启**(WSL2 内核生效) —— 这一步会**断 Claude Code session**,重启前必须把上下文记进 memory

**关键运维**:
- **Docker 默认存 C 盘** —— Docker Desktop 的 VHDX 在 `C:\Users\<user>\AppData\Local\Docker\wsl\`,几个 build 后吃掉 60GB+ 不还。**必须迁到 D 盘** —— Docker Desktop → Settings → Resources → Advanced → Disk image location 改 `D:\Docker`,一次性自动迁移
- **`docker image prune -a` 不可逆** —— 没回收站,任何 untagged 或没运行容器引用的镜像直接干掉。常用 `docker image prune`(不带 -a)只清 dangling 安全

**模型缓存**:复用 L2.2 已建好的 `D:\AI_Models\hf` 共享池(HF 标准 cache 布局),容器挂 `/root/.cache/huggingface`,不重复下载。

**docker-compose 关键参数(生产配置)**:
```yaml
ipc: host                          # vLLM 需要 SHMEM > 64MB,默认会警告
ports: "7860:8091"                 # 外部 7860 保留(VideoCraft 兼容),内部 vllm 默认 8091
gpu_memory_utilization: 0.80       # 4060 Laptop 8GB,生产推荐 0.80(95MB 余量,稳)
max_model_len: 4096                # TTS 不需要长上下文
```

**调优过程**:0.45(初始保守值)→ 0.85(关桌面 GPU 应用后,极限值,余 20MB)→ 0.80(生产折中,余 95MB)。0.85 速度最快但显存边界,0.80 留余量推荐用于实际部署。

镜像:`vllm/vllm-omni:v0.18.0`(`:latest` 标签不存在,Docker Hub 只有打 tag 的)。

---

### 待做的综合测试(下一阶段)

当前 RTF 0.78 只是"单点能跑通"。生产化前必须扫:

**Tier 1 决定能不能用**:
- T1.1 并发 1/2/4 RTF + 总吞吐
- T1.2 流式 `/v1/audio/speech/stream` TTFP(论文 97ms 在 4060 上达多少)
- T1.3 多语种 zh / en / ja / ko 质量与速度
- T1.4 长文本 500 / 2000 字 RTF 曲线
- T1.5 VRAM 上限扫(`gpu_memory_utilization` 与 `max_model_len`)

**Tier 2 杀手特性(决定是否替代云 TTS)**:
- T2.1 9 个预设 voice 听感对比
- T2.2 Voice Clone(参考音频零样本克隆) —— 云 API 没这能力
- T2.3 Voice Design(自然语言风格指令)
- T2.4 emotion / instructions(节目情感色彩控制)

**Tier 3 运维稳健 + 模型升档**:
- T3.1 失败用例(空输入 / 超长 / 特殊字符 / 混合语种)
- T3.2 容器重启后注册 voice 是否持久
- T3.3 持续负载 30 次循环 RTF 稳定性
- T3.4 1.7B 试装(4060 8GB 装得下吗、质量与速度差)
- T3.5 Piper 兜底比对(纯 CPU 退路)

测试报告固化为独立 markdown(待写)。所有产物落 `scratch/tts_qwen3/`(已加 `.gitignore`)。

### 与 VideoCraft 集成路径(待落地)

VideoCraft 现有 `lemonfox` provider 走 OpenAI `/v1/audio/speech`,**理论上改 base URL 就能切到 `http://localhost:7860`**。但要用 Qwen3-TTS 的扩展能力(voice clone / design / instructions),需要给 provider 加扩展字段透传。具体接法等 Tier 1 测完决定。

## L4 — 首启自动化(Backlog)

GPU 检测、一键安装 Ollama、自动 pull 模型、首启 onboarding 弹窗。当前用户已经能配通,这个等用户反馈再决定优先级。

## L4 — 首启自动化(Backlog)

GPU 检测、一键安装 Ollama、自动 pull 模型、首启 onboarding 弹窗。当前用户已经能配通,这个等用户反馈再决定优先级。
