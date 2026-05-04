# TTS 本地部署技术选型文档

**版本**:2026-05  
**适用范围**:本地部署、开源、可商用  
**目标语言**:中文(优先)+ 英文

---

## 1. 选型约束

| 约束 | 说明 |
|---|---|
| 部署形态 | 本地运行,可在消费级硬件上部署 |
| 协议 | 模型权重必须可用于商业用途,无需付费授权 |
| 语言 | 中文为主,英文为辅,需要支持中英混读 |
| 能力 | 零样本声音克隆(从短参考音频生成目标音色) |
| 硬件覆盖 | 从 CPU 到 24GB+ GPU 的全部消费级硬件档位 |

---

## 2. 候选模型协议审查

TTS 领域协议陷阱比 LLM 多得多,先用协议筛一遍。

### 2.1 协议不通过(直接淘汰)

| 模型 | 协议 | 问题 |
|---|---|---|
| **Fish Audio S2 / S2 Pro** | Fish Audio Research License | 模型权重商用需付费许可证。代码开源,权重商用付费 |
| **Voxtral TTS** (Mistral) | CC BY-NC 4.0 | 非商用许可证 |
| **IndexTTS-2** (Bilibili) | 代码 Apache 2.0 + 权重自定义 | **协议陷阱**:根目录 LICENSE 显示 Apache 2.0,但 DISCLAIMER.md 与 INDEX_MODEL_LICENSE 包含额外条款"商用必须事先获得书面授权",官方 README 也明确"For commercial usage, please contact indexspeech@bilibili.com"。ScanCode 工具为此专门新建了 license tag `LicenseRef-Bilibili-IndexTTS` |
| **XTTS-v2** (Coqui) | Coqui Public Model License (CPML) | 协议本身允许非商用,商用需付费;且 Coqui 公司 2024 年倒闭无更新 |
| **MetaVoice** | (被 ElevenLabs 收购) | 未来不确定 |

**关键警示——"开源权重 + 商用付费"模式**:

近年来兴起一类许可证模式,Fish Audio S2、IndexTTS-2 都属于这类。它们的特征是:

- 代码开源(通常 Apache 2.0 或 MIT)
- 权重可下载、可本地推理
- **但商业部署需要单独付费授权**

光看 GitHub 主页或 README 标题容易踩坑。**审查必须查看 LICENSE、DISCLAIMER、MODEL_LICENSE 这些次级文件**。

### 2.2 协议通过(候选)

| 模型 | 协议 | 参数量 | 克隆 |
|---|---|---|---|
| **Qwen3-TTS** (阿里 Qwen) | Apache 2.0 | 0.6B / 1.7B | ✓ 零样本 |
| **Fun-CosyVoice 3.0** (FunAudioLLM/阿里) | Apache 2.0 | 0.5B | ✓ 零样本 |
| **CosyVoice 2.0** (FunAudioLLM/阿里) | Apache 2.0 | 0.5B | ✓ 零样本 |
| **VoxCPM2** (OpenBMB) | Apache 2.0 | 2B | ✓ 零样本 |
| **FireRedTTS-2** (FireRed Team/小米) | Apache 2.0 | ~2B | ✓ 零样本(注 1) |
| **LongCat-AudioDiT** (Meituan) | MIT | 1B / 3.5B | ✓ 零样本 |
| **Chatterbox Multilingual** (Resemble AI) | MIT | 0.5B | ✓ 零样本 |
| **Higgs Audio V2 / V2.5** (BosonAI) | Apache 2.0 | 3B(V2) / 1B(V2.5) | ✓ 零样本 |
| **GPT-SoVITS v4** | MIT | 中等 | △ 需微调 |
| **Spark-TTS** (SparkAudio) | Apache 2.0 | 0.5B | ✓ 零样本 |
| **OmniVoice** | Apache 2.0 | 小 | ✓ 零样本 |
| **Kokoro** | Apache 2.0 | 82M | ✗ 无克隆 |
| **MeloTTS** | MIT | 小 | ✗ 无克隆 |
| **Piper** | MIT | 几十 MB | ✗ 无克隆 |
| **Dia** (Nari Labs) | Apache 2.0 | 1.6B | ✓ 但仅英语 |

**注 1:FireRedTTS-2 的克隆条款备注**

FireRedTTS-2 整体协议是 Apache 2.0,但 HuggingFace 模型卡上有补充声明:"The project incorporates zero-shot voice cloning functionality; Please note that this capability is intended solely for academic research purposes."

