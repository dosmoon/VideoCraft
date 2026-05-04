# ASR 本地部署技术选型文档

**版本**:2026-05  
**适用范围**:本地部署、开源、可商用

---

## 1. 选型目标与硬约束

| 项 | 要求 |
|---|---|
| 部署方式 | 本地推理(离线 / 私有 GPU 服务器),不依赖云 API |
| 许可证 | OSI 认可的开源协议或等价宽松协议,**允许商用** |
| 语言覆盖 | 英语(主)、中文、西班牙语、法语、德语、俄语 |
| 输出能力 | 文本 + 词级时间戳(必需);标点/大小写、说话人分离(可选) |
| 排除项 | CC-BY-NC、研究专用、需企业 BAA 的协议;闭源 API |

---

## 2. 候选模型许可证审查

许可证是这份选型的第一道筛子。任何不可商用的模型直接淘汰。

| 模型 | 许可证 | 商用 | 备注 |
|---|---|---|---|
| Whisper(全系) | MIT | ✓ | OpenAI,2022 起,2024-10 停更 |
| Distil-Whisper | MIT | ✓ | HuggingFace 蒸馏版,英文专精 |
| Parakeet TDT 0.6B v2 | CC-BY-4.0 | ✓ | NVIDIA,英文专精 |
| Parakeet TDT 0.6B v3 | CC-BY-4.0 | ✓ | NVIDIA,25 种欧洲语言 |
| **Canary-1B(v1)** | CC-BY-NC-4.0 | **✗** | NVIDIA,非商用,**淘汰** |
| Canary-1B-v2 | CC-BY-4.0 | ✓ | NVIDIA,25 种欧洲语言,准确率取向 |
| Canary-1B-Flash | CC-BY-4.0 | ✓ | NVIDIA,4 种语言,速度取向 |
| Voxtral Small 24B / Mini 3B | Apache 2.0 | ✓ | Mistral,2025-07;音频 LLM |
| Voxtral Realtime | Apache 2.0 | ✓ | Mistral,2026-02;流式变体 |
| Phi-4-Multimodal-Instruct | MIT | ✓ | Microsoft,3.8B 多模态 |
| Granite-Speech-3.3-8B | Apache 2.0 | ✓ | IBM,英文专精,Open ASR 榜首之一 |
| SenseVoice-Small | FunASR Model License | ⚠️ | 阿里 FunAudioLLM,商用允许但有"禁止行为"条款,合同前需法务复核 |
| FunASR Paraformer-zh | FunASR Model License | ⚠️ | 同上 |
| FireRedASR-AED-L / LLM-L | Apache 2.0(代码),模型条款单列 | ⚠️ | 小米,需逐个 README 核对 |

**关键淘汰**:Canary-1B v1 因 NC 协议出局,只能用 v2/Flash。

**SenseVoice / FunASR 的灰色地带**:协议明文允许商用但有"禁止行为"清单(如不得用于违反法律、不得二次出售模型权重),与 MIT/Apache 的纯宽松协议有差距。**结论**:可用,但部署前应让法务对 [FunASR MODEL_LICENSE](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE) 走一遍签字流程。

---

## 3. 语言覆盖矩阵

| 模型 | EN | ZH | ES | FR | DE | RU |
|---|---|---|---|---|---|---|
| Whisper large-v3 / turbo | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Parakeet TDT 0.6B v2 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Parakeet TDT 0.6B v3** | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| **Canary-1B-v2** | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| Canary-1B-Flash | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ |
| Voxtral Small / Mini | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Phi-4-Multimodal | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Granite-Speech-3.3-8B | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ |
| **SenseVoice-Small** | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |

**核心观察**:

- **没有任何 NVIDIA 模型支持中文**(Granary 数据集只覆盖欧洲语言),所以中文必须从其他家挑
- 单模型覆盖全部 6 种语言的开源选项只有:Whisper、Voxtral、Phi-4-Multimodal
- 中文最强的开源模型(SenseVoice)不覆盖西/法/德/俄

**直接推论**:要拿到每种语言的最优解,必须双模型架构。

---

## 4. 性能与资源对比

数据来源:模型卡官方报告 + Open ASR Leaderboard(2026-03 截止)+ 模型技术报告。

### 4.1 英语短音频准确率(LibriSpeech / Open ASR 榜)

| 模型 | 平均 WER(Open ASR 多数据集) | 速度(RTFx) | FP16 显存 |
|---|---|---|---|
| Granite-Speech-3.3-8B | ~5.85% | 中等 | ~16 GB |
| Canary-Qwen-2.5B | ~5.6% | 较慢(LLM 解码) | ~10 GB |
| Phi-4-Multimodal | ~6.1% | 慢 | ~8 GB |
| Parakeet TDT 0.6B v2 | ~6.05% | **3380**(最快) | ~2 GB |
| Canary-1B-v2 | ~6.5%(英文)| ~1000 | ~6 GB |
| Parakeet TDT 0.6B v3 | ~6.32%(英文) | ~3000 | ~2 GB |
| Whisper large-v3 | ~7.4% | ~140 | ~10 GB |
| Whisper large-v3-turbo | ~7.5% | ~250 | ~6 GB |

