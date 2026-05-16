# ADR-0005: Project 数据层全面插件化 + 组件化

- **状态**: Active
- **决定日期**: 2026-05-16
- **取代**: 单源 project 假设（隐式协议，无 ADR 记录）

## 决定

Project 数据布局重构为对称的双插件容器：

```
<project>/
  .videocraft/project.json          ← 项目元数据（schema_version, name, created_at）
  materials/
    news_video/                     ← 素材类型 = MaterialType.type_name
      news-1/                       ← 素材实例
        instance.json               ← 实例元数据 + 槽位状态摘要
        source/video.mp4
        source/meta.json
        source/basic_info.json
        source/context.json
        subtitles/
          zh.srt
          <iso>.analysis.json
          <iso>.transcript.md
          <iso>.hotclips.json
      news-2/                       ← 第二个实例，结构同上
        ...
  creations/                        ← 重命名自 derivatives/
    news_desk/                      ← 创作类型 = CreationType.type_name
      default/                      ← 创作实例
        config.json                 ← 包含 bound_material: {type, instance}
        output.mp4
        publish.md
        ...
```

**核心改变**：
1. **素材跟创作目录对称**：`materials/<type>/<instance>/` ≡ `creations/<type>/<instance>/`
2. **数据归属插件 + 实例**：所有 source / subtitles / analysis 路径都在某个素材实例内，不再是 project 直接子目录
3. **创作显式绑定素材实例**：`creations/<type>/<instance>/config.json` 内 `bound_material: {type: "news_video", instance: "news-1"}` 字段。绑定即记录，记录即审计
4. **N 个素材实例可并存**：一个 project 内可有 N 个 news_video 实例（不同源视频 / 不同主题）
5. **N 个创作可绑定同一素材**（1:N）；一个创作绑定 1 个素材（按 ADR-0003 快照保护后续解耦）

## 为什么

### 触发痛点

ADR-0004 把 plugin 架构立起来后暴露了：

- `Project.source_dir` / `Project.subtitles_dir` 是 project 直接子目录 → 单源假设硬编码
- 但 ADR-0004 的素材插件本意是 type-extensible，"新闻视频" 仅是当前唯一 type；type-extensible 必然意味着 instance-multiple
- 现有 sidebar 实现尝试在单源假设下塞插件抽象 → 整个面板只能渲染一个隐式实例（or none）→ 跟"组件库"的 mental model 直接打架
- 创作（derivative）侧已经是 `derivatives/<type>/<instance>/` 多实例形态——素材侧不对称，造成认知不一致

### 为什么不向后兼容

- pre-alpha，无 release、无用户（[[feedback_pre_alpha_no_legacy]]）
- 兼容老布局会强迫 Project 同时支持"扁平单源"和"嵌套多实例"两套路径解析逻辑——代码毒
- 现在彻底切干净，未来零债

### 为什么创作不"自动派生"素材而是"显式选择"

按 ADR-0003 派生快照原则：
- 创作创建时**不绑定**素材（创作可以是空白工作台，先打开后选素材）
- 进入工作台后用户**显式选择**一个素材实例 → 这一刻产生 `bound_material` 记录
- 选择后所有创作内的素材访问都走该实例（snapshot 拉过来到自己 instance dir）
- 重新选素材 = 重新选择 + 重新快照（覆盖本地）+ 警告本地编辑会丢

绑定关系 1:N（一个素材可被多个创作消费）；反向 N:1（一个创作只绑一个素材）。

## 如何应用

### Project API 变化

```python
class Project:
    @property
    def materials_dir(self) -> str:
        return os.path.join(self.folder, "materials")
    
    @property
    def creations_dir(self) -> str:
        return os.path.join(self.folder, "creations")   # 重命名自 derivatives_dir
    
    # ── Material instance ops（对应 derivative 的对应方法）──
    def material_type_dir(self, type_name: str) -> str:
        return os.path.join(self.materials_dir, type_name)
    
    def material_instance_dir(self, type_name: str, instance_name: str) -> str:
        return os.path.join(self.materials_dir, type_name, instance_name)
    
    def list_material_types(self) -> list[str]: ...
    def list_material_instances(self, type_name: str) -> list[str]: ...
    def create_material_instance(self, type_name: str, instance_name: str, *,
                                  initial_config: dict | None = None) -> str: ...
    
    # ── Creation instance ops（保留现有 API，目录名 derivatives -> creations）──
    # 现有 derivative_dir / list_derivatives / create_derivative_instance 改名
    # 为 creation_*；行为不变
    
    # ── 移除（破坏性）──
    # source_dir          → 改由 material_instance_dir(...) + /source 构造
    # source_video_path   → 移到 MaterialInstance / NewsVideoModel
    # source_meta_path    → 同上
    # subtitles_dir       → 同上
    # source_status()     → 移到 NewsVideoModel.has_source_video()
```

### MaterialType 契约扩展（slices F + L）