这是一个模糊地带:Apache 2.0 协议本身允许商用,但作者补充声明限制克隆功能为研究用途。法律上 Apache 2.0 不允许通过 README 这类非协议正式文件添加额外限制(协议条款一旦确定就不能单方修改),但实际操作中作者可能在更新版本中调整许可证。商用部署时建议关注协议变化,或仅使用其非克隆能力(如预设声音对话生成)。

---

## 3. 技术架构对比

### 3.1 主流架构路线

当前可商用的 TTS 模型架构主要有四类:

| 架构 | 代表模型 | 特点 |
|---|---|---|
| **LLM-based(自回归)** | Qwen3-TTS、Higgs Audio V2、Spark-TTS、FireRedTTS-2 | 复用文本 LLM 的能力理解文本,生成语音 token |
| **Flow Matching / Diffusion** | CosyVoice 2.0、Fun-CosyVoice 3.0 | 流匹配生成声学特征,质量稳 |
| **Tokenizer-free Diffusion AR** | VoxCPM2 | 跳过离散 tokenizer,直接在连续空间建模 |
| **Waveform Latent Space** | LongCat-AudioDiT | 跳过梅尔频谱中间表示,直接在波形隐空间生成 |
| **传统 GAN/Vocoder** | Piper、Kokoro、MeloTTS | 体积小、速度快,但能力有限(无克隆/控制弱) |

各架构在质量上互有胜负,但 LLM-based 在**长上下文一致性、文本理解、中英混读**上有结构优势,Flow Matching 在**音色稳定性、推理速度**上更平稳,Tokenizer-free 路线声称避免了量化损失,但实测优势因模型而异。

### 3.2 关键能力维度

| 模型 | 中文质量 | 英文质量 | 中英混读 | 长篇稳定 | 情感控制 | 时长控制 |
|---|---|---|---|---|---|---|
| **Qwen3-TTS 1.7B** | 极强 | 强 | **极强** | 强 | 标签 + 风格 | △ |
| **Qwen3-TTS 0.6B** | 强 | 中等偏上 | 强 | 中等 | 标签 + 风格 | △ |
| **Fun-CosyVoice 3.0** | **极强(含 18 方言)** | 中等偏上 | 中等偏上 | **强** | 中等 | △ |
| **CosyVoice 2.0** | 强 | 中等偏上 | 中等 | 强 | 中等 | △ |
| **VoxCPM2** | **极强** | **极强** | 强 | 中等 | Voice Design 强 | △ |
| **FireRedTTS-2** | 强 | 强 | 中等偏上 | **极强(3 分钟稳定)** | 中等 | △ |
| **LongCat-AudioDiT 3.5B** | **极强** | 中等偏上 | 中等 | 强 | 中等 | △ |
| **LongCat-AudioDiT 1B** | 强 | 中等 | 中等 | 中等 | 中等 | △ |
| **Chatterbox ML** | 中等偏上 | 强 | 中等偏下 | 中等 | exaggeration | ✗ |
| **Higgs Audio V2.5** | 强 | **极强** | 中等偏上 | 中等 | 标签 | ✗ |
| **Higgs Audio V2** (3B) | 强 | **极强** | 中等偏上 | 中等 | 标签 + 多说话人 | ✗ |
| **Spark-TTS** | 强 | 中等偏上 | 中等 | 中等 | 强(基于 Qwen2.5) | ✗ |
| **Kokoro / Piper / MeloTTS** | 中等 | 中等 | 弱 | 强 | 弱 | ✗ |

### 3.3 体积与硬件需求

| 模型 | 模型体积 | 推理 VRAM(FP16) | 量化后 VRAM | CPU 可行性 |
|---|---|---|---|---|
| **Piper** | 几十 MB | - | - | ✓ 实时 |
| **Kokoro** | 82M (~330MB) | <1 GB | <1 GB | ✓ 接近实时 |
| **MeloTTS** | <500MB | <1 GB | <1 GB | ✓ |
| **Qwen3-TTS 0.6B** | ~2.5 GB | ~3 GB | ~2 GB | △ 慢 |
| **Chatterbox ML** | ~3 GB | ~4 GB | ~2.5 GB | △ |
| **CosyVoice 2.0 / Fun 3.0** | ~2-3 GB | ~4 GB | ~2.5 GB | △ |
| **Spark-TTS** | ~2 GB | ~4 GB | ~2.5 GB | △ |
| **LongCat-AudioDiT 1B** | ~4 GB | ~6 GB | ~3.5 GB | ✗ |
| **Qwen3-TTS 1.7B** | ~7 GB | ~8 GB | ~5 GB | ✗ 太慢 |
| **VoxCPM2** | ~8 GB | ~10 GB | ~6 GB | ✗ |
| **Higgs Audio V2.5** | ~4 GB | ~6 GB | ~4 GB | ✗ |
| **LongCat-AudioDiT 3.5B** | ~14 GB | ~16 GB | ~9 GB | ✗ |
| **Higgs Audio V2** (3B) | ~12 GB | ~16 GB | ~10 GB | ✗ |
| **FireRedTTS-2** | ~21 GB | ~22 GB | ~12 GB | ✗ 体积最大 |

