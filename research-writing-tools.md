# 开源写作工具架构深度研究报告

> 生成日期：2026-05-21
> 目标：提取可复用的设计模式，为自主写作工具架构提供参考

---

## 1. LyX — 结构化文档处理器鼻祖

### 基本信息

| 项目 | 内容 |
|------|------|
| **仓库** | https://codeberg.org/LyX-org/lyx |
| **官网** | https://www.lyx.org |
| **语言** | C++ (Qt) |
| **许可证** | GPLv2+ |
| **最新版** | LyX 2.5.1 (2026-04-23) |
| **核心范式** | WYSIWYM（所见即所得的意义，非外观） |

### 核心架构：Model-View-Control

LyX 采用严格的 MVC 模式，这是它最值得借鉴的设计决策。

```
┌──────────────────────────────────────────────────────┐
│                      LyXView (Window)                 │
│  ┌──────────────────────────────────────────────────┐ │
│  │              WorkArea (View)                     │ │
│  │  ┌────────────────────────────────────────────┐  │ │
│  │  │           BufferView (Controller)          │  │ │
│  │  │  ┌──────────────────────────────────────┐  │  │ │
│  │  │  │        Buffer (Model)                │  │  │ │
│  │  │  │  ┌────────────────────────────────┐  │  │  │ │
│  │  │  │  │  ParagraphList                 │  │  │  │ │
│  │  │  │  │  ├─ Paragraph (ID, layout)     │  │  │  │ │
│  │  │  │  │  │   ├─ Inset (math, table,    │  │  │  │ │
│  │  │  │  │  │   │   image, ref...)        │  │  │  │ │
│  │  │  │  │  │   └─ Font/Color/Language    │  │  │  │ │
│  │  │  │  │  ├─ Paragraph                  │  │  │  │ │
│  │  │  │  │  └─ Paragraph                  │  │  │  │ │
│  │  │  │  └────────────────────────────────┘  │  │  │ │
│  │  │  └──────────────────────────────────────┘  │  │ │
│  │  └────────────────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

#### Layer 详解

| 层 | 类 | 职责 |
|----|-----|------|
| **Model** | `Buffer` | 文档的纯内存表示。持有一个 `ParagraphList`（双向链表），每个 Paragraph 有唯一 ID、布局类型、字体/语言信息 |
| **Controller** | `BufferView` | 将 Buffer 的一部分转换为绘制指令。持有一个 Cursor（光标位置书签），处理键盘/鼠标事件，翻译为 Buffer 操作（insert/delete/select char） |
| **View** | `WorkArea` | 真实的屏幕区域。持有唯一的 BufferView，提供滚动条，管理 Painter 绘制 |
| **Window** | `LyXView` | 完整窗口。含菜单栏、工具栏、TabBar 和 WorkArea |

#### 关键数据模型

**Paragraph（段落）** — 文档的最小结构单元
- 唯一 ID（`getParFromID()` 检索用）
- 布局类型（标题、正文、列表等）
- 字体属性（多个 font 区间）
- 颜色 / 语言 / 间距
- 嵌套的 Inset 列表

**Inset（嵌入物）** — 段落内部的特殊对象
- 数学公式（`mathed/` 目录中的独立编辑器）
- 表格、图片、脚注、尾注
- 交叉引用、BibTeX 引用
- 每个 Inset 有自己的绘制行为

**Layout 文件（.layout）** — 文档样式定义（无需编译的声明式配置）
```latex
Style Section
    Category          Sectioning
    LatexType         Command
    LatexName         section
    LabelString       "\thesection."
    LabelFont
      Series          Bold
    EndFont
    ...
End
```

#### 调度机制：LFUN（LyX Function）

所有用户操作都通过 `dispatch(FuncRequest)` 路由，而非直接调用方法。
- `FuncRequest` 封装命令名 + 参数
- `getStatus()` 预判能否执行
- `DispatchResult` 返回完成状态

这使得撤销/重做、宏录制、脚本自动化成为可能。

#### 文件格式

```
.lyx 文件 (类 XML)
    ↓
Lexer 解析 (lib/ 中的布局定义)
    ↓
Buffer::readDocument()
    ↓
ParagraphList 填充
    ↓
BufferView 渲染
```

导出流程：
```
Buffer → write() → .lyx 文件 → LaTeX → PDF/dvi/ps
                          ↘ 直接导出 (HTML, plaintext, DocBook)