> RTFx 越高越快;3380 表示模型每秒可转录 3380 秒音频。

### 4.2 多语言准确率(FLEURS WER,数值越低越好)

| 模型 | EN | ES | FR | DE | RU | ZH(CER) |
|---|---|---|---|---|---|---|
| Parakeet TDT v3 | ~6.3 | 类同 Whisper-L3 | 优于 Whisper-L3 | 类同 | ~10-12 | — |
| Canary-1B-v2 | ~5.8 | 优于 Parakeet v3 | 优于 Parakeet v3 | 优于 Parakeet v3 | 优于 Parakeet v3 | — |
| Whisper large-v3 | ~6.5 | ~5 | ~6 | ~5 | ~9 | ~14(中文 CER) |
| Voxtral Small 24B | ~5 | 优于 Whisper-L3 | 优于 Whisper-L3 | 优于 Whisper-L3 | 优于 Whisper-L3 | 中等 |
| SenseVoice-Small | 中等 | — | — | — | — | **~6-8(中文 CER 显著优于 Whisper)** |

> 数值是基于厂商论文与 Open ASR 榜单的近似,不同测试集有偏差。**绝对 WER 仅供横向参考,生产部署前必须用自有数据复测。**

### 4.3 资源占用与速度等级

| 等级 | 模型 | 体积 | 推理 GPU 最低 | CPU 可行 |
|---|---|---|---|---|
| 极轻 | SenseVoice-Small(int8) | ~250 MB | 4 GB | ✓ |
| 极轻 | Parakeet TDT 0.6B v2/v3(int8 ONNX) | ~600 MB | 4 GB | ✓(可观速度) |
| 轻 | Whisper large-v3-turbo(int8) | ~800 MB | 6 GB | ⚠️(慢) |
| 中 | Canary-1B-v2 / Flash | ~6 GB | 8 GB | ✗ |
| 中重 | Voxtral Mini 3B | ~6-8 GB | 12 GB | ✗ |
| 重 | Granite-Speech-3.3-8B | ~16 GB | 24 GB | ✗ |
| 重 | Voxtral Small 24B | ~48 GB | 48 GB(或量化后 24 GB) | ✗ |

---

## 5. 推荐架构

### 方案 A:Parakeet v3 + SenseVoice 双模型路由(**首选**)

```
                  ┌── 语言判断 ─┐
                  │             │
   音频 ────────► │ ZH/Yue/JA/KO ├──► SenseVoice-Small
                  │             │
                  │ EN/ES/FR/DE │
                  │   /RU + 20  ├──► Parakeet TDT 0.6B v3
                  │   种欧语    │
                  └─────────────┘
```

**优点**
- 两个模型相加 ~1 GB,4 GB 显存即可同时常驻
- 都是 CC-BY-4.0 / FunASR-License,可商用
- 都比 Whisper-large-v3 快一个数量级
- 都自带词级时间戳(SenseVoice 用 CTC alignment,Parakeet 用 TDT 原生时间戳)

**缺点**
- 需要做语言路由(简单的方法:从音频前 5 秒过 SenseVoice 拿 LID 标签;或者由上游元数据指定)
- Parakeet 词级时间戳精度比 WhisperX + wav2vec2 强制对齐略差(差几十毫秒,音频字幕场景一般够用)
- SenseVoice 协议非纯宽松,法务要看一眼

**许可证总成本**:CC-BY-4.0 要求注明出处(在产品文档/第三方公告里写上模型来源即可),无版权金;FunASR-License 同样无费用,但需复核禁止条款。

### 方案 B:Canary-1B-v2 + SenseVoice(**准确率优先**)

把 Parakeet v3 替换成 Canary-1B-v2:

- 准确率系统性优于 Parakeet v3(几个百分点 WER)
- 速度从 ~3000 RTFx 降到 ~1000 RTFx,仍比 Whisper 快 7-10 倍
- 显存从 2 GB 升到 6 GB
- 同样 CC-BY-4.0

**适合场景**:对准确率敏感(广电级字幕、法务转录)、可承担更大显存的部署。

### 方案 C:Voxtral Small 24B 单模型(**架构最简**)

只跑一个模型覆盖所有 6 种语言。

- Apache 2.0,法务最干净
- 多语言 ASR 优于 Whisper-large-v3
- 中文 ASR 质量介于 Whisper 和 SenseVoice 之间(没有 SenseVoice 强,但优于 Whisper)
- 额外能力:可以直接对音频做问答 / 摘要(LLM 解码器是 Mistral Small 3.1)
- 缺点:24B 模型显存吃紧(48 GB,量化 24 GB),速度比 Parakeet 慢一个数量级,英文准确率不如 Granite 或 Parakeet

**适合场景**:愿意为"单一模型 + 法务最干净 + 顺带音频理解能力"付出更高的硬件成本。

### 方案 D:Whisper large-v3-turbo 单模型(**最低门槛兜底**)