**硬件覆盖范围**:

- **CPU only**:Piper / Kokoro / MeloTTS(无克隆能力)
- **4-6 GB VRAM**:Qwen3-TTS 0.6B、Chatterbox、CosyVoice、Spark-TTS、LongCat 1B
- **8-12 GB VRAM**:Qwen3-TTS 1.7B、Higgs Audio V2.5、VoxCPM2(量化)
- **16-24 GB VRAM**:LongCat 3.5B、Higgs Audio V2 (3B)、FireRedTTS-2(量化)
- **24 GB+ VRAM**:所有候选都能跑,可同时加载多模型

### 3.4 推理速度(实时倍速 RTF)

RTF (Real-Time Factor) = 处理时间 / 音频时长。RTF=0.1 意味着生成 10 秒音频只需 1 秒处理时间。

| 硬件 | Piper | Qwen3-TTS 1.7B | Chatterbox ML | Fun-CosyVoice 3.0 | VoxCPM2 | FireRedTTS-2 | Higgs V2.5 |
|---|---|---|---|---|---|---|---|
| RTX 5090 | 0.001 | 0.03 | 0.05 | 0.04 | 0.06 | 0.05 | 0.06 |
| RTX 4090 | 0.002 | 0.05 | 0.10 | 0.08 | 0.12 | 0.10 | 0.10 |
| RTX 3060 | 0.01 | 0.15 | 0.30 | 0.25 | 0.40 | 0.35 | 0.35 |
| Apple M3 Pro | 0.02 | 0.25 | 0.50 | 0.40 | 0.60 | 0.50 | 0.55 |
| Apple M2 base | 0.03 | 0.45 | 0.70 | 0.60 | 0.85 | 0.75 | 0.80 |
| CPU(8 核) | 0.1 | 1.5-2 | 2.5-4 | 2-3 | 4-6 | 3-5 | 3-5 |

(数据综合社区实测和官方公布,有 ±20% 浮动)

---

## 4. 中文场景的特殊难点

中文 TTS 比英文难处理的几个特征,直接影响选型:

| 难点 | 例子 | 国际多语言模型典型表现 | 国产模型典型表现 |
|---|---|---|---|
| 多音字 | "重(zhòng)庆" vs "重(chóng)新" | 经常读错 | 训练数据覆盖好 |
| 儿化音 | "好玩儿"、"哪儿" | 经常读不出来 | 训练数据覆盖好 |
| 轻声 | "妈妈"、"东西" | 读出"重音" | 训练数据覆盖好 |
| 变调 | "你好"(三声+三声→二声+三声) | 机械按字典音调 | 自然变调 |
| 中英混读 | "AI 技术"、"GPT 模型" | 经常把英文按拼音读 | 正确切分 |
| 专有名词 | 人名地名、新词 | 长尾覆盖弱 | 长尾覆盖好 |
| 语气词 | "嘞"、"咯"、"嘛"、"呗" | 经常忽略 | 自然处理 |

这些维度上,国产模型(Qwen3-TTS、Fun-CosyVoice、VoxCPM2、LongCat)对欧美训练的多语言模型有结构性优势——**不是因为模型架构更先进,而是因为训练数据中文占比和质量不同**。

---

## 5. 多说话人对话生成能力

这是少数模型才支持的差异化能力,单独展开。

### 5.1 能力定义

**多说话人单次生成**:在单次推理调用里,模型生成包含多个不同说话人交替发声的连续音频片段,每个说话人有独立音色,且整段音频在韵律、停顿、语气衔接上是协调的。

**这不是什么**:

- 不是多人同时出声(那是后期混音层的问题,任何 TTS 都不做)
- 不是简单的"用不同声音生成多段然后拼起来"(那是任何 TTS + ffmpeg 都能做)

### 5.2 与拼接方案的客观差异

| 维度 | 单模型多说话人生成 | 多次单说话人生成 + 拼接 |
|---|---|---|
| 说话人切换处的停顿 | 模型基于上下文决定 | 固定值或人工指定 |
| 切换处的韵律连贯 | 后一句的开头语气受前一句影响 | 各段独立生成,互不感知 |
| 短反应词(嗯、对、是的) | 可生成自然插入 | 需手动剪辑 |
| 抢话、叠话效果 | 部分模型支持 | 拼接无法做 |
| 整段情感弧线 | 模型可统一规划 | 各段独立基调 |
| 跨说话人的上下文一致 | ✓ | ✗(每段独立) |
| 实现复杂度 | 单次调用 | 需自己写拼接逻辑 |
| 时长可控性 | 弱(模型自己决定) | 强(精确到毫秒) |
| 单段质量 | 与单说话人模式相当 | 与单说话人模式相当 |
| 错误恢复 | 整段重生成 | 可单段重生成 |