```

#### 源文件结构

```
src/
├── Buffer.h / Buffer.cpp         ← 文档模型（核心）
├── BufferView.h / BufferView.cpp ← 控制器
├── Paragraph.h / Paragraph.cpp   ← 段落数据结构
├── Inset.h / Inset*.cpp          ← 各类 Inset
├── Painter.h / Painter.cpp       ← 绘制接口
├── FuncRequest.h / FuncRequest.cpp ← LFUN 调度
├── frontends/
│   └── qt4/ / qt5/               ← 前端 GUI 实现
├── mathed/                        ← 数学公式编辑器
├── layout/                        ← .layout 文件
├── lib/                           ← 脚本/示例/文档模板
└── lyxrc.*                        ← 配置系统
```

### 可借鉴的设计模式

| 模式 | 说明 | 引用优先级 |
|------|------|-----------|
| **Buffer+BufferView 分离** | 文档数据和渲染逻辑完全解耦，一个 Buffer 可被多个 View 引用 | ★★★★★ |
| **Inset 体系** | 段落内可嵌套任意类型的特殊对象（公式/引用/图片），各自有独立的绘制和编辑行为 | ★★★★ |
| **LFUN 调度中心** | 所有操作统一经 dispatch 路由，天然支持撤销/重做和脚本自动化 | ★★★★ |
| **Layout 文件声明式配置** | 文档样式由纯文本 .layout 文件定义，无需重新编译 | ★★★★ |
| **ParagraphList 双向链表** | 段落间链接稳定，插入/删除不影响已有 ID 引用 | ★★★ |
| **WYSIWYM 核心理念** | 用户只关注内容的结构含义，而非视觉排版 | ★★★★★ |

---

## 2. NovelWriter — 长篇小说创作工具

### 基本信息

| 项目 | 内容 |
|------|------|
| **仓库** | https://github.com/vkbo/novelWriter |
| **官网** | https://novelwriter.io |
| **文档** | https://docs.novelwriter.io |
| **语言** | Python 3 (PyQt6) |
| **许可证** | GPLv3 |
| **Stars** | ~2.9k |
| **核心设计哲学** | 纯文本存储，人类可读，适合版本控制 |

### 核心架构

```
novelwriter/
├── __init__.py
├── common.py            ← 通用工具函数
├── config.py            ← 用户配置
├── constants.py         ← 常量/标签/样式定义
├── enum.py              ← 枚举类型系统（核心）
├── error.py             ← 错误处理
├── guimain.py           ← 主 GUI 入口
├── shared.py            ← 全局共享状态
├── types.py             ← 类型别名
├── core/                ← 核心数据层
│   ├── project.py       ← NWProject（项目主类）
│   ├── projectdata.py   ← NWProjectData（项目设置）
│   ├── projectxml.py    ← .nwproject XML 读写
│   ├── item.py          ← NWItem（单个条目的数据类）
│   ├── itemmodel.py     ← 树形条目模型（Qt 模型）
│   ├── novelmodel.py    ← 小说结构视图模型
│   ├── tree.py          ← NWTree（条目树容器）
│   ├── index.py         ← Index（文本索引引擎）
│   ├── indexdata.py     ← Index 数据结构
│   ├── document.py      ← 文档 I/O
│   ├── storage.py       ← NWStorage（存储抽象层）
│   ├── status.py        ← 状态/重要性图标管理
│   ├── spellcheck.py    ← 拼写检查
│   ├── sessions.py      ← 创作会话记录
│   ├── options.py       ← 项目级 GUI 选项
│   ├── buildsettings.py ← 导出构建设置
│   ├── docbuild.py      ← 文档编译/导出引擎
│   └── coretools.py     ← 核心工具函数
├── text/                ← 文本处理层
│   ├── counting.py      ← 字数/段落统计
│   ├── formats.py       ← 标记格式定义
│   └── patterns.py      ← 正则表达式匹配
├── formats/             ← 导出格式
│   ├── tokenizer.py     ← 标记化引擎（核心）
│   ├── tohtml.py        ← HTML 导出
│   ├── tomarkdown.py    ← Markdown 导出
│   ├── toodt.py         ← OpenDocument 导出
│   ├── todocx.py        ← Word DOCX 导出
│   ├── toqdoc.py        ← Qt 富文本渲染
│   └── toraw.py         ← 纯文本导出
├── gui/                 ← GUI 视图层
├── dialogs/             ← 对话框
├── tools/               ← 工具组件
└── extensions/          ← 扩展
```

### 枚举类型系统（核心设计亮点）

NovelWriter 设计了一套精确的枚举体系来规范所有数据结构：

```python
# 条目类型：树形结构的三层
nwItemType: NO_TYPE → ROOT → FOLDER → FILE