仍然把它列出来作为基线参考:

- MIT,法务零阻力
- 99 语言全覆盖,生态(whisper.cpp / faster-whisper / WhisperX)最成熟
- 准确率和速度都已被超越,但**配合 WhisperX 做 wav2vec2 强制对齐**,词级时间戳精度仍是开源最高
- 适合:小语种支持是硬需求(俄语之外还要泰语、越南语等);或者已有大量基于 Whisper 工具链的代码不愿重写

---

## 6. 硬件需求(以方案 A 为基线)

| 部署形态 | 配置 | 1 小时音频转录耗时(估) |
|---|---|---|
| 桌面 / 工作站 | RTX 4090(24 GB) | ~30-60 秒 |
| 桌面 / 工作站 | RTX 3060(12 GB) | ~1-2 分钟 |
| Apple Silicon | M2 Max / M3 Pro 以上 | ~1-2 分钟 |
| 服务器 | 单 A100 40 GB | ~20 秒(可批量) |
| CPU 兜底 | 8 核 x86 + ONNX Runtime | ~3-8 分钟 |

方案 B/C 的耗时分别 × 3 / × 10。

---

## 7. 推荐周边工具(同样开源 / 可商用)

| 任务 | 工具 | 协议 | 备注 |
|---|---|---|---|
| VAD | Silero VAD | MIT | 几 MB,faster-whisper / Parakeet 都直接调 |
| VAD(轻量) | WebRTC VAD | BSD | 纯 C,精度低于 Silero |
| 词级强制对齐 | wav2vec2 + CTC | MIT | WhisperX 默认方案,精度最高 |
| 说话人分离 | pyannote/speaker-diarization-3.1 | MIT | 模型本身需 HF 用户协议(不是商用障碍,只是需点击同意) |
| 中文标点恢复 | FunASR ct-punc | FunASR-License | 与 SenseVoice 同协议 |
| 音频解码/重采样 | ffmpeg | LGPL/GPL | 标准依赖 |
| 简繁转换 | OpenCC | Apache 2.0 | C++/Python 都有 |
| 字幕格式 | pysubs2 | MIT | SRT/VTT/ASS 一锅端 |

---

## 8. 验证清单(部署前必跑)

不要直接信任厂商论文里的 WER。用自己的素材跑一遍下面的对比:

1. **准备测试集**:每种语言挑 3-5 段、每段 5-10 分钟、覆盖典型场景(新闻播报 / 访谈 / 嘈杂环境 / 多人对话)
2. **跑下面三套**(全部本地):
   - Parakeet v3(英 + 西法德俄)+ SenseVoice(中)— 方案 A
   - Canary-1B-v2(英 + 西法德俄)+ SenseVoice(中)— 方案 B
   - Whisper large-v3-turbo(全语种)— 基线
3. **对比指标**(不只看 WER):
   - 字符级 / 词级 WER
   - 词级时间戳与人工标注的偏差中位数(ms)
   - 静音段是否产生幻觉文本(选一段全静音音频跑)
   - 数字、专有名词、地名识别准确率(新闻类内容的高频痛点)
   - 标点和大小写质量
4. **吞吐压测**:固定一段 1 小时音频,跑 10 次取中位数,记录 RTFx
5. **显存峰值**:开 nvtop / nvidia-smi 监控,记录每个模型的实际峰值显存

---

## 9. 已知风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| Whisper 系列已停更 | 无新版本带来准确率/速度提升;依赖社区维护 | 不再作为新项目主选,仅做兜底 |
| Parakeet/Canary 不支持中文 | 中文必须独立模型 | 接受双模型架构;或退回 Voxtral / Whisper |
| SenseVoice 协议非纯宽松 | 商用合规需法务复核 | 部署前签字;若不能接受,改用 Whisper / Voxtral 处理中文 |
| CC-BY-4.0 的署名要求 | 必须在产品文档/页脚标注模型来源 | 在 About / 第三方声明里写上即可 |
| 模型权重通过 HuggingFace 分发 | 部分模型(pyannote 等)需用户协议 | 不影响商用,但注册 HF 账户必要 |
| 词级时间戳精度差异 | 字幕同步可能偏差几十毫秒 | 关键场景叠加 wav2vec2 强制对齐 |
| 多语言模型的语种串档 | 边界处可能误识别为相邻语言 | 上游显式指定语言而非依赖自动检测 |

---

## 10. 最终建议

**如果不愿意做更多评估**:直接采用方案 A(Parakeet TDT 0.6B v3 + SenseVoice-Small),这是当前开源 + 商用 + 覆盖你 6 种语言下,综合速度、准确率、资源占用、生态成熟度的最优组合。

**评估预算如果还有 1-2 周**:把方案 B(Canary-1B-v2 替换 Parakeet)和方案 C(Voxtral 单模型)也跑一遍真实数据对比,根据准确率/速度/部署复杂度的实际权衡再做最终决策。

**法务流程并行启动**:CC-BY-4.0 通过即可;FunASR Model License 提前发给法务,这是周期最长的环节。