### 5.3 当前支持的开源候选

| 模型 | 说话人数上限 | 单次生成时长 | 跨语言 | 协议 | 备注 |
|---|---|---|---|---|---|
| **FireRedTTS-2** | 4 人 | 3 分钟 | ✓(A 英文 B 日文) | Apache 2.0(注 1) | 专为多说话人对话设计 |
| **Higgs Audio V2 / V2.5** | 2-4 人(自动分配) | 受 context 限制 | △ | Apache 2.0 | 自动分配声音、自然轮换、跨说话人韵律协调 |
| **Dia** (Nari Labs) | 多说话人 | 受 context 限制 | ✗(仅英语) | Apache 2.0 | 含非语言标签(笑声、叹气) |
| **CosyVoice 2.0 / Fun 3.0** | 多人(通过 `<\|speaker:i\|>` token) | 受 context 限制 | △ | Apache 2.0 | 支持但能力较 Higgs / FireRed 弱 |
| **其他候选** | 不原生支持 | - | - | - | 需自行拼接 |

### 5.4 几点客观事实

- **真正的同时出声任何 TTS 都不支持**——多说话人生成本质上是严格交替的对话流
- **拼接 + ffmpeg amix filter 可做"重叠混音"**——这是任何模型都能配合后期混音实现
- **FireRedTTS-2 是当前对话生成最强的开源候选**——专门为这个场景训练,3 分钟稳定输出
- **Higgs Audio 在英文场景表现更好,FireRedTTS-2 在中英场景平衡**

---

## 6. 关键候选深度分析

### 6.1 Qwen3-TTS

**发布**:2026-01,Qwen 团队(阿里)。

**架构**:LLM-based 自回归 + Qwen3-TTS-Tokenizer-12Hz(16-codebook RVQ codec)。

**变体**:
- **Base**:标准零样本克隆,3 秒参考音频
- **CustomVoice**:9 种预设音色 + 风格指令(性别、年龄、方言、情感)
- **VoiceDesign**:文字描述生成新声音(无需参考音频)

**关键数据**:
- 训练数据 5M+ 小时
- 支持 10 种语言:中、英、日、韩、德、法、俄、葡、西、意
- 流式合成 TTFA 97 ms
- 0.6B 和 1.7B 两个尺寸

**优势**:
- 共享 Qwen 大模型的文本理解能力,中英混读、新词识别明显占优
- 1.7B 版本在长篇稳定性上明显优于 0.5B 级别模型
- VoiceDesign 是同类模型中独特能力

**劣势**:
- 1.7B 体积偏大(~7 GB 下载,8 GB VRAM)
- 0.6B 在长篇内容上偶有漂移
- 时长控制不如 IndexTTS-2 精确
- 多说话人能力一般

### 6.2 Fun-CosyVoice 3.0

**发布**:2025-12,FunAudioLLM 团队(阿里)。

**架构**:LLM 文本前端 + chunk-aware causal flow matching + HiFi-GAN。

**关键数据**:
- 9 种语言:中、英、日、韩、德、西、法、意、俄
- **18 种中文方言**:粤、闽南、川、东北、陕(三秦)、陕(关中)、上海、天津、山东、宁夏、甘肃等
- Pronunciation Inpainting:支持中文拼音和英文 CMU 音素的发音修正
- 流式合成 TTFA 150 ms

**优势**:
- **18 种中文方言覆盖最广**——做地方话内容这是首选
- 流式合成质量稳
- 0.5B 体积友好
- CER(字符错误率)在中文测试集上是开源最低之一

**劣势**:
- 中英混读能力不如 Qwen3-TTS
- 没有 VoiceDesign 这类创造性能力
- 多说话人支持但能力较 Higgs / FireRed 弱

### 6.3 CosyVoice 2.0

**发布**:2024-12,FunAudioLLM 团队(阿里)。

**关键数据**:
- 0.5B 参数
- 双向流式合成,TTFA 150 ms
- 比 1.0 版本发音错误降低 30-50%
- MOS 评分 5.53(可比商用模型 5.52)

**位置**:Fun-CosyVoice 3.0 的前一代,2.0 在生态成熟度上仍占优(社区工具支持更全),但 3.0 在质量上明显进步。新选型应直接上 3.0,2.0 仅在向后兼容场景考虑。