```python
@dataclass(frozen=True)
class MaterialType:
    type_name: str
    display_name_key: str
    icon: str | None
    description_zh: str
    description_en: str
    # 注册器：构造一个新 instance，返回 instance_id
    create_instance: Callable[[Project, str | None], str]   
    # 实例工厂：从 (project, instance_id) 构造 model 对象
    instance_factory: Callable[[Project, str], "MaterialInstanceModel"]
    # UI 渲染器：给一个 model + parent frame，画 sidebar panel
    sidebar_renderer: Callable[[Frame, "MaterialInstanceModel", Hub], "Panel"]
    # 实例命名建议（auto-increment）
    suggest_instance_name: Callable[[list[str]], str]   
```

注意：`has_instance` 字段不再需要——直接调 `project.list_material_instances(type_name)` 看是否非空。`artifact_resolver` 移到 instance_factory 返回的 model 对象上：`model.get_artifact(key) -> Path`。

### MaterialInstanceModel 协议

每个素材类型的 model 类必须实现：

```python
class MaterialInstanceModel(Protocol):
    project: Project
    instance_id: str
    instance_dir: str
    
    # 状态查询
    def slot_readiness(self) -> dict[str, SlotState]: ...
    def is_empty(self) -> bool: ...
    
    # 标准化 artifact 读取（给创作插件用）
    def get_artifact(self, key: str) -> Path | None: ...
    
    # 变更通知
    def subscribe(self, callback: Callable[[], None]) -> None: ...
```

具体 schema、业务方法由每种素材类型自定义（NewsVideoModel 有 add_source_video / generate_subtitles / ai_fill_context 等；其他素材类型有自己的）。

### Sidebar 渲染流程

Hub `_populate_materials_body` 变为：

```python
for mt in materials.all_types():
    for inst_id in self.project.list_material_instances(mt.type_name):
        model = mt.instance_factory(self.project, inst_id)
        panel_frame = tk.Frame(self._materials_body, ...)
        mt.sidebar_renderer(panel_frame, model, self)
```

- 0 个实例时整个 body 显示空状态 hint
- N 个实例时 N 个 panel 垂直堆叠，每 panel 显示其 instance 的实例树

### Material 实例的元数据

每个素材实例目录下有一个 `instance.json`（轻量元数据 + 槽位完成情况摘要，方便不打开整个目录就知道状态）：

```json
{
  "schema_version": 1,
  "type_name": "news_video",
  "instance_name": "news-1",
  "created_at": "2026-05-16T...",
  "display_name": "拜登访谈第三集",     // 用户可改，默认 = instance_name
  "summary": {
    "source_filled": true,
    "context_filled": 7,
    "subtitles": ["zh", "en"]
  }
}
```

### 创作绑定素材：config.json 字段

```json
{
  "schema_version": 1,
  "type_name": "news_desk",
  "instance_name": "default",
  "bound_material": {
    "type_name": "news_video",
    "instance_name": "news-1",
    "bound_at": "2026-05-16T..."
  },
  "components": [...]
}
```

`bound_material` 缺省 = 工作台未绑定状态，进入时强制弹素材选择器。

### Creation 内部仍按 ADR-0003 快照

创作 instance 不直接读 `materials/news_video/news-1/subtitles/zh.srt`——按 ADR-0003，导入时复制到自己的 `creations/news_desk/default/subtitles/<comp_id>.srt`。`bound_material` 只是审计 + 重新选素材的入口，不是运行时引用。

### MaterialInstance.get_artifact() 用作选材桥

创作工作台从绑定的素材取数据时调：

```python
material = materials.get(bound.type_name).instance_factory(project, bound.instance_name)
srt_path = material.get_artifact("subtitle:zh")        # → materials/news_video/news-1/subtitles/zh.srt
shutil.copy2(srt_path, creation_instance_dir / "subtitles" / "<comp_id>.srt")  # 快照入 creation
```

`get_artifact` 的 key namespace 归素材类型 schema 定义（详见 NewsVideoModel.get_artifact 的 docstring）。

## 迁移路径

**无迁移**。pre-alpha。删 `<project>` 目录从头建。

## 实施 slice 拆分

| Slice | 内容 |
|---|---|
| **L** | 本 ADR + task.md（仅文档） |
| **M** | Project 目录结构重构：`materials/<type>/<inst>/` + `creations/<type>/<inst>/` 重命名；移除 `source_dir` / `subtitles_dir` / `source_status` 等；新增 material instance 管理 API |
| **N** | `materials/news_video/model.py` 的 `NewsVideoModel` 类：构造 (project, instance_id)；汇聚 source/context/subtitles/analysis；零 Tk；business actions |
| **O** | `materials/news_video/sidebar.py` 重写：`MaterialSlot` 抽象 + 统一槽位渲染；不再 3 个独立 section |
| **P** | Hub 多实例渲染：list_material_instances 驱动 N panel；[+] 创建实例 = `mt.create_instance(project)`；实例重命名 / 删除右键菜单 |
| **Q** | 创作工作台绑定素材：`bound_material` 字段；首次开工作台弹素材实例选择器；所有创作内素材路径走 `material.get_artifact()` |

## 不在本 ADR 范围

- 第二种素材类型（普通视频 / 访谈视频）的 schema 设计——按 ADR-0004 等真需要时再做
- 素材实例之间的关系建模（比如"这个 news-2 是 news-1 的延伸"）——暂不支持
- 跨 project 共享素材库——单 project 隔离
- 创作绑定到多个素材的需求——按 1:1 实施，N:1 复议要等真出现需求
