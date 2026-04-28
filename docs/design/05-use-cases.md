# 用例集

## UC-01：下载 YouTube 视频并建立工程

**触发**：用户拿到一个 YouTube 链接，需要处理。

**交互流程**：
1. 打开 VideoCraftHub
2. `File > Open Folder...` → 选择或新建目标文件夹（如 `D:\Videos\my_project\`）
3. Hub 打开该文件夹：
   - 自动生成 `.videocraft/project.json`（若不存在；旧版本根级 `videocraft.json` 自动迁入）
   - Sidebar 显示文件夹内容（初始为空）
   - 状态栏显示当前工程路径
4. `Download > yt-dlp 下载器` → 弹出下载工具 Toplevel
   - 初始目录预填为当前工程文件夹
   - 用户粘贴 URL，点击下载
5. 下载完成 → 视频文件出现在工程文件夹
6. 点击 Sidebar 刷新按钮 → `🎬 video.mp4` 出现在列表

---

## UC-02：翻译已有 SRT 文件

**触发**：用户已有一份英文 SRT，需要翻译为中文。

**交互流程**：
1. `File > Open Folder...` → 选择含 SRT 的文件夹
2. Sidebar 显示 `📄 english.srt`
3. `翻译 > Gemini 翻译` → 弹出翻译工具 Toplevel
   - 源文件选择框预填工程文件夹路径（用户仍需点选具体文件）
4. 翻译完成 → `📄 english_zh.srt` 出现在 Sidebar

---

## UC-03：重新打开上次的工程

**触发**：用户关闭程序后重新打开，想继续上次的工作。

**交互流程**：
1. 打开 VideoCraftHub
2. `File > Recent Projects` → 子菜单显示最近 10 个工程
3. 点击目标工程路径 → 直接打开该文件夹
4. Sidebar 恢复显示上次的文件列表

---

## UC-04：管理 AI Provider 配置

**触发**：用户需要更换 AI 模型或添加新的 API Key。

**交互流程**：
1. `AI > Router 管理` → 弹出 Router 管理 Toplevel
2. 在 `Provider & Key` Tab 编辑 API Key
3. 在 `档位配置` Tab 为各档位选择 Provider + Model
4. 保存后生效，所有工具的下次 AI 调用即使用新配置

---

## UC-05：独立运行单个工具（开发/调试模式）

**触发**：开发者需要单独测试某个工具。

```bash
python src/tools/subtitle/srt_tools.py
python src/router_manager.py
python src/tools/translate/translate_srt.py
```

每个工具的 `__main__` 块直接启动独立 Tk 窗口，无需 Hub。

---

## UC-06：发布视频到 YouTube / TikTok

**触发**：字幕烧录完成，用户想一键发布到平台。

**交互流程**：
1. `发布 > YouTube 发布` （或 `TikTok 发布`） → 在新 Tab 打开发布工具
2. 首次使用：点"登录"→ 浏览器 OAuth 授权 → 回调 token 存到 `keys/` 下
3. 浏览选择本地视频文件
4. 填写标题、描述、标签、可见性（public / unlisted / private）、所属播放列表
5. （可选）勾选定时发布，选择日期时间（发布期间 Hub 需保持运行）
6. 点"上传"→ Tab 点变蓝 running → 进度显示分块上传百分比
7. 上传完成 → Tab 点变绿，底部日志显示 YouTube 视频链接 / TikTok publish_id
8. 失败 → Tab 点变红，底部日志显示 HTTP 错误码与响应内容

**相关文件**：[tools/publish/youtube_publish.py](../../src/tools/publish/youtube_publish.py)、[tools/publish/tiktok_publish.py](../../src/tools/publish/tiktok_publish.py)

---

## UC-07：保存和切换字幕烧录预设

**触发**：用户有多种稳定的字幕烧录场景（横屏中英双语、竖屏纯中文、带水印直播版等），希望一键切换参数而不是每次手改。

**交互流程**：
1. `视频 > 字幕烧录` → 打开工具，顶部是"参数预设"行
2. 调整参数（字幕字号、颜色、水印类型、编码速度等 27 项）
3. 点"另存为..." → 输入预设名（如"横屏双语"）→ 保存
4. 下次打开工具 → 自动加载上次用的预设（`last_used` 记忆）
5. 在"参数预设"下拉切换到另一个预设 → 27 项参数一次性应用
6. 不想要的预设点"删除"移除（Default 预设受保护，不可删）

**存储**：`~/.videocraft/presets/subtitle_burn.json`，flat dict 结构，内置 Default 对应硬编码默认值。

**相关文件**：[tools/subtitle/presets.py](../../src/tools/subtitle/presets.py)、[tools/subtitle/subtitle_tool.py](../../src/tools/subtitle/subtitle_tool.py)

---

## UC-08：切换界面语言

**触发**：英文用户第一次打开 VideoCraft 想换成中文，或中文用户给国际朋友演示想临时切到英文。

**交互流程**：
1. `File > Preferences...`（或中文"文件 > 首选项..."）→ 在新 Tab 打开 Preferences 面板
2. "界面语言 / Interface Language" 下拉选择目标语言
3. 点"保存 / Save"→ 写入 `~/.videocraft/settings.json`
4. 按钮旁显示橙色提示"已保存。关闭并重启 VideoCraft 以生效"
5. 用户关闭 Hub → 重新启动 → 所有菜单、欢迎页、已翻译的工具 UI 切换到新语言
6. 未完成字符串抽取的工具（Phase 2+）仍显示原语言

**为什么要重启**：Tk 的 Label 文本在创建时固化，运行时替换所有 widget 的 text 成本远高于重启。详见 [12-i18n.md](12-i18n.md)。

**Factory default**：`en`——面向开源英文用户；国内老用户一次切换到 zh 后会持久记住。