### 6.4 VoxCPM2

**发布**:2026-04,OpenBMB(清华 NLP + ModelBest,MiniCPM 团队)。

**架构**:Tokenizer-free diffusion autoregressive,基于 MiniCPM-4 backbone。

**关键数据**:
- 2B 参数
- 训练数据 2M+ 小时
- 30 种语言:中、英、阿、缅、丹、荷、芬、法、德、希、希伯、印地、印尼、意、日、高棉、韩、老挝、马、挪、波、葡、俄、西、斯瓦希、瑞、菲、泰、土、越
- **9 种中文方言**:四川话、粤语、吴语、东北话、河南话、陕西话、山东话、天津话、闽南话
- **48 kHz 录音棚级输出**(候选中最高音质规格)
- AudioVAE V2 内置超分辨率,16kHz 输入自动升采到 48kHz

**四种生成模式**:
- **Voice Design**:文字描述生成新声音
- **Controllable Cloning**:克隆 + 风格控制
- **Ultimate Cloning**:reference audio + transcript,最高保真
- **Long-form streaming**:长文本流式合成

**优势**:
- **音质最高**(48kHz 是其他候选的 2 倍采样率)
- 30 语言覆盖广
- 中文方言虽然只有 9 种(少于 Fun-CosyVoice 3.0 的 18 种),但加上 30 主语言覆盖,跨语言场景更全
- Tokenizer-free 路线避免了量化损失,理论上音色更自然
- 在 Minimax-MLS 基准上英文 SIM 85.4%(对比 ElevenLabs 61.3%)
- 中文 WER 1.1%(对比 ElevenLabs 16%)

**劣势**:
- 2B 体积偏大,VRAM 需求 ~10 GB
- Voice Design 输出有"运气性"——同一描述多次生成结果差异大,官方建议跑 1-3 次取最佳
- 部分小语种 WER 较高(阿拉伯 13%、捷克 24%)
- 长篇极端表达场景偶有不稳定
- 发布较晚(2026-04),社区工具支持仍在跟进中

### 6.5 FireRedTTS-2

**发布**:2025-09,FireRed Team(小米)。

**架构**:Dual-transformer 架构,12.5Hz 流式 speech tokenizer。

**关键数据**:
- 7 种语言:英、中、日、韩、法、德、俄
- **多说话人对话:最多 4 人,3 分钟**
- 跨语言克隆 + code-switching
- L20 GPU 上首包延迟 140ms
- 模型体积 ~21GB(候选中最大)

**优势**:
- **多说话人对话场景的开源最强候选**
- 长篇稳定性极强(3 分钟连续对话不漂移)
- 跨说话人语境理解(B 接 A 的话能保持上下文连贯)
- 跨语言切换流畅(A 说中文 B 说英文同一段不出问题)
- 流式合成低延迟

**劣势**:
- 体积大,部署门槛高
- 单说话人场景没有对应优势(用 Qwen3-TTS / Fun-CosyVoice 更划算)
- 克隆功能官方备注"academic research purposes",协议存在模糊地带(详见第 2.2 节注 1)

### 6.6 LongCat-AudioDiT (Meituan)

**发布**:2026 初,Meituan(美团)。

**架构**:Waveform Latent Space Diffusion——跳过梅尔频谱中间表示,直接在波形隐空间生成。

**关键数据**:
- MIT 协议(候选中协议最干净档之一)
- 1B 和 3.5B 两个尺寸
- 中英双语
- Seed-ZH 基准:speaker similarity 0.818(此前 SOTA)
- Seed-Hard 基准:0.797(此前 SOTA)

**优势**:
- **MIT 协议比 Apache 2.0 更宽松**
- **波形隐空间架构理论上避免了"text→spec→audio"两阶段误差累积**
- 中文克隆相似度刷新此前 SOTA
- 1B 变体硬件友好

**劣势**:
- 中文优于英文(英文测试不充分)
- 不支持中文方言
- 多说话人能力不强
- 生态较新,社区工具支持有限
- 3.5B 变体硬件需求高

### 6.7 Chatterbox Multilingual (Resemble AI)

**发布**:2025-12 多语言版本。

**架构**:0.5B 参数,基于 Llama 架构改造。

**关键数据**:
- **MIT 协议**
- 23 种语言:阿、丹、德、希、英、西、芬、法、希伯、印地、意、日、韩、马、荷、挪、波、葡、俄、瑞、斯瓦希、土、中
- 跨语言克隆:英语声音可以直接生成法语/德语等
- exaggeration 参数控制情感强度
- **强制嵌入 PerTh 神经水印**

**关键缺陷(中文场景)**:

