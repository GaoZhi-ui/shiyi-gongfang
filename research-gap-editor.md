# 编辑器深度对比研究报告

> 调研日期：2026-05-21
> 调研对象：Marktext, Notable, Zettlr
> 调研重点：编辑器实现、主题系统、标签层级、文件系统抽象
> 对比基线：我们的写作工坊

---

## 目录

1. [Marktext：所见即所得 + 自研 Muya 引擎](#1-marktext所见即所得--自研-muya-引擎)
2. [Notable：极简存储 + CodeMirror + 无限标签层级](#2-notable极简存储--codemirror--无限标签层级)
3. [Zettlr：FSAL + CodeMirror 6 + 学术工作台](#3-zettlrfsal--codemirror-6--学术工作台)
4. [标签系统深度对比：Notable vs 我们的 Tags](#4-标签系统深度对比notable-vs-我们的-tags)
5. [综合分析与迁移建议](#5-综合分析与迁移建议)

---

## 1. Marktext：所见即所得 + 自研 Muya 引擎

### 1.1 项目概况

| 项目 | 值 |
|------|-----|
| 语言 | JavaScript (Electron) |
| Star | ~56k |
| 编辑器引擎 | **自研 Muya** |
| 框架 | Vue 2 (renderer) |
| 许可证 | MIT |
| 状态 | 活跃开发中 |

### 1.2 编辑器核心架构

Marktext 没有使用 ProseMirror、Slate 或 CodeMirror，而是自研了一套名为 **Muya** 的所见即所得引擎。

**源码路径：** `src/muya/`

```
src/muya/lib/
├── index.js            # Muya 主类：插件系统、事件管道、渲染入口
├── config/             # 默认配置、CSS 变量定义
├── contentState/       # 核心：文档状态机
│   ├── arrowCtrl.js
│   ├── backspaceCtrl.js
│   ├── clickCtrl.js
│   ├── codeBlockCtrl.js
│   ├── containerCtrl.js
│   ├── copyCutCtrl.js
│   ├── deleteCtrl.js
│   ├── enterCtrl.js
│   ├── formatCtrl.js
│   ├── imageCtrl.js
│   ├── indentCtrl.js
│   ├── inlineCtrl.js
│   ├── inputCtrl.js
│   ├── pasteCtrl.js
│   ├── tableCtrl.js
│   └── ...
├── eventHandler/       # 事件分发层
│   ├── event.js        # 事件中心
│   ├── mouseEvent.js
│   ├── keyboard.js
│   ├── clipboard.js
│   ├── dragDrop.js
│   ├── resize.js
│   └── clickEvent.js
├── parser/             # Markdown 解析器
│   ├── index.js
│   ├── rules.js
│   ├── escapeCharacter.js
│   ├── marked/         # 基于 marked 的自定义扩展
│   └── render/         # AST → DOM 渲染
├── renderers/          # 渲染策略
│   └── index.js
├── selection/          # 选区管理
├── marktext/           # 拼写检查
├── prism/              # 代码高亮
└── assets/             # CSS 样式
```

**关键设计决策：**

1. **ContentState 模式**：文档以"块"（block）为单位管理，每个 Markdown 元素（段落、标题、列表、代码块等）是一个状态块。所有编辑操作（回车、退格、粘贴、格式化）都有对应的 Controller。

2. **自研解析器**：基于 `marked` 但深度定制，将 Markdown AST 直接映射为 DOM 树，而非走 innerHTML 替换路线。

3. **事件管道**：`EventCenter` 作为全局事件总线，`MouseEvent`/`Keyboard`/`Clipboard` 等独立处理，通过 `ContentState` 统一协调。

4. **插件系统**：`Muya.plugins` 静态数组，外部可以通过 `Muya.use(Plugin, options)` 注册 UI 插件。

### 1.3 主题系统

主题文件存放在 `src/muya/themes/`：

```
src/muya/themes/
├── default.css         # 亮色主题（13.7KB）
├── prismjs/
│   ├── light.theme.css
│   └── dark.theme.css  # 暗色主题
└── fonts/
    ├── Open Sans 字体集
    └── DejaVu Sans Mono 字体集
```

**CSS 变量驱动**：Marktext 的主题通过 CSS 自定义属性（variables）实现动态切换：

```css
/* 亮色模式变量 */
:root {
  --editorColor: #222;
  --editorColor30: rgba(34, 34, 34, 0.3);
  --editorColor04: rgba(34, 34, 34, 0.04);
  --headingColor: #222;
  --h1Color: #222;
  --h2Color: #222;
  --h3Color: #222;
  --blockquoteTextColor: #666;
  --blockquoteBorderColor: #e5e5e5;
  --linkColor: #428bca;
  --tableBorderColor: #ddd;
  --floatBgColor: #fff;
  --floatBorderColor: #ddd;
  --maskColor: rgba(0, 0, 0, 0.3);
  --editorAreaWidth: 800px;
}

/* 暗色模式切换：通过 JS 在根节点切换 CSS 类 */
[class*="dark"] {
  --editorColor: #ddd;
  --editorColor30: rgba(221, 221, 221, 0.3);
  /* ... 暗色变量值 */
}
```

**要点**：所有 UI 颜色都通过变量引用，切换主题只需重设 20+ 个 CSS 变量。编辑器区域宽度也是变量（`--editorAreaWidth`），可动态调整。

### 1.4 对我们的借鉴意义

| 可借鉴点 | 我们的现状 | 参考价值 |
|----------|-----------|---------|
| CSS 变量主题系统 | 只有暗色/亮色硬编码 | ★★★★★ 极易迁移，推荐立即采用 |
| ContentState 块模型 | 无编辑器，只有对话式输入 | ★★★★ 如果自建编辑器，这是可选路线 |
| 自研解析器的代价 | N/A | ★★ 维护成本高，不建议从头自研 |
| 事件管道模式 | 我们的服务层用路由 | ★★★ 架构思路可参考但不必模仿 |

---

## 2. Notable：极简存储 + CodeMirror + 无限标签层级

### 2.1 项目概况

| 项目 | 值 |
|------|-----|
| 语言 | TypeScript (Electron) |
| Star | ~10k (已归档) |
| 编辑器引擎 | **CodeMirror 5** (react-codemirror2) |
| UI 框架 | React + Svelto (状态管理) |
| 存储 | 纯 MD + YAML frontmatter |
| 许可证 | AGPL-3.0 / MIT (旧版本) |
| 状态 | 已闭源（v1.3.0 为最后一个开源版本） |

### 2.2 编辑器实现

Notable 明确**不采用所见即所得**模式：

```
src/renderer/
├── components/
│   ├── about/
│   ├── cwd/              # 工作目录选择
│   └── main/
│       ├── content/      # 笔记正文
│       ├── editor/       # 编辑器组件
│       ├── note/         # 笔记元数据
│       ├── notes/        # 笔记列表
│       ├── tags/         # 标签侧栏
│       └── titlebar/     # 标题栏
├── containers/
│   └── main/
│       ├── editor.ts     # 编辑器容器
│       ├── tags.ts       # 标签容器
│       ├── notes.ts      # 笔记容器
│       └── ...
└── utils/
    ├── tags.ts           # 标签工具（SEPARATOR = '/'）
    └── ...
```

**依赖链**：

```
package.json dependencies:
├── "codemirror"                 # CodeMirror 5（forked by author）
├── "react-codemirror2"          # React 绑定
├── "react" / "react-dom"        # UI
├── "gray-matter"                # YAML frontmatter 解析
├── "js-yaml"                    # YAML 序列化
├── "overstated"                 # 状态管理
├── "chokidar"                   # 文件监听
└── "prismjs"                    # 代码高亮
```

### 2.3 存储模型：纯 MD + YAML frontmatter

Notable 的存储哲学：**没有私有格式，笔记就是 `.md` 文件**。

**文件示例**：
```markdown
---
title: "我的笔记"
tags: [Notebooks/Tutorial, Tags/写作/技巧]
created: 2025-01-01T00:00:00.000Z
modified: 2025-01-02T00:00:00.000Z
favorited: true
pinned: false
deleted: false
attachments: []
---

# 笔记正文

这是笔记内容……
```

**NoteObj 类型（来自 `src/common/types.ts`）**：
```typescript
type NoteObj = {
  content: string,        // 完整文件内容
  filePath: string,       // 绝对路径
  checksum: number,       // CRC-32 校验
  plainContent: string,   // 去掉 frontmatter 的纯正文
  metadata: {
    attachments: string[],
    created: Date,
    modified: Date,
    deleted: boolean,
    favorited: boolean,
    pinned: boolean,
    stat: fs.Stats,
    tags: string[],       // 标签数组，如 ["Notebooks/Tutorial", "写作/技巧"]
    title: string
  }
};
```

**关键设计决策**：
- `gray-matter` 解析 frontmatter
- `chokidar` 监听文件变更，支持外部修改
- CRC-32 checksum 用于检测冲突
- 无数据库，所有笔记由文件系统驱动

### 2.4 标签系统：无限嵌套（核心亮点）

**数据模型（来自 `types.ts`）**：
```typescript
type TagObj = {
  collapsed: boolean,         // 侧栏折叠状态
  name: string,               // 标签名（单段）
  notes: NoteObj[],           // 属于此标签的笔记列表
  path: string,               // 完整路径，如 "写作/技巧"
  tags: { [name: string]: TagObj }  // 子标签（递归）
};

type TagsObj = {
  [filePath: string]: TagObj  // 顶层标签索引
};
```

**分隔符**：`SEPARATOR = '/'`（定义在 `utils/tags.ts`）

**标签构建逻辑（`containers/main/tags.ts`）**：

```typescript
// 核心算法：将 tags 数组展开为树
tagsAll.forEach(tag => {
  const parts = tag.split('/');  // "写作/技巧" → ["写作", "技巧"]
  const currentParts: string[] = [];

  parts.reduce((tags, tag, index) => {
    currentParts.push(tag);

    if (!tags[tag]) {
      // 首次遇到，创建节点
      const path = currentParts.join('/');
      tags[tag] = { path, name: tag, collapsed, notes: [], tags: {} };
    }

    toggle(tags, tag, !isSpecial);

    return tags[tag].tags;  // 递归进入子标签
  }, tags);
});
```

**特殊虚拟标签**：
| 标签名 | 用途 |
|--------|------|
| `__ALL__` | 全部笔记 |
| `__FAVORITES__` | 收藏笔记 |
| `Notebooks` | 笔记本（一级顶层） |
| `__TAGS__` | 普通标签（二级及以上归入这里） |
| `Templates` | 模板 |
| `__UNTAGGED__` | 未分类 |
| `__TRASH__` | 回收站 |

**用户体验效果**：
- 侧栏展示 `Notebooks > Tutorial`（作为笔记本层级）
- 普通标签 `写作/技巧` 自动在 `Tags > 写作 > 技巧` 展示
- 折叠状态持久化（`collapsed` 字段）
- 标签可同时属于多个分类

---

## 3. Zettlr：FSAL + CodeMirror 6 + 学术工作台

### 3.1 项目概况

| 项目 | 值 |
|------|-----|
| 语言 | TypeScript (Electron) |
| Star | ~13k |
| 编辑器引擎 | **CodeMirror 6** |
| UI 框架 | Vue 3 + Pinia |
| 许可证 | GPL-3.0 |
| 状态 | 活跃开发中，学术写作定位 |

### 3.2 编辑器实现

Zettlr 的编辑器模块位于 `source/common/modules/markdown-editor/`：

```
source/common/modules/markdown-editor/
├── autocomplete/          # 自定义自动补全
├── code-folding/          # 代码折叠
├── commands/              # 编辑器命令
├── context-menu/          # 自定义右键菜单
├── editor-extension-sets.ts  # CodeMirror 6 扩展集（14.6KB）
├── editor.css             # 编辑器样式
└── index.ts               # 编辑器入口
```

**技术栈**：基于 CodeMirror 6 的扩展生态系统：
- `@codemirror/state` — 编辑器状态
- `@codemirror/view` — 编辑器视图
- `@codemirror/commands` — 键盘命令
- `@codemirror/language` — 语言支持
- 自定义 autocomplete 实现

### 3.3 FSAL：File System Abstraction Layer

这是 Zettlr 最值得深入研究的部分。FSAL 位于 `source/app/service-providers/fsal/`：

```
source/app/service-providers/fsal/
├── index.ts              # FSAL 主入口（35KB，核心调度器）
├── fsal-file.ts          # 文件解析 + 缓存
├── fsal-directory.ts     # 目录解析 + 设置
├── fsal-attachment.ts    # 附件管理
├── fsal-code-file.ts     # 代码文件管理
├── fsal-cache.ts         # 缓存适配器
├── fsal-watchdog.ts      # 文件系统监听器
└── util/
    ├── extract-bom.ts    # BOM 检测
    ├── extract-file-id.ts # Zettelkasten ID 提取
    ├── extract-linefeed.ts # 换行符检测
    ├── file-parser.ts    # Markdown 解析 + frontmatter
    └── fs.ts             # 文件系统工具
```

**MDFileDescriptor 数据结构**：
```typescript
type MDFileDescriptor = {
  dir: string,            // 所在目录
  path: string,           // 绝对路径
  name: string,           // 文件名
  ext: string,            // 扩展名
  size: number,           // 文件大小
  id: string,             // Zettelkasten ID
  tags: string[],         // 文件中提取的标签
  links: string[],        // 出站链接
  citekeys: string[],     // 引用键
  bom: string,            // BOM 字符
  type: 'file',
  wordCount: number,
  charCount: number,
  modtime: number,        // 修改时间（毫秒时间戳）
  creationtime: number,   // 创建时间
  linefeed: '\n',
  firstHeading: string | null,
  yamlTitle: string | undefined,
  frontmatter: any        // YAML frontmatter 对象
};
```

**FSAL 缓存策略（关键代码）**：
```typescript
// fsal-file.ts
export async function parse(filePath, cache, parser) {
  // 1. 获取文件元数据（modtime, size 等）
  const metadata = await getFilesystemMetadata(filePath);

  // 2. 检查缓存：modtime 相同则直接使用缓存
  if (await cache?.has(file.path) === true) {
    const cachedFile = await cache?.get(file.path);
    if (cachedFile.modtime === file.modtime && cachedFile.type === 'file') {
      file = applyCache(cachedFile, file);
      hasCache = true;
    }
  }

  // 3. 缓存未命中则完整解析并缓存
  if (!hasCache) {
    let content = await fs.readFile(filePath, 'utf8');
    parser(file, content);  // 外部注入的解析器
    await cacheFile(file, cache);
  }
}
```

**目录设置持久化**：每个目录可以有一个 `.ztr-directory` 文件：
```typescript
const SETTINGS_TEMPLATE = {
  sorting: 'name-up',       // 排序方式
  project: null,             // 项目配置
  icon: null,                // 目录图标
  color: null               // 目录颜色
};
```

**文件系统监听**：`fsal-watchdog.ts` 使用 `chokidar` 或原生 `fs.watch`，在文件变更时触发重新解析。

### 3.4 标签系统

Zettlr 的标签直接从**文件内容**中提取，而非 frontmatter：

- 支持 Markdown 标签语法：`#tag`
- 支持 YAML frontmatter 中的 `tags:` 字段
- 标签在 `MDFileDescriptor.tags` 中以字符串数组存储
- **不支持嵌套层级**（平面标签）

### 3.5 对我们的借鉴意义

| 可借鉴点 | 我们的现状 | 参考价值 |
|----------|-----------|---------|
| FSAL 缓存策略 | 无文件系统抽象层 | ★★★★★ 最值得借鉴的架构 |
| MDFileDescriptor 元数据模型 | 只有基本文件路径 | ★★★★ 可直接复刻数据模型 |
| .ztr-directory 目录配置 | 无目录级配置 | ★★★ 小而美的设计 |
| CodeMirror 6 扩展体系 | 无编辑器 | ★★★★ 推荐用 CM6 而非自研 |
| 文件监听（watchdog） | 无 | ★★★ 实时同步的必要组件 |

---

## 4. 标签系统深度对比：Notable vs 我们的 Tags

### 4.1 Notable 的无限嵌套机制

**实现原理**：
- 标签以字符串数组存储于 frontmatter：`tags: [Notebooks/Tutorial, 写作/技巧/进阶]`
- 分隔符 `/` 将字符串拆分为路径段
- 运行时构建树形结构：`TagObj.tags` 递归嵌套
- 侧栏按树形展开显示

**关键文件**：
- `src/common/types.ts` — TagObj 类型定义
- `src/renderer/utils/tags.ts` — 分隔符和排序工具
- `src/renderer/containers/main/tags.ts` — 标签树的构建逻辑

**标签增删的复杂度**：
- 添加笔记到标签：O(n) 遍历标签路径，n = 路径段数
- 删除笔记：O(n) 遍历路径后移除引用
- 标签树重建：O(m*d) m = 笔记数，d = 平均标签深度

### 4.2 Notable 标签 vs 我们的平面标签

| 维度 | Notable 标签 | 我们的标签（推测） | 差距 |
|------|-------------|-------------------|------|
| **数据结构** | 树状递归 `TagObj.tags` | 平面数组 | ★★★ 根本性差异 |
| **存储方式** | frontmatter `tags: [a/b/c]` | 未知 | ★★ 需对齐 |
| **层级支持** | 任意深度（路径段驱动） | 无层级 | ★★★★★ 核心差距 |
| **虚拟标签** | 7 个特殊标签（ALL/FAVORITES等） | 无 | ★★★ 提升 UX |
| **折叠持久化** | `collapsed` 字段 | 无 | ★★ |
| **侧栏展示** | 树形展开，子标签缩进 | 平面列表 | ★★★★ UX 差距 |
| **搜索范围** | 按标签路径精确/模糊搜索 | 无标签搜索 | ★★★ |

### 4.3 迁移成本评估

从平面标签迁移到 Nestable = 无限层级标签：

**方案 A：轻量级——存储层不变，UI 层模拟树形展示**
- 改动范围：前端 UI 组件
- 存储格式：`tags: [a/b/c]`（字符串数组）
- 后端改动：无
- 工作量：2-3 天
- 缺点：排序和搜索需额外处理，多项目场景下复用性差

**方案 B：中量级——重建 Tag 模型**
- 改动范围：存储层 + 前端
- 新增 TagObj 类型定义
- 新增 `tags` 集合索引（按路径检索）
- 工作量：5-7 天
- 优点：结构清晰，支持多项目

**方案 C：重量级——参考 FSAL + Notable 混合**
- 改动范围：整个写作工坊架构
- 引入 FSAL 式文件系统抽象层
- 文件级 frontmatter 存储
- Tags 作为 frontmatter 字段
- 工作量：15-20 天
- 优点：一劳永逸，同时解决编辑器、存储、标签三大问题

**推荐路径**：**方案 B** — 存储层保持简单，引入 TagObj 模型，前端树形展示。FSAL 作为后续独立项目引入。

---

## 5. 综合分析与迁移建议

### 5.1 三个项目的横向对比

| 维度 | Marktext | Notable | Zettlr |
|------|----------|---------|--------|
| **编辑器** | 自研 Muya (WYSIWYG) | CodeMirror 5 (源码编辑) | CodeMirror 6 (源码编辑) |
| **编辑模式** | 所见即所得 | 源码 + 预览分屏 | 源码 + 侧边预览 |
| **自研程度** | 极深（全栈自研） | 浅（依赖成熟库） | 中（部分自研扩展） |
| **存储** | 单文件 + 项目目录 | 纯 MD + YAML frontmatter | 纯 MD + YAML frontmatter |
| **文件系统层** | 简单目录扫描 | chokidar 监听 | 完整 FSAL + 缓存 |
| **标签** | 无标签系统 | 无限嵌套（/分隔） | 平面标签（从内容提取） |
| **主题** | CSS 变量驱动 | 暗色/亮色 | 用户可自定义 CSS |
| **性能考量** | 大文件拖慢 | 文件量大时启动慢 | FSAL 缓存缓解 |
| **定位** | Typora 替代品 | 极简笔记 | 学术写作 |

### 5.2 对我们的建议（按优先级排序）

**P0 — 立即实施**：
1. **CSS 变量主题系统** — 从 Marktext 主题系统直接复刻。把颜色值抽成变量，支持 light/dark 一键切换。工作量：1 天
2. **标签路径化存储** — 将平面标签改为 `/` 分隔的路径字符串，保持向后兼容。工作量：2 天

**P1 — 短期（1-2 周）**：
3. **TagObj 树形模型** — 引入 Notable 风格的递归标签结构，侧栏树形展示。工作量：5 天
4. **编辑器集成（CodeMirror 6）** — 参考 Zettlr 的 CM6 集成，作为"编辑器标签页"的基础。工作量：7 天

**P2 — 中期（3-4 周）**：
5. **FSAL 文件系统抽象层** — 参考 Zettlr 的 FSAL 架构，引入缓存 + 文件监听 + 元数据管理。工作量：10 天
6. **YAML frontmatter 标准化** — 所有笔记文件统一 frontmatter 格式。工作量：3 天
7. **目录级设置（.ztr-directory）** — 每个写作项目目录可独立配置。工作量：2 天

**P3 — 长期**：
8. **所见即所得编辑器** — 如果决定自建，参考 Muya 的 ContentState 设计模式。不建议优先
9. **图数据库标签索引** — 大规模标签体系下改用图数据库。目前不需要

### 5.3 风险提示

1. **自研编辑器的代价**：Marktext 的 Muya 引擎约 30k+ 行 JS，维护成本极高。我们的场景强烈建议 **CodeMirror 6**。
2. **Notable 的闭源教训**：Notable 已闭源，v1.3.0 是最后一个可用版本。标签系统逻辑可以借鉴但不要直接复制。
3. **FSAL 复杂度的权衡**：Zettlr 的 FSAL 代码约 100k+ 行，对小型项目可能过度设计。建议只抽取缓存 + 文件监听 + 元数据三层。
4. **CI 和测试**：所有的编辑器改动都需要配套的测试，否则拼写渲染很容易崩。

### 5.4 架构路线图

```
Phase 1（当前）：对话式交互 + 文件级管理
    ↓
Phase 2（1-2周）：编辑器标签页（CM6）+ 层级标签树（Notable 风格）
    ↓
Phase 3（3-4周）：FSAL 抽象层 + frontmatter 标准化 + 缓存
    ↓
Phase 4（长期）：Project 级设置 + 多分屏 + 高性能搜索
```

---

## 附录：参考源码位置

| 项目 | 关键路径 |
|------|---------|
| Marktext 编辑器 | `src/muya/lib/` (index.js, contentState/, eventHandler/, parser/) |
| Marktext 主题 | `src/muya/themes/default.css` |
| Notable 标签 | `src/renderer/containers/main/tags.ts` |
| Notable 类型 | `src/common/types.ts` |
| Notable 标签工具 | `src/renderer/utils/tags.ts` |
| Notable 存储 | `src/common/` (config.ts, settings.ts) |
| Zettlr FSAL 主入口 | `source/app/service-providers/fsal/index.ts` |
| Zettlr FSAL 文件 | `source/app/service-providers/fsal/fsal-file.ts` |
| Zettlr FSAL 目录 | `source/app/service-providers/fsal/fsal-directory.ts` |
| Zettlr FSAL 缓存 | `source/app/service-providers/fsal/fsal-cache.ts` |
| Zettlr 编辑器 | `source/common/modules/markdown-editor/` |
| Zettlr 文件解析器 | `source/app/service-providers/fsal/util/file-parser.ts` |

---

*报告结束。建议下一阶段直接从 Phase 2 开始：CM6 编辑器 + 层级标签树。*
