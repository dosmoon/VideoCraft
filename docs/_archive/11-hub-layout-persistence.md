# 11 — Hub 窗口布局持久化

## 动机

之前每次启动 Hub 都硬编码最大化 + 固定 sidebar 宽度 + 固定日志面板高度，用户调整过的布局在关闭后完全丢失。不同屏幕/不同工作场景下用户想要不同的布局（例如低分辨率屏想把日志面板拉高，高分辨率屏想把 sidebar 拉宽），应该保存并自动恢复。

## 文件

[src/hub_layout.py](../../src/hub_layout.py)，约 60 行纯逻辑，无 tkinter 依赖，便于单元测试。

## 存储位置

`~/.videocraft/layout.json`，与 `recent.json` / `settings.json` / `presets/` 并列在用户目录的 `.videocraft/` 下。

## JSON Schema

```json
{
  "geometry":      "1413x800+139+44",
  "zoomed":        true,
  "sidebar_width": 320,
  "log_height":    90
}
```

| 字段 | 类型 | 含义 |
|------|------|------|
| `geometry`      | str  | Tk wm_geometry 格式 `WxH+X+Y`（**normal 状态**下的几何，不是 zoomed 后的全屏大小） |
| `zoomed`        | bool | 关闭时窗口是否处于 zoomed（最大化）状态 |
| `sidebar_width` | int  | 水平 PanedWindow 的 sash 位置（左侧 sidebar 宽度，像素） |
| `log_height`    | int  | 底部日志面板高度（像素） |

缺省值见 [hub_layout.py](../../src/hub_layout.py) 的 `DEFAULT_LAYOUT`：`1280x800 / zoomed=True / sidebar 320 / log 90`。

## API

```python
def load_layout() -> dict
# 读文件，缺失或损坏都返回 DEFAULT_LAYOUT 的副本；缺 key 自动补

def save_layout(layout: dict) -> None
# 创建父目录并写 JSON；只保留已知 key，丢弃未知字段避免文件漂移
```

## 加载/保存时机

**加载**（`VideoCraftHub.__init__`）：
1. 构造 Hub 前 `hub_layout.load_layout()` 读文件
2. `self.root.geometry(layout['geometry'])` 应用 normal 尺寸
3. `_build_layout()` 创建 PanedWindow 和所有 widget
4. `self.root.after(50, self._apply_saved_layout)` 延迟 50ms 应用 sash 位置——必须等 widget 实际渲染后 `winfo_height()` 才是真实值
5. `_apply_saved_layout` 里：设 sidebar sash、设 log panel sash、最后再 `self.root.state("zoomed")` 如果需要

**保存**（`VideoCraftHub._on_close` 绑定 `WM_DELETE_WINDOW`）：
1. 记录当前是否 zoomed
2. 如果是 zoomed，先切回 normal 拿真实 geometry（zoomed 下 geometry 返回的是屏幕尺寸，不是用户的自定义）
3. 读 `sidebar_width = self._pane.sashpos(0)` 和 `log_height = win_h - self._vpane.sashpos(0)`
4. **clamp log_height**：限制在 `[60, win_h // 2]` 之间，避免极端拖拽（例如日志面板被拉到 500+ 像素）导致下次启动工具区被压缩，主操作按钮被挤出可视区
5. `hub_layout.save_layout(payload)`
6. `self.root.destroy()`

## 故障恢复

- 文件不存在 → 返回 DEFAULT_LAYOUT，无感知
- JSON 损坏 / 不是 dict → 返回 DEFAULT_LAYOUT，无感知
- 文件里缺某个字段 → 用 DEFAULT_LAYOUT 的对应值补齐
- 文件里有未知字段 → 保存时丢弃，不回写（防止其他工具污染）
- sashpos 设置失败（widget 未就绪等）→ `_apply_saved_layout` 里的 try/except 记 log 不崩

## 与 recent.json / settings.json / presets/ 的关系

| 文件 | 语义 | 改动频率 |
|------|------|---------|
| `layout.json` | **UI 尺寸/位置**状态 | 每次关闭 Hub |
| `recent.json` | **最近打开的工程**列表 | 每次 `open_folder` |
| `settings.json` | **用户偏好**（目前只有 language，未来扩展） | 用户在 Preferences 里主动保存时 |
| `presets/*.json` | **工具级**命名参数预设 | 用户在工具里主动保存时 |

各自职责独立，互不耦合。添加新的持久化需求时优先判断属于哪一类，不要混到同一个文件。