- 中文虽然支持但不是训练重点
- 中英混读经常出错
- 多音字处理不如阿里系
- 语气词识别弱

**适合场景**:多语言均衡需求,跨语言克隆场景。中文优先场景被国产模型碾压。

### 6.8 Higgs Audio V2 / V2.5 (BosonAI)

**架构**:基于 Llama-3.2-3B + DualFFN audio adapter。

**两个版本**:

| 版本 | 参数 | 主要语言 | 备注 |
|---|---|---|---|
| **V2** (2025-08) | 3.6B LLM + 2.2B DualFFN = 5.8B 总参数 | 多语言 | 训练 10M+ 小时 |
| **V2.5** (2026-01) | 1B(GRPO 蒸馏版) | 主要英、中、韩、日;次要其他 | 速度更快,质量相近 |

**特殊能力**:
- 多说话人对话(2-4 人,自动分配声音)
- 自动韵律适配
- 唱歌 / 哼唱
- 语音 + 背景音乐同时生成
- **EmergentTTS-Eval 上 75.7% 击败 GPT-4o-mini-TTS**(开源里的情感表现力顶级)

**关键缺陷(中文场景)**:

- V2.5 的 GRPO 对齐是英中日韩四种,**欧语和俄语是"泛化",质量无保证**
- 中文虽是主要语言,但训练数据深度仍不及阿里系

**适合场景**:英文为主场景,情感表现力要求高,或多说话人对话(与 FireRedTTS-2 互补)。

### 6.9 Spark-TTS

**架构**:基于 Qwen2.5,纯 LLM 管道,无独立 vocoder。

**关键数据**:
- 0.5B 参数
- 5 秒参考音频克隆
- 情感、音调、速度控制
- 中英双语

**位置**:与 Qwen3-TTS 0.6B 直接竞争。Qwen3-TTS 更新且训练数据更多,但 Spark-TTS 在某些情感控制场景上有独特性。

### 6.10 GPT-SoVITS v4

**协议**:MIT(候选中协议最干净档之一)。

**关键数据**:
- 中英日韩粤五语
- 1 分钟微调样本可达专业级,5 秒零样本
- v4 修复了 v3 的金属音 artifacts
- 原生 48kHz 输出
- v2Pro / v2ProPlus 变体提供 v4 级质量但 v2 级速度

**关键差异**:
- **微调路径**而非纯零样本——需要 1 分钟参考音频做几分钟到几十分钟的训练
- 中文社区使用最广,生态工具丰富
- 推理速度比纯 LLM-based 快(无自回归生成 token)

**劣势**:
- 微调流程复杂,普通用户上手有门槛
- 长篇稳定性弱于 Qwen3-TTS

### 6.11 OmniVoice

**关键数据**:
- 600+ 语言(基于 Qwen3-0.6B 文本编码 + diffusion 语言模型)
- RTF 0.025(40 秒音频/秒计算)
- 支持 voice design

**位置**:语言覆盖最广但优势在小语种。中英场景下没有优势。

### 6.12 无克隆类(Kokoro / Piper / MeloTTS)

**适用场景**:
- 不需要声音克隆
- 极致体积/速度需求(嵌入式、CPU only)
- 占位音频生成

| 模型 | 中文支持 | 英文支持 | 体积 | CPU 性能 |
|---|---|---|---|---|
| **Kokoro** | △(韵律一般) | 强 | 82M | RTF 0.05 |
| **Piper** | ✓(预训练声音) | ✓ | <100MB | RTF 0.01 |
| **MeloTTS** | ✓ | ✓ | <500MB | RTF 0.1 |

---

## 7. 按场景的推荐对比

### 7.1 "性能 / 质量 / 协议"维度对比

| 优先维度 | 首选 | 次选 |
|---|---|---|
| **协议最干净**(MIT) | Chatterbox ML / GPT-SoVITS v4 / **LongCat-AudioDiT** | (Apache 2.0 选项次之) |
| **中文质量最强** | Qwen3-TTS 1.7B / Fun-CosyVoice 3.0 / VoxCPM2 / LongCat 3.5B | CosyVoice 2.0 |
| **中英混读最强** | **Qwen3-TTS 1.7B** | VoxCPM2、Higgs Audio V2.5 |
| **英文质量最强** | Higgs Audio V2 (3B) / VoxCPM2 | Higgs Audio V2.5 |
| **音质最高** | **VoxCPM2 (48kHz)** / GPT-SoVITS v4 (48kHz) | 其他多为 24kHz |
| **方言覆盖最广** | **Fun-CosyVoice 3.0(18 方言)** | VoxCPM2(9 方言) |
| **多说话人对话** | **FireRedTTS-2(4 人 3 分钟)** | Higgs Audio V2.5 / Dia(英语) |
| **轻量(<4 GB VRAM)** | Qwen3-TTS 0.6B / Chatterbox / CosyVoice 2.0 | Spark-TTS |
| **CPU only** | Piper / Kokoro | MeloTTS |
| **时长精确控制** | (商用候选无强项) | 需用云端 |

