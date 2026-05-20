# 写作工具技术架构研究报告

> 生成日期：2026-05-21
> 研究范围：Zettlr、Notable、Obsidian、Vela、Bloomverse

---

## 目录

1. [Zettlr — 文件系统即数据库](#1-zettlr--文件系统即数据库)
2. [Notable — 极简本地存储](#2-notable--极简本地存储)
3. [Obsidian — 插件生态与图结构](#3-obsidian--插件生态与图结构)
4. [Vela 与 Bloomverse — 未找到有效源](#4-vela-与-bloomverse--未找到有效源)
5. [可复用架构模式总结](#5-可复用架构模式总结)

---

## 1. Zettlr — 文件系统即数据库

### 1.1 基本信息

| 条目 | 内容 |
|------|------|
| 技术栈 | Electron + Vue 3 (Pinia) + CodeMirror 6 + TypeScript |
| 许可证 | GNU GPL v3 |
| 源码 | https://github.com/Zettlr/Zettlr |
| 架构模式 | Service Provider + FSAL (File System Abstraction Layer) |

### 1.2 目录结构

```
source/
├── main.ts                       # 入口
├── app/
│   ├── app-service-container.ts  # 服务容器（依赖管理）
│   ├── lifecycle.ts              # 应用生命周期
│   └── service-providers/        # 所有服务提供者
│       ├── fsal/                 # 文件系统抽象层（核心）
│       ├── documents/            # 文档管理器
│       ├── tags/                 # 标签系统
│       ├── config/               # 配置管理
│       ├── commands/             # 命令系统
│       ├── assets/               # 资源管理
│       ├── citeproc/             # 引文处理
│       ├── links/                # 内部链接
│       ├── windows/              # 窗口管理
│       ├── menu/                 # 菜单管理
│       ├── updates/              # 更新
│       ├── stats/                # 统计
│       ├── log/                  # 日志
│       ├── dictionary/           # 拼写检查
│       ├── appearance/           # 外观主题
│       ├── css/                  # CSS 管理
│       ├── targets/              # 写作目标
│       ├── tray/                 # 系统托盘
│       ├── recent-docs/          # 最近文档
│       ├── long-running-tasks/   # 长耗时任务
│       └── cli-provider.ts       # CLI 支持
├── common/
│   ├── modules/                  # 通用模块
│   │   ├── markdown-editor/      # CodeMirror 封装
│   │   ├── markdown-utils/       # Markdown 解析工具
│   │   ├── persistent-data-container/ # 持久化数据容器
│   │   ├── preload/              # Electron preload
│   │   └── window-register/      # 窗口注册
│   ├── util/                     # 通用工具
│   ├── vue/                      # 共享 Vue 组件
│   ├── i18n-main.ts / i18n-renderer.ts  # 国际化
│   └── regular-expressions.ts    # 正则表达式常量
├── pinia/                        # Vue 状态管理
└── win-*/                        # 各窗口独立入口
```

### 1.3 FSAL — 文件系统抽象层（核心架构）

FSAL 是整个应用的核心抽象。它将文件系统视为一个"数据库"，提供统一的 CRUD + 搜索 + 事件接口。

#### 1.3.1 数据模型

**MDFileDescriptor（Markdown 文件描述符）：**

```typescript
interface MDFileDescriptor {
  dir: string           // 父目录路径
  path: string          // 绝对路径
  name: string          // 文件名（含扩展名）
  ext: string           // 扩展名
  size: number          // 文件大小
  id: string            // Zettelkasten ID（从文件内容提取）
  tags: string[]        // 标签列表（从内容提取）
  links: string[]       // 出链列表（从内容提取）
  citekeys: string[]    // 引用键
  bom: string           // BOM 标记
  type: 'file'          // 文件类型标识
  wordCount: number     // 词数
  charCount: number     // 字符数
  modtime: number       // 最后修改时间戳
  creationtime: number  // 创建时间
  linefeed: string      // 换行符类型
  firstHeading: string|null  // 首个 H1 标题
  yamlTitle: string|undefined // YAML title 字段
  frontmatter: any|null      // YAML frontmatter 解析结果
}
```

**DirDescriptor（目录描述符）：**

```typescript
interface DirDescriptor {
  path: string
  name: string
  dir: string
  size: number
  type: 'directory'
  isGitRepository: boolean
  modtime: number
  creationtime: number
  settings: {
    sorting: 'name-up'|'name-down'|'time-up'|'time-down'
    project: ProjectSettings|null  // 项目设置
    icon: string|null
    color: string|null
  }
}
```

**ProjectSettings：**

```typescript
interface ProjectSettings {
  title: string          // 项目标题
  profiles: []           // LaTeX/Word 导出配置
  files: string[]        // 项目包含的文件列表（排序后）
  cslStyle: string       // CSL 引用风格路径
  templates: {
    tex: string          // LaTeX 模板路径
    html: string         // HTML 模板路径
  }
}
```

#### 1.3.2 缓存机制

FSAL 维护一个 JSON 文件缓存，存储在 `{userData}/fsal/cache/`：

- `fsal-cache.ts` 提供 `get/set/has/del/clearCache` 接口
- **缓存命中条件**：`cachedFile.modtime === file.modtime`（仅当文件修改时间未变时使用缓存）
- 解析后的描述符通过 `structuredClone()` 深度克隆后存入缓存
- 10MB 以上的文件跳过解析（安全限制）
- 新版本检测或 `--clear-cache` 命令行参数会清空缓存

#### 1.3.3 文件监控

`FSALWatchdog` 封装了 `chokidar`，对每个 root 路径维护独立 watcher：

```
this.watchers = new Map<string, FSALWatchdog>()
```

文件变更事件流：
1. chokidar 检测到变更 → 删除对应缓存条目
2. `unlink`/`unlinkDir`：直接发射事件
3. `add`/`change`/`addDir`：重新获取描述符 → 发射带描述符的事件
4. 事件通过 IPC (`broadcastIPCMessage`) 广播到所有渲染进程

#### 1.3.4 根路径管理

```
config.openPaths = { openFiles: string[], openWorkspaces: string[] }
```

- 启动时通过 `syncRoots()` 检查所有路径有效性
- 失效的文件从配置中移除；失效的工作区标记为"dead"（保留用户配置）
- 配置更新时自动同步 watcher 列表

#### 1.3.5 IPC 通信模式

主进程暴露 `ipcMain.handle('fsal', ...)`，支持的 command：

- `read-path-recursively`：递归读取目录下所有文件路径
- `read-directory`：读取单层目录
- `get-descriptor`：获取路径对应的描述符（支持单路径和批量）

### 1.4 标签系统

`TagProvider` 管理全应用标签：

- **标签来源**：从文件描述符的 `tags` 字段提取（通过 `extractFromFileDescriptors`）
- **标签着色**：`coloredTags` 存储在 `{userData}/tags.json` 中
- **标签与文件映射**：维护 `Map<tagName, filePath[]>` 的双向索引
- **IDF 计算**：`Math.log(N / tag.files.length)` 实现标签权重
- **持久化**：使用 `PersistentDataContainer` 封装（JSON 文件读写 + init 检查）
- **实时更新**：文件保存时自动重新计算所有标签

### 1.5 目录配置系统（.ztr-directory）

每个目录可通过 `.ztr-directory` JSON 文件自定义设置：

```json
{
  "sorting": "name-up",
  "project": null,
  "icon": null,
  "color": null
}
```

- 默认为 `SETTINGS_TEMPLATE`，不写文件
- 只有非默认设置时才持久化到文件
- 设置恢复为默认时自动删除对应的 `.ztr-directory` 文件
- `safeAssign` 工具函数确保只合并有效字段

### 1.6 应用生命周期

```typescript
// lifecycle.ts
async function boot(): Promise<void> {
  // 1. 显示启动画面
  // 2. 启动服务提供者（按依赖顺序）
  // 3. 初始化 FSAL + 同步根路径
  // 4. 重建文件索引（显示进度条）
  // 5. 关闭启动画面
  // 6. 打开窗口
}
```

- 长耗时操作（如文件索引）通过 `LongRunningTaskProvider` 管理，显示进度
- 服务提供者继承自 `ProviderContract`，实现 `boot()` / `shutdown()` 接口

---

## 2. Notable — 极简本地存储

### 2.1 基本信息

| 条目 | 内容 |
|------|------|
| 技术栈 | Electron + React + TypeScript |
| 编辑器 | CodeMirror |
| 许可证 | MIT (v1.3.0 及之前) / AGPL v3 (v1.4.0~v1.5.1) / 闭源 (v1.6+) |
| 源码 | https://github.com/notable/notable |

### 2.2 目录结构（v1.3.0）

```
src/
├── main/              # Electron 主进程
│   ├── index.ts       # 入口
│   ├── app.ts         # 应用控制器
│   ├── utils/         # 工具函数
│   └── windows/       # 窗口管理
├── renderer/          # React 渲染进程
│   ├── index.ts       # 入口
│   ├── index.html     # HTML 模板
│   ├── render.tsx     # React 渲染入口
│   ├── routes.ts      # 路由
│   ├── components/    # UI 组件
│   ├── containers/    # 容器组件
│   ├── utils/         # 渲染进程工具
│   └── template/      # 模板
└── common/            # 主进程 + 渲染进程共享
    ├── config.ts      # 配置类型
    ├── environment.ts # 环境枚举
    ├── settings.ts    # 设置类型
    └── types.ts       # 共享类型定义
```

### 2.2 存储模型

Notable 的核心设计理念：**零锁定，纯文件系统**。

```
/path/to/your/data_directory/
├── attachments/       # 附件目录
│   ├── foo.ext
│   └── bar.ext
└── notes/             # 笔记目录
    ├── foo.md
    └── bar.md
```

- 笔记：纯 Markdown 文件 + YAML front matter 存储元数据
- 附件：独立文件，不嵌入笔记
- 无数据库、无索引文件、无隐藏配置文件

### 2.3 标签层级设计

Notable 最独特的设计：**标签可无限嵌套**。

- 普通标签：`foo`、`bar`
- 嵌套标签：`foo/bar`、`foo/bar/qux`
- 笔记本和模板也是特殊标签：`Notebooks/foo`、`Templates/foo`

这种设计消除了"笔记本"与"标签"的概念差异，整个组织体系统一为标签树。

### 2.4 Notable 总结

Notable 的架构理解起来极其简单——它给我们的启示是：**File-as-record 模式**，即用文件路径 + 文件名 + YAML front matter 构成完整的记录系统，不需要额外的数据库层。

---

## 3. Obsidian — 插件生态与图结构

### 3.1 基本信息

| 条目 | 内容 |
|------|------|
| 技术栈 | Electron + TypeScript（闭源核心 + 开源插件 API） |
| 存储 | 本地 Markdown 文件 + IndexedDB 元数据缓存 |
| 插件 API | 开源 TypeScript 类型定义 |
| 官网 | https://obsidian.md |
| 开发者文档 | https://docs.obsidian.md |

### 3.2 Vault 结构

Obsidian 将"一个文件夹"定义为 vault，所有数据存储在该文件夹中：

```
my-vault/
├── .obsidian/                          # 配置目录（隐藏）
│   ├── app.json                        # 应用设置
│   ├── appearance.json                 # 主题/外观设置
│   ├── community-plugins.json          # 已启用社区插件列表
│   ├── hotkeys.json                    # 自定义快捷键
│   ├── workspace.json                  # 当前工作区布局
│   ├── workspaces.json                 # 保存的工作区
│   ├── themes/                         # 已安装的主题（CSS）
│   │   └── obsidian.css
│   ├── plugins/                        # 已安装的社区插件
│   │   └── <plugin-id>/
│   │       ├── main.js                 # 编译后的插件代码
│   │       ├── manifest.json           # 插件清单
│   │       └── data.json               # 插件设置（由插件写入）
│   └── snippets/                       # 自定义 CSS 片段
├── note1.md
├── note2.md
└── folder/
    └── note3.md
```

**Global settings**（系统级，非 vault 内）：
- macOS：`~/Library/Application Support/obsidian`
- Windows：`%APPDATA%\Obsidian\`
- Linux：`~/.config/obsidian/`

### 3.3 插件系统

#### 3.3.1 插件清单（manifest.json）

```json
{
  "id": "plugin-id",
  "name": "Plugin Name",
  "version": "1.0.0",
  "minAppVersion": "0.15.0",
  "description": "What this plugin does",
  "author": "Author Name",
  "isDesktopOnly": false
}
```

#### 3.3.2 插件生命周期

所有插件继承自 `Plugin` 抽象类（继承自 `Component`）：

```typescript
class MyPlugin extends Plugin {
  async onload() {
    // 插件加载：注册命令、图标、设置页、视图、编辑器扩展
  }
  onunload() {
    // 清理
  }
}
```

**关键注册方法：**

| 方法 | 用途 |
|------|------|
| `addCommand()` | 注册全局命令（自动用插件 id 前缀） |
| `addRibbonIcon()` | 在左侧栏添加图标按钮 |
| `addSettingTab()` | 添加设置页面 |
| `addStatusBarItem()` | 添加底部状态栏元素 |
| `registerView()` | 注册自定义视图 |
| `registerMarkdownPostProcessor()` | 注册 Markdown 后处理器（修改渲染结果） |
| `registerEditorExtension()` | 注册 CodeMirror 6 扩展 |
| `registerMarkdownCodeBlockProcessor()` | 注册代码块处理器 |

**数据持久化**：
- `loadData()` / `saveData()` → 读写 `data.json`（插件目录下）
- `Plugin.onExternalSettingsChange()` → 外部修改 data.json 时的回调

#### 3.3.3 核心 API 类

| 类 | 功能 |
|------|------|
| `Vault` | 文件系统操作（读写/创建/删除/移动/复制/监听变更） |
| `DataAdapter` | 数据适配器（抽象文件操作层，支持本地和 Sync） |
| `Workspace` | 工作区管理（布局、标签页、叶子节点） |
| `MetadataCache` | 元数据缓存（链接解析、标签索引等） |
| `Editor` | 编辑器控制 |
| `App` | 应用根对象，提供上述所有实例 |
| `Component` | 组件基类（生命周期 + 子组件管理 + 事件清理） |

**Vault 事件系统**：
```typescript
vault.on('create', (file) => {})
vault.on('modify', (file) => {})
vault.on('delete', (file) => {})
vault.on('rename', (file, oldPath) => {})
```

### 3.4 元数据缓存

- 存储位置：IndexedDB（浏览器内建客户端数据库）
- 缓存内容：文件元数据、标签、链接、标题、frontmatter
- 目的：避免每次查询都读取文件系统
- 刷新机制：文件变更时自动同步
- 手动重建：设置 → 文件与链接 → 重建元数据缓存

### 3.5 内部链接与图谱

- **链接格式**：`[[wikilink]]` 和 `[markdown link](path)` 双支持
- **链接解析**：Obsidian 独特的 shortest-path 解析（不要求完整路径）
- **图谱**：基于元数据缓存构建的有向图，节点 = 文件，边 = 内部链接
- **图谱索引**：`MetadataCache` 维护所有文件间的链接关系

### 3.6 Obsidian 总结

Obsidian 的关键架构决策：
1. **闭源核心 + 开源 API**：核心功能不开源，但插件 API 完全开放且有完整 TypeScript 类型
2. **文件即记录**：Markdown 文件是最终存储，IndexedDB 仅为性能缓存
3. **配置分区**：vault 级 vs 全局级，`.obsidian/` 文件夹作为配置容器
4. **懒加载 + 事件驱动**：文件变更事件驱动缓存更新，避免轮询

---

## 4. Vela 与 Bloomverse — 未找到有效源

### 4.1 Vela

搜索 "vela writing app"、"vela AI writing tool"、"vela.sh" 等多个组合，返回结果均为小米 Vela 物联网操作系统。未能找到名为 "Vela" 的独立 AI 写作工具。

**推测**：可能为：
- 名称有误或混淆（被小米 Vela 的 SEO 完全压制）
- 非常小众的未开源工具
- 已更名或停止维护

### 4.2 Bloomverse

搜索 "bloomverse writing platform"、"bloomverse novel" 等均未返回相关的写作软件信息。

**推测**：同样可能不存在于可公开搜索的范围内。

> **注**：若这两个工具确实存在，建议提供更精确的 URL、产品描述或 GitHub 仓库地址，以便补充分析。

---

## 5. 可复用架构模式总结

以下是从上述研究（主要是 Zettlr、Notable、Obsidian）中提取的可复用架构模式。

### 5.1 文件系统即数据库（FSAL 模式）

**来源**：Zettlr（核心）、Notable、Obsidian

**核心思想**：
- 文件系统本身就是数据库，无需额外的 SQL/NoSQL 引擎
- Markdown 文件 = 记录，YAML front matter = 结构化字段，文件路径 = 主键
- 通过文件修改时间（mtime）作为乐观锁和缓存失效依据

**架构要点**：

```
┌─────────────────────────────────────────┐
│           写作应用                      │
│  ┌─────────────────────────────────┐   │
│  │   业务逻辑层 (Vue/React)        │   │
│  └──────────────────┬──────────────┘   │
│                     │                   │
│  ┌──────────────────▼──────────────┐   │
│  │   服务提供者 (Service Providers) │   │
│  │   - Documents / Tags / Config   │   │
│  │   - Commands / Stats / Links    │   │
│  └──────────────────┬──────────────┘   │
│                     │                   │
│  ┌──────────────────▼──────────────┐   │
│  │   FSAL (文件系统抽象层)         │   │
│  │   ┌─────────┐ ┌──────────────┐  │   │
│  │   │ 解析器  │ │ 缓存(Cache)  │  │   │
│  │   ├─────────┤ ├──────────────┤  │   │
│  │   │ 监控器  │ │ 事件发射器   │  │   │
│  │   └─────────┘ └──────────────┘  │   │
│  └──────────────────┬──────────────┘   │
│                     │                   │
│  ┌──────────────────▼──────────────┐   │
│  │   文件系统 (磁盘)               │   │
│  │   notes/  attachments/  config/ │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

**可复用的 FSAL 接口设计**：

```typescript
interface FSAL {
  // 文件操作
  parseFile(path: string): Promise<FileDescriptor>
  loadFile(descriptor: FileDescriptor): Promise<string>
  saveFile(descriptor: FileDescriptor, content: string): Promise<void>
  deleteFile(path: string): Promise<void>

  // 目录操作
  parseDirectory(path: string): Promise<DirDescriptor>
  readDirectory(path: string): Promise<AnyDescriptor[]>
  readDirectoryRecursively(path: string): Promise<string[]>

  // 搜索
  search(descriptors: FileDescriptor[], terms: SearchTerm[]): Promise<SearchResult[]>

  // 缓存
  getCache(path: string): Promise<FileDescriptor|null>
  setCache(descriptor: FileDescriptor): Promise<void>
  invalidateCache(path: string): Promise<void>

  // 事件
  on(event: 'change'|'add'|'unlink', callback: (event, path) => void): void

  // 元数据
  getFilesystemMetadata(path: string): Promise<{modtime, birthtime, size}>
}
```

### 5.2 服务提供者模式

**来源**：Zettlr

将应用功能拆分为独立的 Service Provider，每个 provider 继承自公共接口：

```typescript
abstract class ProviderContract {
  abstract boot(): Promise<void>
  abstract shutdown(): Promise<void>
}
```

**Provider 类型**：
- **系统级**：Config、Log、Windows、Menu、Updates
- **数据级**：FSAL、Documents、Tags、Links、Assets
- **功能级**：Commands、Citeproc、Stats、Dictionary、Appearance

**依赖管理**：通过 `AppServiceContainer` 管理 Provider 间的依赖和启动顺序。

**IPC 桥接**：每个 Provider 在 `boot()` 中注册自己的 IPC handler，渲染进程通过 IPC 通信。

### 5.3 标签系统设计

三种不同的标签实现思路：

| 方案 | 代表 | 存储方式 | 嵌套支持 | 复杂度 |
|------|------|----------|----------|--------|
| 内容提取 | Zettlr | 从文件内容正则提取 | 无 | 低 |
| Front Matter | Notable | YAML front matter | `/` 分隔嵌套 | 极低 |
| 元数据缓存 | Obsidian | IndexedDB | 有 | 中 |

**推荐方案**（结合三者优点）：
- 标签存储在 YAML front matter 中（Notable 模式——零锁定）
- 建立内存中的 `Map<tagName, filePath[]>` 索引（Zettlr 模式）
- 可选地存储为 JSON 缓存文件以加速启动（Zettlr 缓存模式）

### 5.4 项目（Project）管理

**来源**：Zettlr

```
每个目录可选包含一个 .ztr-directory 文件
├── .ztr-directory       # JSON 格式的项目配置
├── chapter-01.md
├── chapter-02.md
└── ...
```

**ProjectSettings 数据模型**：
```typescript
interface ProjectSettings {
  title: string         // 项目标题
  files: string[]       // 项目包含文件列表（显式排序）
  profiles: ExportProfile[]  // 多个导出配置
  cslStyle: string      // 引用风格
  templates: { tex, html }  // 导出模板路径
}
```

**设计要点**：
- 目录本身作为项目容器（无需额外项目文件）
- `.ztr-directory` 是可选配置文件，仅存储非默认设置
- `files: string[]` 显式控制文件顺序（对导出为单一文档至关重要）
- 自动清理：设置恢复默认时删除对应的 `.ztr-directory` 文件

### 5.5 缓存策略对比

| 策略 | 使用方 | 存储位置 | 失效条件 | 优势 |
|------|--------|----------|----------|------|
| mtime 比对 | Zettlr | 磁盘 JSON | modtime 变化 | 轻量、可靠 |
| IndexedDB | Obsidian | 浏览器 DB | 文件变更事件 | 适合复杂查询 |
| 无缓存 | Notable | 无 | 无 | 零复杂度 |
| 懒解析 | Zettlr | 内存 | GC | 启动快 |

### 5.6 插件系统设计模式

**来源**：Obsidian

```
┌──────────────────────────────────────────────┐
│              Obsidian Core                    │
│  ┌─────────┐ ┌──────────┐ ┌───────────────┐  │
│  │  Vault  │ │Workspace │ │ MetadataCache │  │
│  └─────────┘ └──────────┘ └───────────────┘  │
│         │           │              │          │
│         ▼           ▼              ▼          │
│  ┌──────────────────────────────────────┐    │
│  │         Plugin API 层                │    │
│  │  Plugin extends Component            │    │
│  │  +addCommand / +addRibbonIcon / ...  │    │
│  └──────────────────┬───────────────────┘    │
│                     │                         │
│  ┌──────────────────▼───────────────────┐    │
│  │          插件加载器                    │    │
│  │  扫描 .obsidian/plugins/<id>/        │    │
│  │  读取 manifest.json → 加载 main.js   │    │
│  └─────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

**插件清单设计**：
```json
{
  "id": "唯一标识",
  "name": "显示名称",
  "version": "语义化版本",
  "minAppVersion": "最低应用版本",
  "description": "描述",
  "author": "作者"
}
```

**插件注册项类型**：
- 命令（Command）：全局可搜索的命令
- 图标按钮（Ribbon Icon）：侧栏快捷入口
- 设置页（Setting Tab）：插件配置界面
- 视图（View）：自定义面板/侧栏
- Markdown 处理器：修改渲染输出
- 编辑器扩展：CodeMirror 6 插件
- 编辑器建议（EditorSuggest）：自动补全

### 5.7 Electron 架构模式

| 方面 | Zettlr | Notable | Obsidian |
|------|--------|---------|----------|
| IPC 通信 | `ipcMain.handle('channel', ...)` | 标准 Electron IPC | 标准 Electron IPC |
| 窗口管理 | 专用 Provider | windows/ 目录 | Workspace API |
| 预加载脚本 | common/modules/preload/ | 有 | 有 |
| 状态管理 | Pinia (Vue 3) | React state | 内部状态 + 插件 DataAdapter |

---

## 综合推荐（针对写作工具开发）

### 建议选型

| 模块 | 推荐方案 | 理由 |
|------|----------|------|
| **核心架构** | Zettlr 的 FSAL | 最完善的本地文件抽象，支持极大规模 |
| **存储模型** | Notable 的纯文件模式 | 零锁定、可 Git 化 |
| **插件系统** | Obsidian 的设计 | 成熟、丰富的 API 表面 |
| **标签系统** | YAML frontmatter + 内存索引 | 兼顾可移植性与查询性能 |
| **项目管理** | Zettlr 的 .ztr-directory | 轻量，可扩展 |
| **缓存** | mtime 比对 + JSON 文件 | 简单可靠，无外部依赖 |

### 最小可行架构 API

```typescript
// 核心数据模型
interface Document {
  id: string
  title: string
  content: string
  metadata: {
    tags: string[]
    created: number
    modified: number
    wordCount: number
    // ... 自定义字段
  }
}

// 文件系统抽象
interface DocumentStore {
  list(): Promise<DocumentSummary[]>
  get(id: string): Promise<Document>
  save(doc: Document): Promise<void>
  delete(id: string): Promise<void>
  search(query: SearchQuery): Promise<DocumentSummary[]>
  onChanged(callback: (event, id) => void): void
}

// 服务提供者
interface ServiceProvider {
  name: string
  init(): Promise<void>
  destroy(): Promise<void>
}

// 插件契约
interface Plugin {
  id: string
  onload(app: App): void
  onunload(): void
}
```

---

## 来源

- Zettlr GitHub: https://github.com/Zettlr/Zettlr
- Zettlr README（Directory Structure & Architecture 章节）
- Notable GitHub (v1.3.0 MIT): https://github.com/notable/notable
- Obsidian 开发者文档: https://docs.obsidian.md
- Obsidian 数据存储说明: https://help.obsidian.md/Files+and+folders/How+Obsidian+stores+data
- Obsidian Plugin API TypeScript 类型定义
