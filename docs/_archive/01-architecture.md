# 架构决策

> ⚠️ **状态：Superseded by [ADR-0008](../adr/0008-plugins-ts-python-capability-gateway.md)（2026-06-03）。**
> 本文档描述的"单进程 + Tk Tab 嵌入 / 无需 IPC / AI Router 进程内单例 / 多工具共享进程内全局状态"外壳模型已整体退役：产品迁到 Electron renderer + Python sidecar（JSON-RPC over stdio）拓扑，进程边界是**数据级**（Python 不渲染），Tk app 已删（见迁移设计文档 P2）。**进程模型已反转，但业务/引擎代码未重写**——引擎本就零 tkinter、IPC-ready。
> 仅作历史留档；当前架构权威 = [ADR-0006](../adr/0006-composition-timeline-ir.md)（数据模型）+ [ADR-0008](../adr/0008-plugins-ts-python-capability-gateway.md)（IPC 拓扑 + 插件语言边界）+ [`docs/draft/electron-migration-design.md`](../draft/electron-migration-design.md)。

## 单进程 + Tab 嵌入模式

**决策**：放弃 `subprocess.Popen` 启动工具，也不再弹 `tk.Toplevel`，改为把工具嵌入 Hub 的 Tab 内容区。

**保留 subprocess 的场景**：
- FFmpeg 调用（视频处理本就是子进程）

**保留 threading 的场景**：
- 所有长任务（AI 调用、下载、转写、TTS、字幕烧录等）

**好处**：
- AI Router 可作进程内单例，统计数据实时共享
- 无需 IPC、文件锁、守护进程
- 多工具同时打开共享一套全局状态（日志、Tab 状态、语言、布局）
- 工具关闭 = 关 Tab，主进程与其它工具不受影响

---

## 工具双模式设计

每个工具文件同时支持两种运行方式：

```python
# 嵌入模式（Hub 打开 Tab 时）
tool_frame = ToolFrame(content_area)   # ttk.Frame 子类，假装自己是 Toplevel
ToolClass(tool_frame)                  # 静默吸收 geometry/title/resizable 调用

# 独立模式（直接运行）
if __name__ == "__main__":
    root = tk.Tk()
    ToolClass(root)
    root.mainloop()
```

**兼容性**：`ToolFrame` 在 [VideoCraftHub.py](../../src/VideoCraftHub.py) 里实现，拦截 Toplevel 专属方法（`geometry()` / `title()` / `resizable()`），工具类无需感知嵌入与否。

**状态上报**：工具继承 [ToolBase](../../src/tools/base.py)，用 `self.set_busy() / set_done() / set_error(msg) / set_warning(msg)` 上报状态到 Hub 的 Tab 点和底部日志面板。这些方法线程安全（内部 `master.after(0, ...)` marshal）。

**注意**：若工具 `__init__` 内调用了 `self.root.mainloop()`，需移除（mainloop 由 Hub 统一管理）。

---

## 关键约束

- **不做全局状态共享**：工具间数据通过 Project 文件夹（文件系统）传递，不用共享内存
- **AI 调用走 facade**：UI 层一律 `from core import ai`（顶层 `ai_router.py` 仅作 legacy 兼容 shim）；providers / errors / cancellation 在 `src/core/ai/` 子包内，详见 [04-ai-router.md](04-ai-router.md)
- **错误传播**：`core/` 层工具函数失败一律 `raise`，UI 层在 try/except 里统一 `self.set_error(...)`，不静默失败
- **配置存储**（均在 `<repo>/user_data/` 下，绿色便携；老 `~/.videocraft/` 首次启动由 `core/user_data.py` 一次性 copy 迁移）：

  | 文件 | 用途 |
  |------|------|
  | `recent.json`                | 最近打开的工程列表（[project.py](../../src/project.py)） |
  | `layout.json`                | Hub 主窗口 geometry / sash / zoom / sidebar_tab（[hub_layout.py](../../src/hub_layout.py)，见 [11-hub-layout-persistence.md](11-hub-layout-persistence.md)） |
  | `settings.json`              | 用户偏好（`language` 等） |
  | `presets/subtitle_burn.json` | 字幕烧录工具的命名参数预设 |
  | `runtimes/node/`             | Settings 一键安装的 managed Node.js（yt-dlp JS runtime 用） |
  | `keys/providers.json`（repo-rooted） | AI Provider task routing + 各 Key 存储；不进 user_data，便于 git 选择性 ignore |

---

## 本地化（i18n）

所有用户可见字符串走 [src/i18n.py](../../src/i18n.py) 的 `tr(key)`，locale 表在 `src/i18n/zh.json` 和 `src/i18n/en.json`。factory default 是 `en`（面向开源英文用户），用户可在 File > Preferences 切换。切换语言**需要重启**——Tk 的 Label 文本在创建时就固化，热切换成本远高于重启。详见 [12-i18n.md](12-i18n.md)。
