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
| **L3** | TTS (文本转语音) | 待定 (Qwen3-TTS / Piper) | ⏳ 用户主动暂缓 | — |
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

## L3 — TTS 本地化(暂缓)

用户主动暂缓:"TTS 不着急,先放着"。后续选型见 `tts_local_selection_v4.md`,推荐档 Qwen3-TTS 1.7B + Piper 兜底。

## L4 — 首启自动化(Backlog)

GPU 检测、一键安装 Ollama、自动 pull 模型、首启 onboarding 弹窗。当前用户已经能配通,这个等用户反馈再决定优先级。