# 条目类别：ROOT 级别区分
nwItemClass: NOVEL, PLOT, CHARACTER, WORLD, TIMELINE, OBJECT,
             ENTITY, CUSTOM, ARCHIVE, TEMPLATE, TRASH

# 条目布局：FILE 级别区分
nwItemLayout: DOCUMENT, NOTE
```

意思是：
- **ROOT** = 根节点（小说、角色、世界...各一个根）
- **FOLDER** = 文件夹（小说下的"第一卷"、"第二卷"...）
- **FILE** = 实际文件（每章/每场景一个文件），布局分 DOCUMENT（正文）和 NOTE（笔记）

### 项目文件格式

```
project.nwproject       ← XML 项目元数据（条目树、设置）
content/
├── 1234567890.nwd      ← 每个文档一个文件（纯文本 + 元数据头）
├── abcdef1234.nwd
└── ...
```

**.nwd 文件内容示例：**
```markdown
# 第一章: 起风了

这是一段正文。

@synopsis: 主角在这个场景中首次感受到异常。

@pov: 沈默
@focus: 李薇
@plot: 主线/调查
```

**.nwproject (XML) 核心结构：**
```xml
<novelWriterXML projectVersion="1.2">
  <project>
    <name>...</name>
    <author>...</author>
    <sessions>...</sessions>
  </project>
  <items>
    <item handle="..." parent="..." root="..." order="0"
          type="ROOT" class="NOVEL" layout="NO_LAYOUT">
      <itemname>小说标题</itemname>
    </item>
    <item handle="..." parent="..." root="..." order="1"
          type="FILE" class="NOVEL" layout="DOCUMENT">
      <itemname>第一章</itemname>
    </item>
  </items>
</novelWriterXML>
```

### 文本标记化引擎（Tokenizer）

这是 NovelWriter 导出架构的核心设计：

```
.nwd (原始文本)
    │
    ▼
Tokenizer (patterns.py + formats.py)
    │  解析 @pov:、@plot:、@synopsis: 等元数据标签
    │  解析 # ## ### 标题层级
    │  解析 **粗体**、*斜体*、~~删除线~~、==标记==
    │
    ▼
Token 流 (列表，每个 Token 有类型、文本、元数据)
    │
    ├─► tohtml.py   → HTML
    ├─► tomarkdown.py → Markdown
    ├─► toodt.py    → OpenDocument
    ├─► todocx.py   → Word DOCX
    └─► toqdoc.py   → Qt 富文本 (编辑器渲染)
```

Token 类型包括：TITLE, HEADING, TEXT, EMPTY, SEPARATOR, SKIP, COMMENTS, KEYWORDS, ALIGN, WRAP, PAGE, META 等。

### 索引系统（Index）

NWProject 内的 `Index` 类是一个关键设计：
- 扫描全文提取标题层级
- 记录每个标题的 POV/Focus/Plot 标签
- 构建小说结构视图（NovelModel）
- 支持章节粒度的字数统计和标签过滤

```
Index.scanText(handle, text)
    → 解析标题标记 # ## ### ####
    → 提取 @pov @focus @plot @synopsis
    → 建立 IndexNode (handle → [Heading1, Heading2, ...])
    → NovelModel 从 Index 读取数据，管理小说大纲视图
```

### NovelView / OutlineView 的多视图架构

```
同一份数据（NWTree + Index）
    │
    ├─► NovelModel (QAbstractTableModel) — 章节列表视图
    │   列：标题 | 字数 | POV标签 | 更多箭头
    │
    └─► OutlineModel — 全量大纲视图
        列：标题 | 层级 | 标签 | 状态 | 字数 | POV | Focus | Plot | 时间 | 世界 ...