### 7.2 各档硬件下的最优单一选择

| 硬件 | 中文优先最优 | 英文优先最优 | 备注 |
|---|---|---|---|
| CPU only | Piper(无克隆) | Piper / Kokoro | 克隆能力需要 GPU |
| 4-6 GB VRAM | **Qwen3-TTS 0.6B** 或 Fun-CosyVoice 3.0 | Chatterbox ML | 都支持零样本克隆 |
| 8-12 GB VRAM | **Qwen3-TTS 1.7B** 或 VoxCPM2 | Higgs Audio V2.5 / VoxCPM2 | 1.7B 量化后 ~5GB |
| 16-24 GB VRAM | LongCat 3.5B 或 VoxCPM2 完整版 | Higgs Audio V2 (3B) | 单模型质量天花板 |
| 24 GB+ VRAM | 多模型共存(如 Qwen3-TTS + Fun-CosyVoice) | 多模型共存 | 任务级别切换 |

---

## 8. 模型对比矩阵(完整版)

| 维度 | Qwen3-TTS 1.7B | Qwen3-TTS 0.6B | Fun-CosyVoice 3.0 | CosyVoice 2.0 | VoxCPM2 | FireRedTTS-2 | LongCat 3.5B | Chatterbox ML | Higgs V2.5 | Higgs V2 (3B) | Spark-TTS | GPT-SoVITS v4 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 协议 | Apache | Apache | Apache | Apache | Apache | Apache(注) | **MIT** | **MIT** | Apache | Apache | Apache | **MIT** |
| 参数 | 1.7B | 0.6B | 0.5B | 0.5B | 2B | ~2B | 3.5B | 0.5B | 1B | 5.8B | 0.5B | 中等 |
| VRAM(FP16) | 8GB | 3GB | 4GB | 4GB | 10GB | 22GB | 16GB | 4GB | 6GB | 16GB | 4GB | ~3GB |
| 发布时间 | 2026-01 | 2026-01 | 2025-12 | 2024-12 | 2026-04 | 2025-09 | 2026 | 2025-12 | 2026-01 | 2025-08 | 2025 | 2025 |
| 音质 | 24kHz | 24kHz | 24kHz | 24kHz | **48kHz** | 24kHz | 24kHz | 24kHz | 24kHz | 24kHz | 24kHz | **48kHz** |
| 中文质量 | 极强 | 强 | 极强 | 强 | 极强 | 强 | 极强 | 中上 | 强 | 强 | 强 | 强 |
| 中文方言 | △ | △ | **18 种** | △ | **9 种** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | △(粤) |
| 英文质量 | 强 | 中上 | 中上 | 中上 | **极强** | 强 | 中上 | 强 | **极强** | **极强** | 中上 | 中等 |
| 中英混读 | **极强** | 强 | 中上 | 中等 | 强 | 中上 | 中等 | 中下 | 中上 | 中上 | 中等 | 中等 |
| 长篇稳定 | 强 | 中等 | 强 | 强 | 中等 | **极强** | 强 | 中等 | 中等 | 中等 | 中等 | 中等 |
| 克隆方式 | 3 秒 | 3 秒 | 零样本 | 零样本 | 零样本+多模式 | 零样本 | 零样本 | 3-10 秒 | 零样本 | 零样本 | 5 秒 | 微调或零样本 |
| 跨语言克隆 | △ | △ | △ | △ | ✓ | **强** | △ | **强** | △ | △ | △ | △ |
| 多说话人 | △ | △ | △ | △ | △ | **极强(4 人 3 分钟)** | △ | △ | **强** | **强** | △ | △ |
| 情感控制 | 标签+风格 | 标签+风格 | 中等 | 中等 | **Voice Design** | 中等 | 中等 | exaggeration | 标签 | 标签 | **强** | 中等 |
| 流式 TTFA | 97ms | 97ms | 150ms | 150ms | 流式支持 | **140ms** | - | - | - | - | - | - |
| 水印 | 无 | 无 | 无 | 无 | 无 | 无 | 无 | **强制 PerTh** | 无 | 无 | 无 | 无 |
| 维护活跃度 | 高 | 高 | 中 | 中 | 高(新) | 中 | 高(新) | 高 | 高 | 中 | 中 | **极高(社区)** |

---

## 9. 协议风险评估

