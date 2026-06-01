/**
 * News-context AI extraction — prompt + schema, TS-side (ADR-0008 Phase B2/B3).
 *
 * Per the B2 decision the capability gateway stays generic (capability.llm_extract
 * takes {prompt, schema, task}); the news-specific knowledge — the 15-field schema,
 * the realtime-news prompt template, and how the user's basic_info hints + yt-dlp
 * platform metadata become a filled prompt — lives HERE in the plugin, not in core.
 * This is the TS port of the prompt-building half of the retired
 * `materials/news_video/ai_fill.py` (the LLM call itself is now capability.llm_extract).
 *
 * The prompt text is domain data sent to the model (NOT user-facing UI), so it
 * stays in its original Chinese; only code/comments are English.
 *
 * Caller flow (B3 workbench): read basic_info + platform meta → buildContextPrompt
 * → capability.llm_extract({prompt, schema: NEWS_CONTEXT_SCHEMA, task: NEWS_CONTEXT_TASK})
 * → contextFromDict(result) → model.writeContextDict. Replacement semantics (the
 * AI's fresh output fully replaces prior context.json) are preserved by the caller.
 */

import { CONTEXT_FIELDS, type SourceBasicInfo } from "./schema";

/** Routing task for the realtime-news LLM (cloud + web-search grounding). */
export const NEWS_CONTEXT_TASK = "news.realtime";

/** JSON schema constraining the 15-field context output (all strings, all required).
 * Mirrors ai_fill.py `_SCHEMA`; field order/identity comes from schema.ts CONTEXT_FIELDS. */
export const NEWS_CONTEXT_SCHEMA = {
  type: "object",
  properties: Object.fromEntries(CONTEXT_FIELDS.map((f) => [f, { type: "string" }])),
  required: [...CONTEXT_FIELDS],
  additionalProperties: false,
} as const;

/** Build the realtime-news extraction prompt from the user's basic_info hints and
 * the yt-dlp platform metadata. Faithful port of ai_fill.extract's prompt assembly:
 * tags joined (first 20), url falls back across webpage_url/original_url/url, empty
 * platform fields render as "—", and basic_info is embedded as indent-2 JSON. */
export function buildContextPrompt(basicInfo: SourceBasicInfo, platform: Record<string, unknown>): string {
  const tagsRaw = platform.tags;
  const tagsStr = Array.isArray(tagsRaw) ? tagsRaw.slice(0, 20).map((t) => String(t)).join(", ") : "";
  const url = String(platform.webpage_url ?? platform.original_url ?? platform.url ?? "").trim();
  const uploader = String(platform.uploader ?? "").trim();
  const description = String(platform.description ?? "").trim();
  const existingFilled = JSON.stringify(basicInfo, null, 2);

  return `# 源视频上下文抽取 / Source video context extraction

你是新闻 / 时事类视频的资料分析助手。任务：从下面的种子信息出发，**主动用联网搜索能力**产出一份完整、准确、规范的事件档案 JSON，供下游 AI 任务（章节、标题、热点片段、发布稿、字幕烧录、屏幕组件渲染）作为唯一真相源使用。

## 输入种子

### 源 URL（请优先打开它）
${url || "—"}

### 平台元数据 (yt-dlp 抓取)
- 上传者: ${uploader || "—"}
- 描述: ${description || "—"}
- 标签: ${tagsStr || "—"}

### 用户填的线索 (basic_info — **只是线索，不是真相**)
${existingFilled}

**重要：这些线索可能拼错（例：'Vance' 应为 'James David Vance' 或常用 'JD Vance'）、可能不完整（只填了姓没填全名）、可能职位过时、日期可能用大致月份代替准确日。你的工作是用搜索核实并输出权威版本**——不要无脑照抄。如果线索为空，就完全靠搜索补全。

## 输出字段定义 (15 字段全 string)

**缺乏证据时返回空字符串 ""**，不要写 "未知" / "unknown" / "N/A" / "待定" 等占位。

### 锚点字段 (校正版 basic_info — 必须搜索核实)
- host:           主讲人姓名，使用**官方常用写法 / 全名**。中文人物用中文名，英文人物用英文常用名。例：用户填 "Vance" → 你输出 "JD Vance" 或 "James David Vance"
- host_bio:       一行身份，简洁权威，例 "美国副总统"、"OpenAI CEO"、"Anthropic 联合创始人"
- event_date:     事件发生日期，YYYY-MM-DD。用户填的若为近似值，搜索新闻报道核实精确日期
- event_location: 地点 + 城市，例 "白宫椭圆形办公室·华盛顿"、"达沃斯论坛主会场·瑞士达沃斯"
- episode_topic:  整集主题 ≤30 字，名词性短语，例 "反医疗欺诈工作组发布会"、"AI 安全圆桌"

### 人物 (派生)
- host_affiliation: 主讲人所属机构 (例: "白宫"、"美国国务院"、"Anthropic")
- guests:           其他在场可识别人物 (其他官员 / 被点名记者 / 同台嘉宾)，顿号分隔；可空

### 时间
- event_time:     事件完整发生时间，**包含年月日 + 时分 + 时区**，格式 "YYYY-MM-DD HH:MM TZ" (例: "2026-05-13 14:30 EDT")。日期部分与你输出的 event_date 一致；时分部分主动搜索(发布会 / 演讲日程通常在主办方官网、Live 视频标题、新闻报道首段都有标注)。如时分确实查不到，至少填日期部分 (例: "2026-05-13")，不要返回完全空字符串

### 事件
- show_type:     节目类型 (新闻发布会 / 演讲 / 访谈 / 直播切片 / 课程 / 评论 / 解说)
- event_summary: 事件简要概述，1-2 句完整中文，≤200 字，覆盖 "谁在哪里做了什么、要点是什么"。须与你输出的 host / event_date / event_location / episode_topic 一致
- key_points:    核心议题或关键点 3-5 条，**每条独占一行**，以中间点 "·" 或减号 "-" 起首；下游 AI 选热点片段会参考

### 背景
- background:    相关历史背景或上下文事件，≤300 字。给下游AI 提供更广的语境 (例: 政策出台的前因、人物近期动态、相关事件链)。**必须基于实时搜索结果**，不要凭训练记忆推断

### 产出层
- audience:      目标受众 (媒体记者 / 普通公众 / 行业专业人士 / 学生 / ...)
- platform_tone: 视频发布平台或风格倾向 (YouTube / B 站 / 抖音 / 小红书 / TikTok)
- notes:         敏感话题 / 称谓约定 / 平台禁忌词等下游 AI 需要知道的信息，≤80 字，可空

## 工作流建议
1. 先打开 URL 看页面标题 / 描述 / 频道，确认事件主体
2. **核实并校正用户线索的 5 个锚点字段**（最重要的一步——下游所有渲染都用你输出的 host/event_date 等，不再回看用户的原始输入）
3. 搜索主讲人当下职位、所属机构、近期动态
4. 定位事件发生的具体日期、地点 (页面元数据 + 新闻报道交叉验证)
5. 检索相关历史背景写入 background
6. 综合以上信息撰写 event_summary 与 key_points

返回严格符合调用方提供的 JSON Schema，不要附加任何解释文字。
`;
}
