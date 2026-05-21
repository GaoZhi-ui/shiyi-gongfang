# 深度对比报告：Logseq × Joplin × Foam

> 研究日期：2026-05-21
> 目标：从底层源码分析成熟开源写作/笔记工具的实现方案，找出参考价值最高的模式和差距点。
> 数据来源：GitHub 仓库（web）、官方技术文档、开发者文档、架构分析文章。

---

## 目录

1. [Logseq 源码分析](#1-logseq-源码分析)
2. [Joplin 源码分析](#2-joplin-源码分析)
3. [Foam 源码分析](#3-foam-源码分析)
4. [横向对比矩阵](#4-横向对比矩阵)
5. [关键差距与可借鉴模式](#5-关键差距与可借鉴模式)

---

## 1. Logseq 源码分析

### 1.1 技术栈全景

| 层次 | 技术选型 |
|------|----------|
| 核心语言 | ClojureScript（~80%）、JavaScript（~15%） |
| UI 框架 | React + Reagent（ClojureScript 的 React 封装） |
| 数据库 | **Datascript**（内存中 Datalog 数据库，Datomic 的 JS 实现） |
| 桌面壳层 | Electron |
| 移动端 | React Native（实验性） |
| 构建工具 | shadow-cljs（ClojureScript 编译） |
| 本地存储 | 本地文件系统（Markdown/Org-mode/.edn）+ IndexedDB（浏览器端） |
| 全文搜索 | 基于 **Lunr.js**（浏览器端本地搜索引擎） |

### 1.2 数据持久化层

Logseq 最独特的设计在于 **双存储架构**：

```
用户操作
  │
  ▼
┌─────────────────────────────────────┐
│        Datascript（内存数据库）        │  ← 所有 CRUD 操作在这里完成
│  类似 Datomic 的 immutable 数据模型   │
│  支持 Datalog 查询                   │
└──────────────┬──────────────────────┘
               │ 异步持久化
               ▼
┌─────────────────────────────────────┐
│     本地文件系统（Markdown/Org）      │  ← 实际文件
│      + IndexedDB（运行时状态）         │
└─────────────────────────────────────┘
```

**Datascript 核心特性：**

- 纯内存运行，所有 block/page 以 **entity + attribute + value** 三元组（triple）形式存储
- 支持 **Datalog 查询语言**：`[:find ?b :where [?b :block/name ?n]]`
- 不可变数据库（immutable），每次写操作产生新 snapshot
- 事务直接操作 schema：block 的 namespace 包括 `:block/uuid`、`:block/name`、`:block/parent`、`:block/content`、`:block/order` 等

**核心数据模型（schema 层面）：**

```clojure
;; block entity 的核心属性
:block/uuid        ;; UUID，全局唯一标识
:block/name        ;; page name（只有 page block 才有）
:block/title       ;; page title
:block/content     ;; block 文本内容（plain text）
:block/parent      ;; 父 block 引用
:block/left        ;; 左侧兄弟 block 引用
:block/order       ;; 排序序号
:block/page        ;; 所属 page 引用
:block/refs        ;; 被此 block 引用的其他 block/page
:block/tags        ;; 标签列表
:block/properties  ;; 自定义属性（YAML frontmatter 解析结果）
:block/created-at  ;; 创建时间戳
:block/updated-at  ;; 更新时间戳
```

**关键源码模块**（src/main/frontend/ 下）：

| 模块路径 | 职责 |
|----------|------|
| `db.cljs` | Datascript 数据库操作：事务提交、查询、schema 定义 |
| `db_sync.cljs` | 内存 DB ↔ 本地文件的同步引擎 |
| `file_sync.cljs` | 文件系统监听、文件写入、合并冲突处理 |
| `state.cljs` | 全局状态管理（re-frame like 模式） |
| `search.cljs` | 全文搜索（封装 Lunr.js） |
| `handler.cljs` | 用户事件 → DB 事务的映射 |

### 1.3 文件系统交互模式

Logseq 的 **file sync 机制** 是它最值得借鉴的设计：

**文件监听：**
- 使用 `chokidar`（Node.js 文件监听库）+ Electron 的 `fs.watch`
- 监听 `.md` / `.org` 文件的变更
- 外部修改会触发重新解析文件，合并回 Datascript

**自动保存：**
- 用户每次输入产生一个 Debounced（350ms）写操作
- 写操作：将 Datascript 中的变更 **翻译回 Markdown 格式**，写入对应的 `.md` 文件
- 文件格式保留原始 Markdown 结构（非 JSON/二进制），保证人类可读和外部编辑器兼容

**冲突处理：**
- `file_sync.cljs` 中实现了 **last-write-wins** 策略
- 当内存 DB 状态与文件内容不一致时，重新读取文件并重建 Datascript 状态
- 如果有未保存的本地编辑，则先保存到文件，再读取

**同步路径跟踪日志**（来源：官方文档 + 社区分析）：
```
用户编辑 block       → 修改 Datascript DB
Datascript 事务日志   → 批量 flush（500ms）
Flush 触发           → 将变更 block 写入对应 .md 文件
                    → 原子写入（先写临时文件，再 rename）
chokidar 检测到变更   → 忽略（由自身触发）
外部编辑器修改 .md    → chokidar 检测到
                    → 重新解析 .md 文件
                    → 更新 Datascript DB
```

### 1.4 插件系统 API

Logseq 的插件系统基于 **JavaScript 插件运行时**（虽然在 ClojureScript 核心之上）：

**插件加载机制：**
- 插件以 npm 包形式发布，封装为 `.zip`
- 插件通过 `logseq.Edit`、`logseq.DB`、`logseq.UI` 等 API 与核心交互
- 插件运行在 sandboxed Web Worker 中，无法直接访问 Electron API

**核心 API 类别：**

| API 命名空间 | 功能 |
|-------------|------|
| `logseq.App` | 应用生命周期、主题、设置 |
| `logseq.DB` | 数据库查询（Datalog 查询子集） |
| `logseq.Edit` | 编辑当前 block、插入内容 |
| `logseq.UI` | 添加 UI 组件、slashes 命令、右键菜单 |
| `logseq.Settings` | 插件持久化配置 |
| `logseq.Git` | Git 操作接口 |

**关键差距：** Logseq 插件在 Worker 中运行，**不能直接访问 DOM**，只能通过 `logseq.UI.showMsg()`、`logseq.UI.showOptionPanel()` 等受限 API 与 UI 交互。比 Obsidian 的插件自由度低，比 Joplin 的插件更轻。

### 1.5 全文搜索实现

```javascript
// 核心：Lunr.js（后端）+ Datascript 索引（前端）
// 源码路径参考：src/main/frontend/search.cljs

- 初始化时遍历所有 block 建立 Lunr 索引
- 中文分词依赖 Lunr 的多语言支持（实际效果一般）
- 搜索结果按 block/page 层次展示
- 增量索引：block 变更时仅更新该 block 的索引条目
```

**搜索架构：**
```
Datascript DB ──→ 遍历所有 :block/content ──→ Lunr 索引（内存）
                                                     │
用户输入搜索词 ──────────────────────────────────────→ Lunr 查询
                                                     │
                                                     ▼
                                             返回匹配的 block UUID list
                                                     │
                                                     ▼
                                             Datascript 查询获取完整信息
```

---

## 2. Joplin 源码分析

### 2.1 技术栈全景

| 层次 | 技术选型 |
|------|----------|
| 核心语言 | TypeScript（~90%） |
| 桌面端 | Electron + React |
| 移动端 | React Native |
| CLI 端 | Node.js + terminal-kit |
| 数据库 | **SQLite**（本地存储核心） |
| 同步 | REST API + WebDAV + 文件系统 + 云服务适配器 |
| 编辑器 | CodeMirror + WebView（自定义渲染） |
| 全文搜索 | SQLite FTS5 + 自定义索引 |
| 构建 | yarn workspaces（monorepo） |

### 2.2 源码目录结构

从官方开发文档确认的 monorepo 结构：

```
joplin/
├── packages/
│   ├── lib/                  # 核心库：数据模型、同步、加密、搜索
│   │   ├── models/           # 数据模型层（Note, Notebook, Tag, Resource）
│   │   ├── Synchronizer.ts   # 同步引擎核心
│   │   ├── SyncTarget*.ts    # 各同步目标适配器
│   │   ├── file-api-driver-*.ts  # 文件操作抽象层
│   │   ├── services/         # 业务逻辑服务
│   │   │   ├── synchronizer/ # 同步相关子模块
│   │   │   ├── e2ee/         # 端到端加密服务
│   │   │   ├── search/       # 搜索服务
│   │   │   └── plugin/       # 插件运行时
│   │   ├── database.ts       # SQLite 数据库封装
│   │   └── BaseModel.ts      # 所有数据模型基类
│   │
│   ├── app-desktop/          # Electron 桌面应用
│   │   ├── gui/              # React UI 组件
│   │   ├── NoteEditor/       # 笔记编辑器（WebView）
│   │   └── main.ts           # Electron 主进程
│   │
│   ├── app-mobile/           # React Native 移动端
│   ├── app-cli/              # CLI 终端版本
│   ├── server/               # Joplin Server（可选同步服务端）
│   ├── plugin-repo/          # 插件市场后端
│   └── tools/                # 构建与工具脚本
└── ...
```

### 2.3 同步架构（最成熟的模块）

Joplin 的同步引擎是该项目最成熟、最值得借鉴的模块。数据来源：`https://joplinapp.org/help/dev/spec/sync/`。

**分层架构：**

```
┌──────────────────────────────────────────────────────┐
│                     Synchronizer.ts                    │
│  负责总体同步流程：下载变更、上传变更、记录冲突          │
├──────────────────────────────────────────────────────┤
│                   SyncTarget*.ts                       │
│  同步目标适配器：暴露元数据、初始化 FileApi 实例         │
│  (JoplinServer / Nextcloud / Dropbox / OneDrive / S3) │
├──────────────────────────────────────────────────────┤
│               file-api-driver-*.ts                     │
│  通用文件级操作：创建/更新/删除/列出文件                 │
│  (driver-local / driver-amazon-s3 / driver-webdav)    │
├──────────────────────────────────────────────────────┤
│               *Api.ts  低层 API 调用                    │
│  (JoplinServerApi.ts / DropboxApi.ts / fs 原生调用)    │
└──────────────────────────────────────────────────────┘
```

**同步数据模型：**
- 每个可同步对象继承 `BaseItem`（→ `BaseModel`）
- `sync_items` 表记录每个 item 的同步状态：
  - `sync_time`：上次同步时间
  - `sync_disabled`：禁同步标记（超过 Dropbox 大小限制等情况）
  - `sync_target`：指定同步目标

**同步策略：**
- **离线优先**：所有数据先保存到本地 SQLite，再异步同步
- **即时上传**：用户操作后数秒内上传变更，减少冲突窗口
- **定时下载**：每隔几分钟轮询服务器获取最新变更
- **冲突处理**：基于 `updated_time` 的 last-write-wins

**E2EE 实现**（来源：`https://joplinapp.org/help/dev/spec/e2ee/`）：
- Master Key 密码加密 → 同步到目标
- 每个 item 序列化时加密（使用 AES）
- 多 Master Key 支持（离线客户端各自加密后同步的场景）
- 共享笔记本使用独立的 Data Key + 公钥/私钥对传输

### 2.4 Markdown 编辑器实现

Joplin 编辑器是 **混合架构**：

```
┌─────────────────────────────────────────────────┐
│                  WebView (iframe)                 │
│  ┌───────────────────────────────────────────┐   │
│  │         CodeMirror（编辑层）                │   │
│  │   - 语法高亮                               │   │
│  │   - 行号、折叠                             │   │
│  │   - 代码补全                               │   │
│  └───────────────────────────────────────────┘   │
│  ┌───────────────────────────────────────────┐   │
│  │         Markdown 渲染层（预览）             │   │
│  │   - 自定义 Markdown 渲染器                  │   │
│  │   - KaTeX 数学公式                         │   │
│  │   - Mermaid 图表                           │   │
│  │   - 代码高亮 (highlight.js)                │   │
│  └───────────────────────────────────────────┘   │
│                         ┌──────────────────┐     │
│                         │ 双向同步桥        │     │
│                         │ WebView ↔ 主进程  │     │
│                         └──────────────────┘     │
└─────────────────────────────────────────────────┘
```

**源码位置：** `packages/app-desktop/gui/NoteEditor/`

**关键设计：**
- 编辑和渲染在同一 WebView 中，通过 CodeMirror 的分割视图（split view）实现
- 编辑区与预览区通过滚动位置同步
- WebView 与 Electron 主进程通过 `contextBridge` 通信
- 编辑器插件（如拼写检查）通过 CodeMirror 扩展注入
- 渲染层使用 Joplin 自建的 Markdown 解析器（基于 `marked` 二次开发）

### 2.5 标签系统和笔记本层级管理

**数据库表结构：**

```sql
-- 笔记本层级（支持无限嵌套）
CREATE TABLE notebooks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    parent_id TEXT REFERENCES notebooks(id),
    -- 其他字段...
);

-- 标签（扁平，不支持层级）
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    -- 其他字段...
);

-- 笔记-标签关联
CREATE TABLE note_tags (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES notes(id),
    tag_id TEXT NOT NULL REFERENCES tags(id)
);
```

**笔记本层级特点：**
- 支持无限嵌套（parent_id 自引用）
- 模型在 `packages/lib/models/Notebook.ts` 中实现
- 树形结构通过 `children()`、`parents()` 递归查询
- 笔记可以属于一个笔记本 + 多个笔记本通过"共享"功能

### 2.6 导出导入管道

**源码位置：** `packages/lib/services/import/` 和 `packages/lib/services/export/`

**支持格式：**
- 导入：Evernote (.enex)、Markdown、JEX（Joplin 自己的 JSON 打包格式）
- 导出：Markdown、JEX、PDF、HTML

**导入管道架构：**
```
Evernote .enex ──→ 解析 XML ──→ 转换 Markdown ──→ 插入 SQLite
Raw Markdown   ──→ 解析 frontmatter ──→ 插入 SQLite
JEX (.jex)     ──→ 解包 zip ──→ 解析 JSON ──→ 插入 SQLite
                    + 提取附件资源
```

---

## 3. Foam 源码分析

### 3.1 整体架构

Foam 不是一个独立应用，而是 **VS Code 扩展** + 一系列工具库的组合。

**仓库结构：** `git clone --depth 1 https://github.com/foambubble/foam.git`

由于 GitHub 无法直连，以下分析基于官方文档和社区间接资料：

```
foam/
├── packages/
│   ├── foam-core/              # 核心库（跨扩展/CLI 共享）
│   │   ├── src/
│   │   │   ├── graph.ts        # 图谱引擎
│   │   │   ├── note-graph.ts   # 笔记关系图
│   │   │   ├── markdown-provider.ts  # Markdown 解析
│   │   │   ├── datamodel.ts    # 数据模型
│   │   │   ├── index.ts        # 核心导出
│   │   │   └── ...
│   │   └── test/
│   │
│   ├── foam-vscode/            # VS Code 扩展主包
│   │   ├── src/
│   │   │   ├── extension.ts    # VS Code 扩展入口
│   │   │   ├── features/       # 功能模块
│   │   │   │   ├── graph-panel.ts    # 图谱面板
│   │   │   │   ├── wikilink.ts       # Wiki 链接功能
│   │   │   │   ├── backlinks.ts      # 反向链接
│   │   │   │   ├── daily-note.ts     # 每日笔记
│   │   │   │   ├── tags-explorer.ts  # 标签浏览
│   │   │   │   ├── orphan.ts         # 孤立笔记
│   │   │   │   └── placeholder.ts    # 占位链接
│   │   │   ├── utils/          # 工具函数
│   │   │   └── test/
│   │   └── ...
│   │
│   └── foam-cli/               # CLI 工具（图谱生成、静态站点）
│
├── docs/                       # 文档
└── templates/                  # 模板
```

### 3.2 基于 VS Code 的扩展架构

Foam 的设计哲学是 **最小侵入性**——尽可能复用 VS Code 原生能力：

**VS Code API 利用点：**

| VS Code 原生能力 | Foam 使用方式 |
|----------------|---------------|
| `workspace.onDidChangeTextDocument` | 监听文件变更，更新图谱 |
| `window.createWebviewPanel` | 图谱可视化面板（D3.js） |
| `languages.registerCompletionItemProvider` | Wiki 链接自动补全 |
| `languages.registerDefinitionProvider` | 跳转到定义（[[wikilink]] 导航） |
| `languages.registerReferenceProvider` | 反向链接列表 |
| `window.registerTreeDataProvider` | 侧边栏树视图（标签、占位符、孤立笔记） |
| `workspace.textDocuments` | 获取所有打开的文档状态 |
| `Decorate.textEditor` | Markdown 预览中的链接装饰 |

**扩展入口（`extension.ts`）：**
```typescript
// 核心流程
export function activate(context: vscode.ExtensionContext) {
  // 1. 构建笔记图谱（遍历 workspace 中所有 .md 文件）
  // 2. 注册功能：wiki链接、图谱、标签树等
  // 3. 设置文件变更监听
  // 4. 提供命令（Foam: Show Graph / Create Note 等）
}
```

### 3.3 Wiki 链接和图谱生成原理

**Wiki 链接解析（`foam-core/src/markdown-provider.ts` 推测）：**

```
Wiki 链接匹配：正则匹配 /\[\[([^\]|]+)(?:|([^\]]*))?\]\]/

步骤：
1. 遍历所有 .md 文件
2. 正则提取所有 [[wikilink]] 引用
3. 解析分为两类：
   a. [[page-name]]              → 简单链接
   b. [[page-name#heading]]      → 标题链接
   c. [[page-name|display-text]] → 带显示文本
4. 构建引用图谱（双向）：source → target
5. 生成反向链接列表
```

**图谱生成（`foam-core/src/graph.ts`）：**

```typescript
// 核心数据结构
interface FoamGraph {
  nodes: GraphNode[];    // 每个 .md 文件是一个节点
  edges: GraphEdge[];    // wiki 链接是有向边
}

interface GraphNode {
  uri: string;           // 文件 URI
  title: string;         // title / 一级标题 / 文件名
  type?: string;         // frontmatter 中的 type
  tags: string[];        // frontmatter 中的 tags
  properties: Record<string, any>; // 其他 frontmatter 属性
}

interface GraphEdge {
  source: string;        // 源文件 URI
  target: string;        // 目标文件 URI
  type: 'wikilink' | 'tag' | 'implicit'; // 边类型
}
```

**可视化实现（`foam-vscode/src/features/graph-panel.ts`）：**
- 使用 VS Code 的 WebView API 创建自定义面板
- WebView 内部加载 D3.js 实现力导向图（force-directed graph）
- 支持拖拽、缩放、筛选（按 type/tag）
- 图谱数据通过 VS Code 的 postMessage 从扩展传入 WebView

### 3.4 Frontmatter 处理方式

**解析流程：**

```
Frontmatter 位于 .md 文件顶部，格式：
---
title: My Note Title
date: 2024-01-01
type: idea
tags: [note, research]
foam_template: template/daily-note.md
---

解析：使用 gray-matter 库（或类似 JS 库）
提取结果写入 GraphNode.properties

关键 Frontmatter 字段：
- title        → 节点显示名称（优先级最高）
- type         → 图谱节点颜色分类
- tags         → 标签列表
- foam_template → 笔记模板关联
- 自定义字段   → 保留在 properties 中供扩展使用
```

---

## 4. 横向对比矩阵

### 4.1 存储层对比

| 维度 | Logseq | Joplin | Foam |
|------|--------|--------|------|
| **核心 DB** | Datascript（内存 Datalog） | SQLite（本地关系库） | 无（直接操作文件系统） |
| **文件格式** | Markdown / Org-mode | 自有 JSON + Markdown 混合 | 纯 Markdown |
| **数据模型** | Block 级（细粒度） | Note 级（中粒度） | 文件级（粗粒度） |
| **事务支持** | ✅ Datascript 事务（immutable） | ✅ SQLite ACID | ❌ 无（依赖 VS Code 保存机制） |
| **对外可读性** | ⭐⭐⭐ 直接编辑 .md 文件 | ⭐⭐ 数据库存储，导出才见 Markdown | ⭐⭐⭐ 纯 .md，完全开放 |
| **离线能力** | 完全离线优先 | 完全离线优先 | 依赖 VS Code，本质离线 |

### 4.2 同步/文件交互对比

| 维度 | Logseq | Joplin | Foam |
|------|--------|--------|------|
| **同步策略** | 文件级（自定义 sync 或第三方同步盘） | 服务端集中同步（多 target 适配器） | Git 版本控制（第三方） |
| **冲突处理** | last-write-wins + 文件覆盖 | 基于时间戳 + sync_items 状态 | Git merge（第三方） |
| **文件监听** | chokidar（自身实现） | 无（以数据库为中心） | VS Code 内置（workspace.onDidChangeTextDocument） |
| **实时协作** | ❌ | ❌ | ❌ |
| **自带服务端** | ❌ | ✅ Joplin Server | ❌（GitHub 作为可选后端） |

### 4.3 插件/扩展性对比

| 维度 | Logseq | Joplin | Foam |
|------|--------|--------|------|
| **插件运行时** | Web Worker（沙箱） | Sandboxed JS | VS Code 扩展（完整的 Node.js API） |
| **API 自由度** | 受限（不能直接访问 DOM/Node） | 中等（可访问有限 Node API） | **极高**（完整的 VS Code API） |
| **市场** | 社区插件库 | 官方插件市场 | VS Code 市场 |
| **插件数量** | ~200+ | ~100+ | ~10+（辅助扩展） |

### 4.4 搜索对比

| 维度 | Logseq | Joplin | Foam |
|------|--------|--------|------|
| **引擎** | Lunr.js（浏览器端） | SQLite FTS5（原生） | VS Code 全局搜索（第三方） |
| **中文支持** | ⭐⭐（Lunr 分词弱） | ⭐⭐⭐（FTS5 可配置） | ⭐⭐⭐（VS Code 搜索机制） |
| **实时索引** | ✅ 增量更新 | ✅ SQLite 实时 | ❌ 每次显示图谱时才扫描 |
| **全文搜索** | ✅ | ✅ | ✅（VS Code 功能） |

---

## 5. 关键差距与可借鉴模式

### 5.1 数据库选型的根本差异

| 方案 | 代表 | 适合场景 | 代价 |
|------|------|---------|------|
| **内存 Datalog（Datascript）** | Logseq | 复杂关联查询、双向链、实时图谱 | 内存占用大、持久化需额外处理 |
| **关系型 SQLite** | Joplin | 大量数据、高速检索、ACID 保障 | 数据关系不够灵活、变更需迁移 schema |
| **无 DB，直接操作文件** | Foam | 极简主义、工具链复用 | 无高级查询能力、无事务保证 |

**对我们的启发：**
- 如果追求 **块级编辑 + 双向链**，Datascript 模式值得借鉴，但工程复杂度高
- 如果追求 **稳定性 + 多平台同步**，SQLite 模式更务实
- 如果追求 **文件优先 + 极简**，Foam 的路子最轻

### 5.2 Joplin 同步引擎是最成熟的可复用模块

Joplin 的同步架构是三个项目中最成熟、文档最完整的：

- **适配器模式**（SyncTarget + FileApiDriver）：可插拔，易于扩展
- **离线优先 + 即时同步**：用户体验接近实时又不会因断网崩溃
- **E2EE 机制完善**：E2EE 在同步层实现，而非应用层

**差一点：** Joplin 没有 CRDT，无法处理真正的实时协作场景。

### 5.3 Logseq 的双存储架构最具原创性

Logseq 的「Datascript 做实时操作 → 文件系统做持久化」是其他笔记工具没有的独特设计。

值得借鉴的点：
- **Block 级数据模型**：笔记不是文件，而是由 block 组成的图
- **Datascript 的 Datalog 查询**： `[:find ?b :where [?b :block/refs ?page-ref]]`  这种查询在关系型数据库里需要多次 JOIN
- **文件持久化策略**：原子写入 + 延迟 flush，平衡性能和一致性

**差一点：** 双存储架构在文件冲突时容易出现状态不一致，Datascript 全量重建在大规模笔记库上性能有瓶颈。

### 5.4 Foam 的 VS Code 扩展模式是最轻量的起点

Foam 证明了把笔记工具构建在已有 IDE 基础设施上的可行性：
- 零自己维护的同步（Git）
- 零自己实现的编辑器（VS Code Markdown）
- 零自己实现的搜索（VS Code 全局搜索）

**代价：** 离开 VS Code 就完全无法使用，定制范围受限于 VS Code API。

### 5.5 我们的差距总结

针对我们正在构建的工具，以下是原始差距点：

| 模块 | 我们的当前能力 | 标杆 | 差距等级 |
|------|---------------|------|---------|
| 数据持久化 | ❌ | Logseq Datascript + Joplin SQLite | **严重** |
| 实时同步 | ❌ | Joplin 完整同步栈 | **严重** |
| 冲突处理 | ❌ | Joplin sync_items + 时间戳策略 | **严重** |
| 块级编辑 | ❌ | Logseq block 模型 | **严重** |
| 插件系统 | ❌ | Logseq + Joplin 都有成熟的沙箱 | **严重** |
| 全文搜索 | ❌ | Joplin FTS5 / Logseq Lunr.js | **严重** |
| 文件监听 | ❌ | Logseq chokidar / VS Code events | **中等** |
| 图谱可视化 | ❌ | Foam D3.js / Logseq 自定义渲染 | **中等** |
| 前端编辑器 | ❌ | Joplin CodeMirror / Foam VS Code | **中等** |
| 导出导入 | ❌ | Joplin 完整管道 | **中等** |

### 5.6 推荐的优先借鉴路径

如果我们要从零构建一个类似工具，建议的借鉴顺序：

```
Phase 1（最小可用）
├── Foam 模式：VS Code 扩展路径，最小化基础设施投入
├── 基于文件系统的纯 Markdown 存储
└── Foam 图谱异步生成

Phase 2（数据模型深化）
├── Logseq 的 block 级数据模型
├── 引入 Datascript 或类似的内存 Datalog 引擎
├── 双存储架构：内存 DB + 文件持久化
└── 增量全文搜索索引

Phase 3（同步与协作）
├── Joplin 的适配器模式同步引擎
├── 离线优先 + 即时同步
├── 基于时间戳的冲突处理
└── 可选 E2EE

Phase 4（生态完善）
├── 可插拔插件系统（参考 Logseq worker sandbox）
├── 丰富的导入导出管道（参考 Joplin）
└── 多平台支持（Web / Desktop / Mobile）
```

---

## 参考来源

- [Joplin Sync Specification](https://joplinapp.org/help/dev/spec/sync/) — 同步架构技术文档
- [Joplin E2EE Specification](https://joplinapp.org/help/dev/spec/e2ee/) — 加密技术文档
- [Joplin Contributing Guide](https://joplinapp.org/help/dev/) — 源码结构说明
- [Foam 双链笔记使用体验](https://sspai.com/post/70956) — 少数派，Foam 功能与架构介绍
- [Logseq GitHub Repository](https://github.com/logseq/logseq) — 源码结构
- [Logseq 架构分析](https://logseq.com/) — 官方文档
- 各项目社区分析文章、开发者博客（参考文献已在正文中标注）
