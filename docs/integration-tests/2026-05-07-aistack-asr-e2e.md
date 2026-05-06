# aistack ASR 全链路对比测试报告 — 2026-05-07

> 给 aistack 仓库 Claude Code 会话的读物。本文档由 VideoCraft 端会话生成，
> 跨 repo 的协议契约层是 aistack 的 `docs/api/asr.md`；本档不直接修改 aistack 端任何文件，
> 仅记录 VideoCraft 实测发现的 backend 行为差异，供 aistack 端排期改进。

## 测试上下文

- **日期**：2026-05-07
- **VideoCraft commit**：`607f0be` (AI Console 改版后第一次端到端实测)
- **aistack commit**：`b1dd015` (D6 完工后状态)
- **aistack 服务**：本机 `127.0.0.1:11500`
- **硬件**：RTX 4060 Laptop / 8 GB VRAM
- **测试源**：Trump 川普讲话 17 分钟英文音频 (`川普讲话20260506.mp4`)
- **测试方法**：VideoCraft AI Console 改版后的功能路由表，逐项把 ASR task 切到 aistack + 不同 model，触发 `/v1/audio/transcriptions`

四份产出 SRT：

| 文件后缀 | Backend |
|---|---|
| `_en.srt` | Lemonfox（云 ASR，对照基线） |
| `_en 2.srt` | Parakeet TDT 0.6B v3 (NeMo) |
| `_en 3.srt` | Whisper-small (faster-whisper / CTranslate2) |
| `_en 4.srt` | SenseVoice Small (FunASR) |

aistack 端的 hot-swap 行为符合设计：

```
INFO:aistack.cache:hot-swap evict provider=faster-whisper key=('small', 'cuda', 'float16')
                    (loading sensevoice/iic/SenseVoiceSmall)
INFO:     127.0.0.1:54805 - "POST /v1/audio/transcriptions HTTP/1.1" 200 OK
```

`asr-main` category 互斥规则起效，三个 backend 在 8 GB VRAM 上轮转无 OOM。

---

## 量化对比

| 指标 | Lemonfox | Whisper-small | Parakeet | SenseVoice |
|---|---|---|---|---|
| **段数** | 467 | 472 | 298 | 190 |
| **平均段长** | ~2.2 s | ~2.2 s | ~3.4 s | ~5.4 s |
| **首段起始** | 00:06.58 | 00:06.58 | **00:11.84** ⚠ | 00:06.65 |
| **末段终点** | 17:04 | 17:04 | 17:02 | 17:05 |

---

## 关键发现（按严重性排序）

### 🔴 1. SenseVoice 英文输出**没有空格**

整篇没有任何 word boundary：

```
Msready,yessir.
I'mabig.
Sportsman,therearenopeopletougherinsportsthanthepeople.
AndIreallybelieveyou'reprobablybornwiththepunchandyou'rebornwithhimbuildingintotakeapunchtoo,
```

不是偶发，整篇都这样。原因：FunASR / SenseVoice 的 BPE tokenizer 在英文场景下，sub-piece
合并时丢了 word boundary（应该是按 SentencePiece `▁` 前缀切，目前明显没切）。
这是 **SenseVoice 在英文上的已知模型行为**，不是 aistack 接入 bug。

**当前状态**：英文场景下 SenseVoice 不可用 — 烧字幕直接报废。

**aistack 端建议方案**（按工作量排序）：
- ⭐ A. 在 `aistack/asr/sensevoice.py` 出口加一道 `wordninja` 或 `wordsegment` 后处理
  + truecase 恢复（仅在 detected_lang ∈ {"en"} 时触发）
- B. 复查 FunASR 的 SentencePiece 解码逻辑，看能否调参让它正确按 `▁` 分词
- C. 在 ASR 路由里直接禁掉 SenseVoice 的非 CJK 走向（语言检测 ≠ CJK 时 fallback 到 whisper）

### 🟡 2. Parakeet 漏前 11 秒

Parakeet 的首段从 `00:11.84` 起，漏掉了 Lemonfox/Whisper/SenseVoice 都识别到的开场寒暄：
- "Are you guys ready?"
- "Yes, sir."
- "Well, thank you very much."

NeMo VAD 默认阈值偏高，开场小声说话过不了门。**aistack 端建议**：
- 在 `aistack/asr/parakeet.py` 调低 VAD 阈值（具体参数：`vad_threshold` / `min_speech_duration_ms` 等）
- 或者把这个参数暴露给 `/v1/audio/transcriptions` 做 query 参数，让客户端按场景调

### 🟢 3. Lemonfox ≈ Whisper-small —— 完全可替代

时间戳逐毫秒吻合（`00:06,580` / `00:14,240` 都一样），段数仅差 5。Lemonfox 后台明显是
Whisper 系。本地 Whisper-small 出来后，**Lemonfox 在英文场景没有保留必要**。

VideoCraft 后续可考虑 deprecate Lemonfox provider（这是 VideoCraft 端决策，记录在此）。

### 🟢 4. SenseVoice 时间戳能力被低估

最初的判断"SenseVoice 没有 word/char-level 时间戳"是错的。FunASR 2024-11 加了能力：

- `funasr/models/sense_voice/model.py:861` 接受 `output_timestamp=True`
- 模型在自己的 encoder logits 上跑 CTC 强制对齐，返回 `timestamp: [[start_ms, end_ms], ...]`
  和对齐到的 `words` 数组
- 中文 → 每个汉字一条；英文 → sub-piece 合并成 word
- **不需要外挂** Paraformer / `fa-zh` aligner