```

### 可借鉴的设计模式

| 模式 | 说明 | 引用优先级 |
|------|------|-----------|
| **枚举类型系统** | nwItemType/nwItemClass/nwItemLayout 三层次枚举，数据合法性由类型系统担保 | ★★★★★ |
| **Token 化导出架构** | 原始文本 → Token 流 → 多格式输出，每一层职责清晰，易于扩展新格式 | ★★★★★ |
| **树形条目模型 + 索引系统** | NWTree 管理条目层级，Index 单独管理文本内容索引，数据与视图松耦合 | ★★★★ |
| **纯文本 + 元数据存储** | 每个文件都是人类可读的纯文本，元数据用 @key: value 语法嵌入，适合 Git 版本管理 | ★★★★ |
| **NWItem 的 pack/unpack 模式** | 数据序列化与反序列化统一，支持复制（duplicate）和跨版本兼容 | ★★★★ |
| **存储抽象层（NWStorage）** | 文件 I/O 统一通过 storage 层，项目锁、读写分离、文档管理集中处理 | ★★★ |
| **会话记录（NWSessionLog）** | 记录每次打开的编辑时长，用于统计总创作时间 | ★★ |
| **状态/重要性图标系统** | 用不同形状和颜色表示项目状态和优先级，可视化进度 | ★★★ |

---

## 3. Manuskript — 开源写作工作台

### 基本信息

| 项目 | 内容 |
|------|------|
| **仓库** | https://github.com/olivierkes/manuskript |
| **官网** | https://www.theologeek.ch/manuskript/ |
| **语言** | Python 3 (PyQt5) |
| **许可证** | GPLv3 |
| **Stars** | ~2.3k |
| **分支** | develop（开发主分支） |
| **核心设计哲学** | 开放纯文本格式，支持第三方协作和版本控制 |

### 核心架构

```
manuskript/
├── __init__.py
├── main.py                ← 应用入口
├── mainWindow.py          ← 主窗口逻辑
├── enums.py               ← 枚举定义（Character, World, Plot, Outline）
├── settings.py            ← 全局设置
├── functions.py           ← 工具函数
├── loadSave.py            ← 外部加载/保存接口
├── logging.py             ← 日志
├── searchLabels.py        ← 搜索标签定义
├── version.py             ← 版本号
├── models/                ← 数据模型层
│   ├── abstractItem.py    ← 树形条目的基类
│   ├── abstractModel.py   ← 树形模型的基类（QAbstractItemModel）
│   ├── outlineItem.py     ← 大纲条目（场景/章节/文件夹）
│   ├── outlineModel.py    ← 大纲模型（核心树形结构）
│   ├── characterModel.py  ← 角色模型
│   ├── characterPOVModel.py ← 角色 POV 模型
│   ├── plotModel.py       ← 情节模型
│   ├── worldModel.py      ← 世界观模型（OPML）
│   ├── flatDataModelWrapper.py ← 扁平数据包装器
│   ├── references.py      ← 引用管理
│   ├── searchableItem.py  ← 可搜索条目 mixin
│   ├── searchableModel.py ← 可搜索模型
│   ├── searchFilter.py    ← 搜索过滤器
│   └── searchResultModel.py ← 搜索结果模型
├── ui/                    ← 界面层
│   ├── mainWindow.py/ui   ← 主窗口
│   ├── editors/           ← 文本编辑器
│   ├── exporters/         ← 导出面板
│   ├── importers/         ← 导入面板
│   ├── views/             ← 视图组件（大纲视图，卡片视图等）
│   ├── tools/             ← 工具窗口
│   └── highlighters/      ← 语法高亮
├── converters/            ← 格式转换
├── exporter/              ← 导出引擎
├── importer/              ← 导入引擎
└── load_save/             ← 文件格式读写
    ├── version_0.py       ← 旧版格式兼容
    └── version_1.py       ← v1 格式（当前主要格式）
```

### 数据模型层级

```
abstractItem（基础：ID + 父子关系 + XML 序列化）
    │
    ├── outlineItem（大纲条目）
    │   枚举列：title, type(folder/md), text, compile, POV,
    │          status, label, wordCount, charCount, goal,
    │          goalPercentage, revisions, customIcon
    │
    └── searchableItem（可搜索 mixin，与 outlineItem 并行继承）

abstractModel（QAbstractItemModel 封装）
    │
    ├── outlineModel（大纲树形模型 - 核心）
    ├── characterModel（角色列表模型）
    ├── plotModel（情节模型）
    └── worldModel（世界观模型）
