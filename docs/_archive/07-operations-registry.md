# Operation Registry 设计：文件类型 → 右键操作映射

## 文件：`src/operations.py`

## 设计目标

将"哪类文件支持哪些操作"集中注册，Sidebar 右键菜单根据文件扩展名动态生成，
新增操作只需在 Registry 加一行，无需修改 UI 代码。

## Operation 数据结构

```python
@dataclass
class Operation:
    label: str           # 菜单显示文字
    handler: str         # "quick" | "tool" | "common"
    file_types: list     # 扩展名列表，["*"] 表示全部文件
    func: Callable       # quick/common：core 函数引用
    tool_key: str        # tool：TOOL_MAP 中的 key
    separator_before: bool = False  # 在此项前加分隔线
```

## handler 类型说明

| handler | 行为 |
|---------|------|
| `quick` | 后台线程执行 core 函数，进度显示在状态栏，完成后 Sidebar 自动刷新 |
| `tool`  | 打开对应工具的 Toplevel 窗口（未来支持 prefill_path 预填路径） |
| `common`| 同 quick，适用于"显示在资源管理器"等通用操作 |

## 当前注册的操作

| 文件类型 | 操作 | handler |
|---------|------|---------|
| .mp4 .mkv .avi .mov | 提取 MP3 | quick → video_ops.extract_mp3 |
| .mp4 .mkv .avi .mov .mp3 .wav | 语音转字幕... | tool → speech2text |
| .mp4 .mkv .avi .mov | 烧录字幕... | tool → subtitle |
| .mp4 .mkv .avi .mov | 视频分段... | tool → splitvideo |
| .srt | 提取纯文本 (.txt) | quick → srt_ops.extract_text |
| .srt | 翻译字幕... | tool → translate |
| .srt | 烧录到视频... | tool → subtitle |
| .mp3 .wav .aac .m4a | 语音转字幕... | tool → speech2text |
| * (全部) | 在资源管理器中显示 | common |
| * (全部) | 复制文件路径 | common |

## Sidebar 右键菜单调用流程

```
用户右键点击文件
  → _on_tree_right_click(event)
  → get_operations(file_path)        # 按扩展名过滤
  → 构建 tk.Menu
  → 用户点击菜单项
  → _run_operation(op, file_path)
      ├── quick/common → _run_quick() → threading.Thread → core 函数
      └── tool         → open_tool(key)  → Toplevel 窗口
```

## 扩展方式

新增一个操作只需在 `REGISTRY` 列表加一行：

```python
Operation("生成标题...", "quick", [".srt"],
          func=srt_ops.generate_titles),
```