**aistack 端 TODO（请确认）**：
- [ ] `aistack/asr/sensevoice.py` 调 `model.generate()` 时是否传了 `output_timestamp=True`？
- [ ] 如果传了，返回的 `timestamp` 字段有没有透传到 `/v1/audio/transcriptions` 的
      `verbose_json.words[]`（统一 OpenAI verbose_json shape）？
- [ ] 如果没传/没透传 → 1 行 fix；fix 后 SenseVoice 在中文场景下**比 Whisper 更细**
      （汉字级 vs 词级），是它真正的舒适区。

---

## 各 backend 时间戳能力总表

| 引擎 | 时间戳粒度 | 实现 | 精度备注 |
|---|---|---|---|
| Lemonfox | word-level | Whisper 后端 `verbose_json.words[]` | 同 Whisper，cross-attention DTW，偶有 ±100 ms 抖 |
| Whisper-small | word-level | faster-whisper `word_timestamps=True` | DTW 后处理，同上 |
| **Parakeet TDT** | word-level | TDT 模型直出 token+duration | **最稳**（NVIDIA 推 TDT 的卖点） |
| **SenseVoice** | word-level (英) / char-level (中) | encoder logits + CTC forced-align (自带) | 中文场景汉字级，比 Whisper 细 |

四个都能给词级时间戳。Parakeet 理论最稳，SenseVoice 中文最细。

---

## 专名识别准确度

参考 ground truth：Ciryl Gane / Alex Pereira / Ilia Topuria / Justin Gaethje / Khabib /
Dana White / Trump / Pope Leo / Marco Rubio / ExxonMobil / Chevron。

| 专名 | Lemonfox | Whisper-small | Parakeet | SenseVoice |
|---|---|---|---|---|
| Ciryl Gane | Cyril Gahn | Ciro gone | Ciro Gunn | CirilG / Cyil |
| Alex Pereira | ✓ | ✓ | ✓ | **AlexBarrera ✗** |
| Ilia Topuria | Ilya Toporya | Ilya Tapuria | **Ilya Topuria ✓** | IliaJaoria |
| Justin Gaethje | Justin Gehchi | Justin Geici | Justin Gagey | JustinGeieci |
| Khabib | ✓ | ✓ | Kabib | (跳过) |
| Chevron | **Shevran ✗** | ✓ | ✓ | ✓ |
| ExxonMobil | ✓ | ✓ | ✓ | ExxonMobile |

**Parakeet 专名最准** —— Topuria 唯一全对，Pereira / Chevron 都对。但漏开头是硬伤。

---

## 段落级 disfluency / 幻觉

| 维度 | Lemonfox | Whisper-small | Parakeet | SenseVoice |
|---|---|---|---|---|
| Disfluency 滤除 | 部分 | 少 ("this this are real") | 几乎不滤（保留大量 "uh"） | 多 |
| 幻觉 | 偶发 ("Connective. I'm not bad") | 少 | 少 | 偶发 ("He's going to go crazy" 多出) |

---

## 段长 / 烧字幕适配

举例：同一段 0:24~0:27

- **Lemonfox**：3 段
  - "I know the football players."
  - "I know just about everybody you can know."
  - "And they come to the Oval Office."
- **Whisper-small**：3 段（同上）
- **Parakeet**：1 段，三句合并
- **SenseVoice**：1 段，无空格

直接烧字幕：Lemonfox / Whisper-small ≫ Parakeet（需后处理切段） ≫ SenseVoice（不可用）。

---

## VideoCraft 端的使用推荐（已落到 AI Console）

| 场景 | 推荐 backend |
|---|---|
| 英文新闻短片直接烧字幕 | Whisper-small (本地) |
| 抠人名 / 正式抄录 | Parakeet（手补开头 + 后处理切段） |
| CJK 内容 | SenseVoice |
| 英文 + SenseVoice | **不用**（除非 aistack 落地空格还原后处理） |
| Lemonfox | 退役候选 |

---

## 给 aistack 的三条 backlog（按优先级）

1. **🔴 P1 — SenseVoice 英文 word-segmenter 后处理**
   - 文件：`aistack/asr/sensevoice.py`
   - 触发条件：`detected_lang in {"en"}`（或非 CJK 时通用）
   - 方案：`wordninja` / `wordsegment` 切词 + 简单 truecase 恢复
   - 验收：再跑一遍本测试，输出文本与 Whisper-small 同质（带空格）

2. **🟡 P2 — SenseVoice `output_timestamp=True` 透传**
   - 文件：`aistack/asr/sensevoice.py`
   - 检查 `model.generate()` 调用是否带 `output_timestamp=True`
   - 检查返回的 `timestamp` / `words` 有没有映射到 OpenAI verbose_json 的 `words[]` shape
   - 验收：`POST /v1/audio/transcriptions` with `model=sensevoice`,
     `response_format=verbose_json` 返回的 JSON 里 `words[]` 非空

3. **🟡 P2 — Parakeet VAD 阈值降一档**
   - 文件：`aistack/asr/parakeet.py`
   - 默认值降低（具体阈值待 NeMo 文档查），或暴露成 query 参数
   - 验收：本测试音频 Parakeet 路径首段起始 ≤ `00:09.0`

---

## 测试产物归档

四份 SRT 原文件：
```
D:\My_新闻短片\20260506\川普讲话\川普讲话20260506\subtitles\川普讲话20260506_en.srt        (Lemonfox)
D:\My_新闻短片\20260506\川普讲话\川普讲话20260506\川普讲话20260506_en 2.srt              (Parakeet)
D:\My_新闻短片\20260506\川普讲话\川普讲话20260506\川普讲话20260506_en 3.srt              (Whisper-small)
D:\My_新闻短片\20260506\川普讲话\川普讲话20260506\川普讲话20260506_en 4.srt              (SenseVoice)
```

aistack 端如需复现，可拿同一份音频走自身 e2e 测试。