```

### 文件格式：v1 版的"开放纯文本"设计

Manuskript v1 文件格式的最重要设计决策是 **支持两种保存模式**：

#### 模式 A：单文件 ZIP（.msk）

```
project.msk (zip)
├── MANUSKRIPT           ← 版本标记 "1"
├── infos.txt            ← 书名/作者/系列等元信息（键值对）
├── summary.txt          ← 雪花式摘要（sentence → paragraph → page → full）
├── status.txt           ← 状态定义（名称:颜色）
├── labels.txt           ← 标签定义（名称:颜色）
├── settings.txt         ← 项目设置（JSON 格式）
├── characters/
│   └── {ID}-{name}.txt ← 每个角色一个文件（键值对元数据）
├── outline/
│   ├── {ID}-{name}.txt ← 每个大纲条目一个文件
│   └── ...
├── world.opml           ← 世界观（OPML 格式）
├── plots.xml            ← 情节（XML 格式）
└── revisions.xml        ← 修订历史（可选）
```

#### 模式 B：纯文本文件夹（推荐）

```
project/                ← 项目文件夹（而非 .msk 文件）
├── infos.txt
├── summary.txt
├── status.txt
├── labels.txt
├── settings.txt
├── characters/
│   └── {ID}-{name}.txt
├── outline/
│   └── ...
├── world.opml
└── plots.xml
```

纯文本模式是为 **版本控制友好** 而设计的：每个角色文件独立，每次修改只影响一个文件，diff 清晰可读。

#### 典型字符文件内容

```
Name:             沈默
ID:               abc123
Importance:       主要角色
POV:              true
Motivation:      找到真相
Goal:            揭穿阴谋
Conflict:        身份暴露威胁
Phrase Summary:  一个从地球穿越到泰拉的退役武警
Paragraph Summary: ...
Full Summary:    ...
Color:           #ff4444
```

### 大纲条目（outlineItem）的数据列枚举

```python
class Outline:
    title = 0          # 标题
    type = 1           # 类型（folder/md）
    text = 2           # 正文内容（Markdown）
    compile = 3        # 是否参与编译
    POV = 4            # 视角角色
    status = 5         # 写作状态
    label = 6          # 标签
    wordCount = 7      # 字数
    charCount = 8      # 字符数
    goal = 9           # 写作目标
    goalPercentage = 10 # 目标达成率
    customIcon = 11    # 自定义图标
    revisions = 12     # 修订记录
    setGoal = 13       # 内部目标设定
```

### 雪花式摘要系统

Manuskript 的一个独特功能是支持"雪花法"（Snowflake Method）写作：

```
一句话摘要  (Situation)
    │
    ▼
一句话段落  (Sentence)
    │
    ▼
一段落摘要  (Paragraph)
    │
    ▼
一页摘要    (Page)
    │
    ▼