虽然候选模型协议都通过了"可商用"筛选,但风险等级仍有差异:

| 协议 | 风险等级 | 关键风险点 |
|---|---|---|
| **MIT** | 最低 | 几乎无限制,可商用、可修改、可闭源衍生 |
| **Apache 2.0** | 低 | 与 MIT 相似,额外要求保留版权声明,有专利授权条款 |
| **Apache 2.0 + 作者补充声明** | 低-中 | 协议本身允许商用,但作者声明对特定能力(如克隆)限制研究用途。法律灰色地带 |

**协议外的隐性风险**:

1. **训练数据合规性**:即使模型协议是 MIT,训练数据可能含未授权语音,对克隆模型尤其敏感
2. **声音版权**:协议管模型不管输出。用模型克隆名人声音商用,即使模型协议干净也违法
3. **国家/地区限制**:部分地区对 AI 语音合成有合规要求(如欧盟 AI Act 要求 AI 生成内容标识)
4. **协议演进**:Qwen 系列从 3.5 Omni 起有部分变体闭源化趋势,Apache 2.0 是当前状态,未来不保证
5. **水印强制性**:Chatterbox 强制嵌入 PerTh 水印,虽然听感无影响但可被识别为 AI 生成
6. **自定义补充条款**:FireRedTTS-2 这类"Apache 2.0 + 作者声明限制"的混合状态,在 Fish Audio S2、IndexTTS-2 之后出现的新陷阱形态

---

## 10. 实际选型建议

按"目标语言:中文优先 + 英文,商用,本地部署"约束:

### 默认推荐:Qwen3-TTS 1.7B

理由:
- Apache 2.0 协议干净
- 中英混读能力是同等条件下最强(继承 Qwen 大模型的文本理解)
- 1.7B 在长篇稳定性上明显优于 0.5B 级别
- 包含三个变体(Base / CustomVoice / VoiceDesign),覆盖不同使用模式
- 8GB VRAM 即可运行,量化后可降到 5GB

### 不同场景的最优选择

| 场景 | 推荐 | 备注 |
|---|---|---|
| 通用中英主播旁白 | **Qwen3-TTS 1.7B** | 默认 |
| 需要最高音质(48kHz) | **VoxCPM2** | 录音棚级 |
| 需要 Voice Design(无录音) | Qwen3-TTS / VoxCPM2 | 两者都支持 |
| 中文方言内容 | **Fun-CosyVoice 3.0** | 18 方言最广 |
| 多说话人对话 | **FireRedTTS-2** | 4 人 3 分钟最强 |
| 多人英文对话 | Higgs Audio V2.5 | 英文情感表现强 |
| 协议要求最严格(MIT) | **LongCat-AudioDiT** / Chatterbox ML / GPT-SoVITS v4 | LongCat 中文最强 |
| 8GB 以下硬件 | Qwen3-TTS 0.6B / Fun-CosyVoice 3.0 | 0.5B 级别中文最强档 |
| CPU only | Piper(中文预训练声音) | 无克隆,质量妥协 |

### 完全不要选

- **Fish Audio S2 / S2 Pro**:权重商用付费
- **IndexTTS-2**:协议陷阱,商用需书面授权
- **Voxtral TTS**:CC BY-NC 不可商用
- **XTTS-v2**:无维护
- **MetaVoice**:被 ElevenLabs 收购,未来不确定

### 需要警惕

- **FireRedTTS-2**:Apache 2.0 但克隆功能有作者补充声明限研究用途。商用部署前关注协议最新状态,或仅使用其非克隆能力

---

## 11. 验证方法建议

实际部署前的最小验证集:

1. **中文克隆质量**:30 秒男声 + 30 秒女声参考,各生成 2 分钟,人工评分音色相似度 1-5,目标 ≥ 4.0
2. **中英混读测试**:20 段含英文术语的中文文本(如"OpenAI 的 GPT-5 击败了 Claude 4"),英文部分发音正确率 ≥ 90%
3. **多音字测试**:含 30 个常见多音字段落,选音正确率 ≥ 95%
4. **长篇稳定性**:连续生成 10 分钟内容,后段不出现音色漂移
5. **吞吐压测**:1 万字符脚本批量,记录中位数耗时和峰值 VRAM
6. **语气词处理**:含"嘞、嘛、呗、咯"的口语化文本,自然处理率
7. **专有名词**:含 20 个新词/人名/地名的文本,正确读音率
8. **多说话人测试**(若该能力是需求):2-4 人对话脚本,评估说话人切换自然度、跨语境一致性
9. **音质客观评估**:24kHz vs 48kHz 输出在频谱图、SNR 上的差异(对最终用途敏感时考虑)
