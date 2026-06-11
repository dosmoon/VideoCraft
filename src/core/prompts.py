"""Prompt hub — central storage for all AI prompts used by feature layer.

Every prompt is a markdown file under `<repo>/prompts/<task_id>.md`. The
file content IS the prompt template, with `{placeholder}` substitution
done by the caller via `str.format(**vars)`.

Per architecture principle 4 (see docs/design/04-ai-router.md):
prompts MUST NOT live in tool UIs. Feature layer (core/srt_ops, core/
translate, ...) calls `prompts.get(task_id)` to fetch the template, then
fills placeholders before passing to ai.complete().

Reset path: each task has a built-in default constant in this module
(used both as the initial seeded file AND as the "Reset to default"
target in the AI Console UI).

Phase 1 limitations (intentional):
  - Single prompt per task. Per-(task, provider) variants are
    deferred (Phase 2; see design doc).
  - Storage path is `<repo>/prompts/`; a user override layer in
    `<repo>/user_data/prompts/` was never implemented (the central
    prompt hub is being dismantled in favor of per-plugin prompts).
    Edits write directly to the shipped path.
"""

from __future__ import annotations

import os
from typing import Iterable


# ── Path resolution ─────────────────────────────────────────────────────────

def prompts_dir() -> str:
    """Return absolute path to the repo's prompts/ directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    # src/core -> src -> <repo root>
    return os.path.normpath(os.path.join(here, "..", "..", "prompts"))


def _path(task_id: str) -> str:
    return os.path.join(prompts_dir(), f"{task_id}.md")


# ── Built-in defaults ───────────────────────────────────────────────────────
# Single source of truth for "Reset to default" and for first-run seeding
# when prompts/*.md is missing. These are duplicated as files in
# `<repo>/prompts/` at install time so users can edit without code edits.

DEFAULTS: dict[str, str] = {

    "translate": (
        "You are a professional SRT subtitle translator. Translate the "
        "following subtitles from {source_lang_name} to {target_lang_name}.\n"
        "\n"
        "The input is a batch of {batch_size} subtitles, each prefixed "
        "with a 【number】 marker to identify its position. Use the marker's "
        "number as the `index` in your response.\n"
        "\n"
        "Rules:\n"
        "1. Translate each subtitle independently. Do NOT merge, split, "
        "add, or remove subtitles — return exactly {batch_size} items.\n"
        "2. Preserve line breaks and punctuation within each subtitle.\n"
        "3. Do not wrap translations in quotation marks unless quotes are "
        "part of the original meaning.\n"
        "4. Ensure natural, fluent {target_lang_name}.\n"
        "\n"
        "Input subtitles (batch size = {batch_size}):\n"
        "{numbered_input}\n"
    ),

    "subtitle.segments": (
        "# 生成时间戳分段\n"
        "\n"
        "【\n"
        "\n"
        "1、你知道youtube的视频分段的格式吧？请学习这种分段格式：\n"
        "\n"
        "xx:xx 标题\n"
        "\n"
        "xx:xx 标题\n"
        "\n"
        "xx:xx 标题\n"
        "\n"
        "2、请根据srt字幕内容，生成youtube分段描述（中文）\n"
        "\n"
        "3、如有记者提问，优先以记者提问内容作为标题\n"
        "\n"
        "4、时:分:秒，这是时间戳的基本格式，不要弄错了\n"
        "\n"
        "】\n"
        "\n"
        "以下是SRT字幕内容：\n"
        "\n"
        "{subtitle_content}\n"
        "\n"
        "请根据以上字幕内容生成YouTube分段描述，格式为每行一个分段，"
        "格式为：时:分:秒 标题"
    ),

    "subtitle.refine": (
        "## 精炼全部分段\n"
        "\n"
        "【\n"
        "请一次性对全部分段内容进行总结提炼，每个段落提炼后不超过128个字。\n"
        "对于问答段落，保留精炼后的问题和回答，保持问答说话人的视角，"
        "不要改为第三方转述。\n"
        "输出格式为：\n"
        "时间戳 标题\n"
        "精炼内容\n"
        "\n"
        "分段之间空一行，不要添加解释。\n"
        "】\n"
        "\n"
        "以下是全部分段内容：\n"
        "{all_segments_content}\n"
    ),

    "subtitle.titles": (
        "## 生成标题\n"
        "\n"
        "【\n"
        "给这个视频起个合适的名字，新闻性十足、概括核心焦点，"
        "稍微长些没关系\n"
        "\n"
        "】"
    ),

    "subtitle.pack": (
        "# 一次性生成视频标题、时间戳分段、精炼描述与核心要点\n"
        "\n"
        "**输出语言硬性要求：titles、以及每个 segment 的 title / refined / "
        "key_points，全部必须使用 {output_language}，即输入字幕本身的语言。"
        "本提示词和附带的背景资料即使是中文，也不改变这一要求。**\n"
        "\n"
        "请基于以下SRT字幕内容，一次性产出三类结果：\n"
        "\n"
        "1. titles：为该视频拟 1–3 个候选标题。要求新闻性十足、"
        "概括核心焦点；如包含记者提问，可参考核心问题作为标题素材。\n"
        "2. segments：按 YouTube 风格切分时间戳分段。\n"
        "   - 时间戳格式严格为 HH:MM:SS（时:分:秒），不要使用 mm:ss。\n"
        "   - 每段给出简短标题；如有记者提问，优先以记者提问内容作为标题。\n"
        "   - 切分粒度参考视频自然话题转折，不要过细也不要过粗。\n"
        "3. 每个 segment 的 refined 字段：对该段内容做精炼总结，"
        "不超过 128 个汉字（非中文输出 ≤80 词）。\n"
        "   - 对于问答段落，保留精炼后的问题与回答，并保持问答说话人的"
        "视角，不要改写为第三方转述。\n"
        "   - 不要复述原文，给出信息密度高的概括。\n"
        "\n"
        "4. 每个 segment 的 key_points 字段：该段中具体的事实 / 数据 / "
        "结论 / 决定（每条 ≤25 汉字 / 非中文 ≤12 词），按它们在 SRT 中"
        "出现的顺序列出。"
        "字符串数组，无具体事实可标（如纯仪式性问候 / 静默 / 纯过场）"
        "则返回 []。\n"
        "\n"
        "返回严格符合调用方提供的 JSON Schema，不要附加任何解释文字。\n"
        "\n"
        "以下是SRT字幕内容：\n"
        "\n"
        "{subtitle_content}\n"
    ),

    "news.source_context": (
        "# 源视频上下文抽取 / Source video context extraction\n"
        "\n"
        "你是新闻 / 时事类视频的资料分析助手。任务：从下面的种子"
        "信息出发，**主动用联网搜索能力**产出一份完整、准确、规范"
        "的事件档案 JSON，供下游 AI 任务（章节、标题、热点片段、"
        "发布稿、字幕烧录、屏幕组件渲染）作为唯一真相源使用。\n"
        "\n"
        "## 输入种子\n"
        "\n"
        "### 源 URL（请优先打开它）\n"
        "{url}\n"
        "\n"
        "### 平台元数据 (yt-dlp 抓取)\n"
        "- 上传者: {uploader}\n"
        "- 描述: {description}\n"
        "- 标签: {tags}\n"
        "\n"
        "### 用户填的线索 (basic_info — **只是线索，不是真相**)\n"
        "{existing_filled}\n"
        "\n"
        "**重要：这些线索可能拼错（例：'Vance' 应为 'James David"
        " Vance' 或常用 'JD Vance'）、可能不完整（只填了姓没填全"
        "名）、可能职位过时、日期可能用大致月份代替准确日。你的"
        "工作是用搜索核实并输出权威版本**——不要无脑照抄。如果"
        "线索为空，就完全靠搜索补全。\n"
        "\n"
        "## 输出字段定义 (15 字段全 string)\n"
        "\n"
        "**缺乏证据时返回空字符串 \"\"**，不要写 \"未知\" / \"unknown\""
        " / \"N/A\" / \"待定\" 等占位。\n"
        "\n"
        "### 锚点字段 (校正版 basic_info — 必须搜索核实)\n"
        "- host:           主讲人姓名，使用**官方常用写法 / 全名**。"
        "中文人物用中文名，英文人物用英文常用名。例：用户填 "
        "\"Vance\" → 你输出 \"JD Vance\" 或 \"James David Vance\"\n"
        "- host_bio:       一行身份，简洁权威，例 \"美国副总统\"、"
        "\"OpenAI CEO\"、\"Anthropic 联合创始人\"\n"
        "- event_date:     事件发生日期，YYYY-MM-DD。用户填的若为"
        "近似值，搜索新闻报道核实精确日期\n"
        "- event_location: 地点 + 城市，例 \"白宫椭圆形办公室·华盛顿\""
        "、\"达沃斯论坛主会场·瑞士达沃斯\"\n"
        "- episode_topic:  整集主题 ≤30 字，名词性短语，例 \"反医疗"
        "欺诈工作组发布会\"、\"AI 安全圆桌\"\n"
        "\n"
        "### 人物 (派生)\n"
        "- host_affiliation: 主讲人所属机构 (例: \"白宫\"、\"美国国务"
        "院\"、\"Anthropic\")\n"
        "- guests:           其他在场可识别人物 (其他官员 / 被点名"
        "记者 / 同台嘉宾)，顿号分隔；可空\n"
        "\n"
        "### 时间\n"
        "- event_time:     事件完整发生时间，**包含年月日 + 时分 + 时区**"
        "，格式 \"YYYY-MM-DD HH:MM TZ\" (例: \"2026-05-13 14:30 EDT\")。"
        "日期部分与你输出的 event_date 一致；时分部分主动搜索"
        "(发布会 / 演讲日程通常在主办方官网、Live 视频标题、新闻报道"
        "首段都有标注)。如时分确实查不到，至少填日期部分 (例: "
        "\"2026-05-13\")，不要返回完全空字符串\n"
        "\n"
        "### 事件\n"
        "- show_type:     节目类型 (新闻发布会 / 演讲 / 访谈 / 直播"
        "切片 / 课程 / 评论 / 解说)\n"
        "- event_summary: 事件简要概述，1-2 句完整中文，≤200 字，"
        "覆盖 \"谁在哪里做了什么、要点是什么\"。须与你输出的 host /"
        " event_date / event_location / episode_topic 一致\n"
        "- key_points:    核心议题或关键点 3-5 条，**每条独占一行**，"
        "以中间点 \"·\" 或减号 \"-\" 起首；下游 AI 选热点片段会参考\n"
        "\n"
        "### 背景\n"
        "- background:    相关历史背景或上下文事件，≤300 字。给下游"
        "AI 提供更广的语境 (例: 政策出台的前因、人物近期动态、"
        "相关事件链)。**必须基于实时搜索结果**，不要凭训练记忆"
        "推断\n"
        "\n"
        "### 产出层\n"
        "- audience:      目标受众 (媒体记者 / 普通公众 / 行业专业"
        "人士 / 学生 / ...)\n"
        "- platform_tone: 视频发布平台或风格倾向 (YouTube / B 站 / "
        "抖音 / 小红书 / TikTok)\n"
        "- notes:         敏感话题 / 称谓约定 / 平台禁忌词等下游 AI"
        " 需要知道的信息，≤80 字，可空\n"
        "\n"
        "## 工作流建议\n"
        "1. 先打开 URL 看页面标题 / 描述 / 频道，确认事件主体\n"
        "2. **核实并校正用户线索的 5 个锚点字段**（最重要的一步——"
        "下游所有渲染都用你输出的 host/event_date 等，不再回看用户"
        "的原始输入）\n"
        "3. 搜索主讲人当下职位、所属机构、近期动态\n"
        "4. 定位事件发生的具体日期、地点 (页面元数据 + 新闻报道"
        "交叉验证)\n"
        "5. 检索相关历史背景写入 background\n"
        "6. 综合以上信息撰写 event_summary 与 key_points\n"
        "\n"
        "返回严格符合调用方提供的 JSON Schema，不要附加任何解释"
        "文字。\n"
    ),

    "subtitle.hotclips": (
        "# 热点片段挖掘\n"
        "\n"
        "**输出语言硬性要求：hook / outro / why_viral / suggested_title / "
        "suggested_hashtags，全部必须使用 {output_language}，即输入字幕"
        "本身的语言。本提示词和附带的背景资料即使是中文，也不改变这一"
        "要求。**\n"
        "\n"
        "请基于以下 SRT 字幕内容，挖掘最多 {desired_count} 条"
        "具有传播潜力的短视频候选片段。每条片段应满足：\n"
        "\n"
        "- 时长在 {target_min_sec}~{target_max_sec} 秒之间\n"
        "- 自包含（开头和结尾完整，不依赖前后文）\n"
        "- 有吸引力的开场（反共识 / 悬念 / 强烈观点 / 数据反差 / 情绪密度高）\n"
        "\n"
        "对每条候选片段，输出：\n"
        "- start / end：HH:MM:SS 时间戳\n"
        "- duration_sec：整数秒\n"
        "- hook：开场一句钩子文案（≤30 字 / ≤15 词），用于片头吸引点击\n"
        "- outro：结尾一句 CTA 或总结文案（≤25 字 / ≤12 词），"
        "用于片尾收束并引导互动；要贴合本条切片内容，不要套用万能"
        "「关注三连」之类的空话\n"
        "- why_viral：一句话说明为什么这段有传播力\n"
        "- score：1~10 综合评分（10 = 极强），考虑 hook 强度、信息密度、"
        "情绪起伏、完整性\n"
        "- suggested_title：完整短视频标题（≤30 字 / ≤15 词）\n"
        "- suggested_hashtags：3~5 个相关标签（带 # 前缀）\n"
        "\n"
        "返回严格符合调用方提供的 JSON Schema，不要附加解释文字。\n"
        "\n"
        "以下是 SRT 字幕内容：\n"
        "\n"
        "{subtitle_content}\n"
    ),
}


# Placeholder catalog for UI display ("which {variables} this prompt uses").
# Feature layer is the contract owner — these strings are documentary.
PLACEHOLDERS: dict[str, list[str]] = {
    "translate": ["{source_lang_name}", "{target_lang_name}",
                  "{batch_size}", "{numbered_input}"],
    "subtitle.segments": ["{subtitle_content}"],
    "subtitle.refine":   ["{all_segments_content}"],
    "subtitle.titles":   [],
    "subtitle.pack":     ["{subtitle_content}", "{output_language}"],
    "subtitle.hotclips": ["{subtitle_content}", "{desired_count}",
                          "{target_min_sec}", "{target_max_sec}",
                          "{output_language}"],
    "news.source_context": ["{url}", "{uploader}", "{description}",
                            "{tags}", "{existing_filled}"],
}


# ── Public API ──────────────────────────────────────────────────────────────

def get(task_id: str) -> str:
    """Return the prompt template for `task_id`.

    Reads `<prompts_dir>/<task_id>.md` if present, else falls back to the
    built-in DEFAULTS. Returns empty string if neither has the task.
    """
    path = _path(task_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return DEFAULTS.get(task_id, "")


def set(task_id: str, content: str) -> None:
    """Write a new prompt template for `task_id` (overwrites any prior file)."""
    if task_id not in DEFAULTS:
        raise ValueError(f"Unknown task_id: {task_id!r}")
    os.makedirs(prompts_dir(), exist_ok=True)
    with open(_path(task_id), "w", encoding="utf-8", newline="") as f:
        f.write(content)


def reset(task_id: str) -> str:
    """Restore the built-in default prompt for `task_id`. Returns the
    default text that was written."""
    if task_id not in DEFAULTS:
        raise ValueError(f"Unknown task_id: {task_id!r}")
    default = DEFAULTS[task_id]
    set(task_id, default)
    return default


def apply_output_language(prompt: str, output_language: str) -> str:
    """Resolve the {output_language} directive in a built prompt.

    Replaces the placeholder when present. Prompt override files
    (prompts_dir) may predate the placeholder — in that case a full
    directive block is appended so stale overrides still get the
    output-language fix. Empty `output_language` degrades to a generic
    same-language instruction; the literal placeholder never reaches
    the model.
    """
    if "{output_language}" in prompt:
        name = (output_language
                or "与输入字幕相同的语言 (the same language as the input subtitles)")
        return prompt.replace("{output_language}", name)
    if output_language:
        return (prompt
                + "\n\n**输出语言硬性要求：所有输出文本必须使用 "
                + output_language
                + "，即输入字幕本身的语言。**\n")
    return prompt


def is_overridden(task_id: str) -> bool:
    """True if the on-disk prompt differs from the built-in default."""
    if task_id not in DEFAULTS:
        return False
    return get(task_id) != DEFAULTS[task_id]


def list_tasks() -> Iterable[str]:
    """Iterate task ids with built-in defaults (canonical prompt set)."""
    return DEFAULTS.keys()


def placeholders(task_id: str) -> list[str]:
    """Return the documented placeholder list for `task_id`."""
    return list(PLACEHOLDERS.get(task_id, []))


def ensure_files_exist() -> None:
    """First-run helper: write any missing prompts/<task>.md from defaults
    so the prompts/ folder is fully seeded for the user to browse / edit."""
    os.makedirs(prompts_dir(), exist_ok=True)
    for task_id, default in DEFAULTS.items():
        path = _path(task_id)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(default)
