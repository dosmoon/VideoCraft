# 10 — 自媒体节目形态模块设计规范

## 设计原则

每一种自媒体节目形态，对应一个**独立的定制菜单模块**。  
不追求通用配置化，追求**针对该形态最顺手的操作流**。

---

## 模块注册方式

### 菜单位置
在 `VideoCraftHub._build_menu()` 中，为每种形态注册一个顶级菜单项（或子菜单项）：

```python
# 例：文字转视频菜单下的每日要闻
t2v_menu.add_command(label="每日要闻合成",
                     command=lambda: self.open_tool("daily-news"))
```

### TOOL_MAP 注册
```python
TOOL_MAP = {
    "daily-news": {"file": "text2Video.py", "class": "DailyNewsApp"},
    # 新形态：
    # "format-key": {"file": "对应文件.py", "class": "对应类名"},
}
```

---

## 当前实现状态

[tools/text2video/text2video.py](../../src/tools/text2video/text2video.py) 目前包含 4 个工具类，都是 "节目形态模块"的具体实现或基础工具：

| 类 | 职责 |
|----|------|
| `TTSApp`           | 单角色 / 多角色对话文本转语音（Fish Audio SDK），多角色解析 + 逐段合成 + ffmpeg concat |
| `SRTFromTextApp`   | 根据音频时长 + 文本内容按字符比例分配时轴，生成 SRT（非真实逐句 ASR 时间戳） |
| `AudioVideoApp`    | 多章节音频 + 背景图/视频 + 字幕 → 合成为最终视频（集成 core/subtitle_ops 的样式构建和分割） |
| `DailyNewsApp`     | 每日要闻滚屏合成——稿子滚动 + 背景图 + 水印，竖屏优先，是本文档的参考实现 |

`TTSApp` + `AudioVideoApp` 的组合提供了"文本 → 音频 → 视频（含字幕烧录）"完整链路；`DailyNewsApp` 则是针对"每日要闻"这种特定节目形态的定制实现，不追求通用性。

---

## 模块设计模式

以 `DailyNewsApp`（每日要闻合成）为参考实现：

### 核心技术栈
| 层 | 技术 | 说明 |
|----|------|------|
| 文字渲染 | PIL (`ImageDraw`, `ImageFont`) | 精确度量中英文混排宽度，逐字符换行 |
| 视频合成 | ffmpeg `filter_complex` | `overlay:eval=frame` 实现滚动/动效 |
| 音频 | ffmpeg `-shortest` | 以音频为时长锚点 |
| 字幕 | ffmpeg `drawtext` | 固定元素（水印等）用 drawtext，动态内容用 overlay |

### 文字换行（PIL 精确换行）
```python
# 用 textbbox 逐字符度量，支持中英文混排
for ch in paragraph:
    test = cur + ch
    if draw.textbbox((0,0), test, font=font)[2] > text_area_w and cur:
        lines.append(cur); cur = ch
    else:
        cur = test
```
不使用 ffmpeg `drawtext` 的 `\n` 转义——中文场景下极不可靠。

### 滚动公式（匀速，起止于屏幕中间区域）
```
y_start     = H × 3/4     （从屏幕下四分之三处进入）
y_end       = H × 1/4 - total_text_h  （滚出上四分之一）
总位移       = H/2 + total_text_h
速度(px/s)  = 总位移 / 音频时长
y(t)        = H×3/4 - t × 速度
```

### 水印（固定右上角）
- PIL 渲染的文字图层（透明 PNG）用 `overlay:eval=frame` 滚动
- 水印用 ffmpeg `drawtext` 叠加在最终帧上，不随内容滚动

### 文字背景半透明色块
用 `Image.alpha_composite` 在透明 PNG 上预先绘制，随文字一起滚动。

---

## 各形态规划

| 形态 | 模块 Key | 状态 | 特点 |
|------|---------|------|------|
| 每日要闻 | `daily-news` | ✅ 已实现 | 稿子滚屏 + 背景图 + 水印，竖屏优先 |
| 访谈节目 | `interview` | 待规划 | 多角色 TTS + 分屏布局 |
| 推文朗读 | `tweet-reader` | 待规划 | 音色克隆 + 推文排版截图 |
| 新闻简报 | `news-brief` | 待规划 | 多条目列表逐条显示 |

---

## 文件组织约定

- 每个形态的主逻辑写在独立 Python 文件或合并到 `text2Video.py` 中作为独立类
- 公共工具（PIL 换行、ffmpeg 滚动、颜色转换等）提取到 `core/` 供复用
- 不同形态的 UI 参数互不干扰，各自持有独立的 `tk.StringVar` / `tk.IntVar`