全文       (Full)
```

每一步都作为 infos.txt 中的一个键值对存储，对应记忆中的 `mdlFlatData` 模型。

### 可借鉴的设计模式

| 模式 | 说明 | 引用优先级 |
|------|------|-----------|
| **双模式存储（ZIP vs 纯文本文件夹）** | 兼顾便携性和版本控制友好性 | ★★★★★ |
| **雪花式摘要层级（5级渐进）** | sentence → paragraph → page → full，适合渐进式创作 | ★★★★ |
| **树形大纲 + 元数据列（outlineItem）** | 每个条目同时持有标题、内容、状态、字数、目标、标签，在大纲视图中一览无余 | ★★★★ |
| **字符文件键值对格式** | 角色/世界等元数据以纯文本键值对存储，易读易改易版本控制 | ★★★★ |
| **Mixin 模式（searchableItem + abstractItem）** | 通过多重继承组合能力，避免深层继承链 | ★★★ |
| **版本化加载（version_0 / version_1）** | load_save 目录按版本号分文件，向前兼容 | ★★★★ |
| **OPML 格式存储世界观** | 使用 OPML（大纲处理标记语言）标准格式存储层级化世界观数据 | ★★★ |
| **写作目标追踪** | 每个条目可设置字数目标，目录自动汇总子条目目标 | ★★★ |
| **Qt Designer .ui 文件 + Python 代码分离** | UI 布局用 .ui 文件设计，逻辑在 .py 中，职责清晰 | ★★ |
| **缓存加速（save时文件内容比对）** | save 时比较文件哈希，只写有变化的文件，减少磁盘 I/O | ★★ |

---

## 4. 跨工具对比：关键设计维度

| 维度 | LyX | NovelWriter | Manuskript |
|------|-----|-------------|------------|
| **核心语言** | C++ | Python | Python |
| **UI 框架** | Qt (C++) | PyQt6 | PyQt5 |
| **数据模型** | Buffer + ParagraphList | NWTree + NWItem | TreeModel + outlineItem |
| **文件格式** | .lyx (类 XML) | .nwproject XML + .nwd 文本 | .msk (ZIP) / 纯文本文件夹 |
| **内容标记** | LaTeX 语义 | 精简 Markdown + 元数据语法 | Markdown |
| **导出架构** | LaTeX → PDF | Tokenizer → 多种格式 | Pandoc + 内置转换器 |
| **项目层级** | 文档 ↔ 章节 ↔ 段落 | ROOT ↔ FOLDER ↔ FILE | Folder ↔ Text (无限嵌套) |
| **元数据关联** | BibTeX 引用 | @pov @plot @focus 标签 | 状态/标签/角色关联 |
| **版本控制友好** | 中等 (XML diff) | 优秀 (纯文本) | 优秀 (纯文本文件夹模式) |
| **撤销系统** | LFUN dispatch + Undo | Qt Undo Framework | 基础修订历史 |
| **关注分离** | Buffer/View 严格分离 | Core/GUI/Format 三层 | Model/UI 分离 |
| **字数统计** | 无内置 | 精确，标题级别 | 树形递归汇总 |
| **写作目标** | 无 | 统计展示 | 逐层可设目标 |
| **学习曲线** | 高 (LaTeX 概念) | 低 (Markdown 类) | 中 |

---

## 5. 优先级建议：最值得复用的设计模式

### 第一梯队（必须纳入）

1. **枚举类型系统**（NovelWriter） — nwItemType + nwItemClass + nwItemLayout 三层次约束，从类型层面杜绝非法数据组合。这是所有数据结构的基础设施。

2. **Token 化导出架构**（NovelWriter） — 原始文本 → Token 流 → 多格式输出。每层只做一件事，扩展新导出格式只需新增一个 consumer。

3. **存储抽象层 + 双模式**（Manuskript） — 单文件 ZIP 便携，纯文本文件夹适合 Git。save 时做缓存比较只写变化文件。

4. **Buffer+BufferView 分离**（LyX） — 数据和渲染彻底解耦，一个模型可被多视图消费。这对任何编辑器架构都是基础。

### 第二梯队（强烈推荐）

5. **树形条目 + 索引系统分离**（NovelWriter） — 树管理层级结构，索引管理内容元数据，互不干扰。

6. **雪花式摘要 5 级渐进**（Manuskript） — 适合长篇创作的从一句话到全文的渐进展开。

7. **Inset 体系**（LyX） — 段落内可嵌套任意特殊对象，每类 Inset 自解释绘制和编辑行为。

8. **LFUN 调度中心**（LyX） — 所有操作统一路由，天然支持撤销/重做/宏录制。

### 第三梯队（按需采纳）

9. **角色/世界/情节分离模型**（Manuskript + NovelWriter） — 各自独立的模型类管理不同类型的元数据。

10. **写作目标递归汇总**（Manuskript） — 子条目目标自动汇总到父目录，进度一目了然。

11. **会话记录**（NovelWriter） — 记录每次编辑会话的时长，用于统计总创作时间。

12. **状态/标签可视化系统**（NovelWriter + Manuskript） — 用颜色和图标表示不同写作阶段。

---

## 6. 来源索引

- LyX 架构文档：https://wiki.lyx.org/Devel/NotesOnModelViewControl
- LyX 源代码探索：https://wiki.lyx.org/Devel/SourceCodeExploration
- LyX 文件格式：https://wiki.lyx.org/Devel/LyXFileFormat
- LyX Files in Trunk：https://wiki.lyx.org/Devel/FilesInTrunk
- LyX 开发页面：https://www.lyx.org/Development
- NovelWriter GitHub：https://github.com/vkbo/novelWriter
- NovelWriter enum.py：https://github.com/vkbo/novelWriter/blob/main/novelwriter/enum.py
- NovelWriter core/item.py：https://github.com/vkbo/novelWriter/blob/main/novelwriter/core/item.py
- NovelWriter core/project.py：https://github.com/vkbo/novelWriter/blob/main/novelwriter/core/project.py
- NovelWriter core/novelmodel.py：https://github.com/vkbo/novelWriter/blob/main/novelwriter/core/novelmodel.py
- Manuskript GitHub：https://github.com/olivierkes/manuskript
- Manuskript 文件格式 v1：https://github.com/olivierkes/manuskript/blob/develop/manuskript/load_save/version_1.py
- Manuskript outlineItem：https://github.com/olivierkes/manuskript/blob/develop/manuskript/models/outlineItem.py
- Manuskript Wiki：https://github.com/olivierkes/manuskript/wiki
