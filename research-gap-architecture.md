# 开源写作工具架构深度对比分析

> 研究日期：2026-05-21
> 分析目标：Outline、AppFlowy、Standard Notes、HedgeDoc
> 对比维度：数据模型、存储方案、实时协作、加密安全

---

## 一、项目概览

| 维度 | Outline | AppFlowy | Standard Notes | HedgeDoc |
|------|---------|----------|---------------|----------|
| **定位** | 团队 Wiki / 知识库 | Notion 开源替代（本地优先） | 端到端加密笔记 | 实时协作 Markdown 编辑器 |
| **前端** | React (Slate 编辑器) | Flutter | TypeScript + React (Web) / React Native (Mobile) | React (HedgeDoc 2) |
| **后端** | Node.js + Koa | Rust (核心逻辑) + 可选云服务 | Node.js + Express | Node.js + Express (1.x) / NestJS (2.x) |
| **数据库** | PostgreSQL + Redis + S3 | SQLite (本地) / PostgreSQL (云端) | MySQL / SQLite (自托管) | PostgreSQL / MySQL / SQLite |
| **开源协议** | BSL 1.1 | AGPL-3.0 | AGPL-3.0 | AGPL-3.0 |
| **Star** | ~30k+ | ~50k+ | ~10k+ (app) | ~5k+ |

---

## 二、数据模型对比

### 2.1 Outline：集合-文档树

```
Collection (集合)
├── Document (文档, 根节点)
│   ├── Child Document (子文档)
│   │   ├── Text Block (文本块)
│   │   ├── Heading Block (标题块)
│   │   └── ...
│   └── Child Document
└── Document
```

Outline 的数据模型核心是一棵**嵌套文档树**：
- **Collection** 是最顶层组织单位，相当于"文件夹"或"知识库"
- **Document** 是实际内容载体，可无限嵌套子文档
- **编辑器的数据模型**基于 Slate.js 的 JSON 格式：每个文档由一系列 Block 构成，每个 Block 有 type 和 children
- **元数据**独立存储：标题、描述、标签、创建时间、最后编辑者、权限等存储在 PostgreSQL 的独立表中
- **全文索引**通过 PostgreSQL 的 tsvector 实现

**可借鉴的点**：Block-based 数据模型 + 独立元数据表的分离设计。元数据放在关系型数据库便于查询，正文内容用 JSON 格式灵活存储。

### 2.2 AppFlowy：四层嵌套

```
Workspace (工作空间)
├── App (应用)
│   ├── View (视图)
│   │   ├── TextEditor (文本编辑器)
│   │   ├── Grid (表格)
│   │   └── Board (看板)
│   └── View
└── App
```

AppFlowy 的数据模型分为四层抽象：
- **Workspace** → **App** → **View** → **具体视图类型**
- **Rust 端的 crate 划分**直接对应数据模型：
  - `flowy-folder`：管理 Workspace / App / View 的层次结构
  - `flowy-document`：文档内容持久化
  - `flowy-grid`：Grid 视图操作
- **JSON schema 驱动**：每种视图类型有独立的 protobuf schema 定义
- **Content** 与 **Meta** 分离：View 记录结构信息，具体内容由对应 crate 管理

**可借鉴的点**：视图类型抽象（TextEditor / Grid / Board 统一为 View），方便扩展新的视图类型。Rust 端 crate 与数据模型一一对应。

### 2.3 Standard Notes：扁平 Item 模型

```
Item (统一模型)
├── Note (笔记: content 字段含加密文本)
├── Tag (标签: 引用 Note)
├── ItemsKey (密钥项)
├── Preferences (偏好设置)
└── ...

每个 Item 的结构:
{
  uuid: string,
  content: string (加密),
  content_type: string (Note/Tag/etc),
  encrypted_item_key: string,
  items_key_id: string,
  created_at, updated_at: timestamp
}
```

Standard Notes 的**数据模型极其简洁**：
- 所有实体统一为 **Item**，通过 `content_type` 区分类型
- 没有嵌套结构，所有笔记扁平存放
- **Tag 通过引用关系连接 Note**，形成非强制性的分类
- 这种设计简化了加密：只需一种序列化 / 加密 / 同步策略
- 查询全靠客户端本地过滤（全量下载后解密）

**可借鉴的点**：统一 Item 模型让端到端加密的实现成本大幅降低。缺点是服务器端无法做复杂查询。

### 2.4 HedgeDoc：独立笔记模型

```
Note
├── publicId (128-bit base32, 唯一标识)
├── aliases[] (自定义别名)
├── title / description / tags (从 frontmatter 提取)
├── content (Markdown 文本)
├── revisions[] (变更历史)
├── owner (用户引用)
├── groupPermissions[] (组权限)
├── userPermissions[] (用户权限)
├── authorColors[] (协作作者颜色标记)
└── viewCount
```

HedgeDoc 的数据模型是**以 Note 为中心的独立模型**：
- 每条笔记独立，不强制嵌套或组织（可选的 Tag 分类）
- **publicId** 是核心标识，alias 作为可读的 URL 备选
- 笔记内容就是纯 Markdown 文本 + frontmatter（YAML 元数据头）
- **权限与内容分离**：groupPermissions / userPermissions 独立存储
- HedgeDoc 2.0 增加 `version` 字段区分 1.x 遗留笔记

**可借鉴的点**：frontmatter + markdown 的组合是"纯文本友好"的极佳选择；publicId + alias 的设计兼顾了安全性和可读性。

### 2.5 数据模型对比总结

| 维度 | Outline | AppFlowy | Standard Notes | HedgeDoc |
|------|---------|----------|---------------|----------|
| 结构类型 | 嵌套树形 | 四层嵌套 | 扁平 Item | 独立笔记 |
| 内容格式 | Slate JSON (Block) | Protobuf / JSON | 加密文本 | Markdown + Frontmatter |
| 元数据 | 独立表存储 | 独立层存储 | content 字段内 | DB 字段 + frontmatter |
| 组织方式 | Collection → Document → 子文档 | Workspace → App → View | Tag 引用 | Alias + Tag |
| 查询能力 | PostgreSQL 全文搜索 | SQLite 本地查询 | 客户端全量过滤 | 服务端 tag 搜索 |

---

## 三、存储方案对比

### 3.1 Outline：Server-side 三组件

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  PostgreSQL   │    │    Redis     │    │     S3       │
│  (主数据)     │    │  (缓存/队列)  │    │  (附件存储)   │
│              │    │              │    │              │
│ - 文档元数据  │    │ - Session    │    │ - 图片       │
│ - 用户/团队   │    │ - 缓存查询   │    │ - 文件附件   │
│ - 全文索引    │    │ - 任务队列   │    │ - 导出文件   │
│ - 权限        │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
```

- **全部数据存储在服务端**，客户端是薄 shell
- PostgreSQL 承担关系数据 + 全文搜索（tsvector）
- Redis 用于 session 管理、缓存热数据、Bull 任务队列
- S3 协议兼容的对象存储用于附件，减轻数据库压力
- **备份策略**：PostgreSQL dump + S3 快照

### 3.2 AppFlowy：Local-first + SQLite

```
┌─────────────────────────────────────┐
│           AppFlowy Client           │
│  ┌──────────────┐ ┌──────────────┐  │
│  │  Flutter UI   │ │  Rust Core   │  │
│  │  (Dart)      │◄┤  (FFI/IPC)   │  │
│  └──────────────┘ └──────┬───────┘  │
│                          │          │
│                    ┌─────▼──────┐   │
│                    │   SQLite   │   │
│                    │  (本地DB)  │   │
│                    └────────────┘   │
└─────────────────────────────────────┘
          │ (可选同步)
          ▼
    ┌──────────┐
    │  Cloud   │
    │ (PostgreSQL)
    └──────────┘
```

- **Local-first 架构**：所有数据先在本地 SQLite 写入，再异步同步到云端
- **Rust 端负责所有 IO**：文件系统操作、数据库读写、网络请求
- **Flutter 端零 IO**：通过 protobuf 序列化的消息与 Rust 端通信
- **可选的 AppFlowy Cloud**：基于 PostgreSQL 的云同步服务（正在完善）
- 离线可完全使用，联网后自动同步

### 3.3 Standard Notes：加密同步

```
┌──────────────┐         ┌──────────────┐
│   客户端      │         │   服务端      │
│              │ HTTPS   │              │
│ ┌──────────┐ │◄───────►│ ┌──────────┐ │
│ │ 本地数据库 │ │  加密   │ │  MySQL   │ │
│ │ (SQLite)  │ │   Item  │ │ (encrypted│ │
│ │ (加密存储) │ │   Syncing│ │  blobs)  │ │
│ └──────────┘ │         │ └──────────┘ │
│              │         │              │
│ ┌──────────┐ │         │ ┌──────────┐ │
│ │ Keychain  │ │         │ │   S3     │ │
│ │ (本地密钥)│ │         │ │ (附件)   │ │
│ └──────────┘ │         │ └──────────┘ │
└──────────────┘         └──────────────┘
```

- **客户端加密，服务端盲存储**：服务器不知道也不解密任何内容
- **本地 SQLite** 保存已解密的明文（有 passcode 时额外加密）
- **服务端 MySQL** 只存加密后的 blob
- **S3 兼容存储**用于加密的文件附件
- **同步协议**：客户端全量拉取后本地 diff，增量推送

### 3.4 HedgeDoc：标准服务端存储

```
┌──────────────┐    ┌──────────────┐
│   HedgeDoc   │    │  Database    │
│   (Node.js)  │    │ (Pg/MySQL/   │
│              │    │  SQLite)     │
│ - REST API   │◄──►│              │
│ - Socket.io  │    │ - Notes      │
│ - Yjs server │    │ - Revisions  │
│ - Auth       │    │ - Users      │
│              │    │ - Permissions│
│ ┌──────────┐ │    └──────────────┘
│ │   S3     │ │
│ │(Media/Img)│ │
│ └──────────┘ │
└──────────────┘
```

- 常规服务端存储，支持 PostgreSQL / MySQL / SQLite
- **Note 内容**直接存储在数据库（纯文本 markdown）
- **Media/uploads** 通过本地文件系统或 S3
- 2.0 版本有更灵活的存储抽象层
- 版本历史（revisions）存储在数据库内

### 3.5 存储方案对比总结

| 维度 | Outline | AppFlowy | Standard Notes | HedgeDoc |
|------|---------|----------|---------------|----------|
| 架构模式 | Server-side | Local-first + 可选云 | Client-side + 加密同步 | Server-side |
| 离线能力 | 弱（依赖网络） | 强（本地优先） | 强（全量本地） | 中（需同步） |
| 本地数据库 | 无 | SQLite | SQLite (加密) | 无 |
| 服务端存储 | PostgreSQL + Redis + S3 | PostgreSQL (可选云) | MySQL + S3 | Pg/MySQL/SQLite |
| 扩展存储 | S3 对象存储 | Rust 端 IO | S3 附件 | S3/本地 |
| 备份方式 | DB dump + S3 快照 | 文件复制 | 加密备份导出 | DB dump |

---

## 四、实时协作对比

### 4.1 Outline：无实时协作

Outline **没有真正意义上的实时协作编辑**。它采用传统的"保存后同步"模型：

- **非 OT/CRDT**：不解决多用户光标冲突
- **锁机制**：文档编辑时有 "editing" 状态提示，避免多人同时编辑
- **协作方式**：评论、@提及、共享链接、权限控制
- **变更历史**：所有修改都有版本记录，可回滚
- **更新推送**：通过 WebSocket 推送"文档已更新"通知，不推送内容差分

**原因**：Outline 定位为 Wiki/知识库，而非实时协作的文档编辑器。用户场景偏向独立编辑后共享，非多人同时写一个文档。

### 4.2 AppFlowy：基础协作（仍在完善）

AppFlowy 的实时协作功能**仍在开发中**：

- **当前状态**：支持页面分享和基础同步，多人编辑功能有限
- **同步机制**：Event-driven 架构，通过 protobuf 消息传递变更
- **未采用 CRDT/OT**：更接近"最后写入胜出 + 手动冲突解决"
- **未来方向**：AppFlowy Cloud 正在实现真正的实时协作

**关键发现**：AppFlowy 的 Rust + Flutter IPC 架构天然适合协作——所有变更都通过序列化的消息传递，增加 CRDT 层理论上只影响 Rust 端的 sync crate。

### 4.3 Standard Notes：同步而非协作

Standard Notes **不支持实时协作编辑**：

- **同步模型**：客户端驱动，全量拉取 → 本地修改 → 增量推送
- **冲突处理**：基于时间戳的最后写入胜出（Last Write Wins）
- **协作功能**：仅支持笔记分享（只读或编辑），通过服务器中转加密后的 Item
- **不适用 CRDT 原因**：端到端加密下，服务器无法参与冲突解决

### 4.4 HedgeDoc：真正的实时协作

HedgeDoc 是四个项目中**实时协作能力最强的**：

**HedgeDoc 1.x**：
- **Socket.io** 实现实时双向通信
- 基于 **OT（Operational Transformation）** 的实时同步
- 服务端作为 operation 的中央协调节点
- 每个编辑操作都经过服务端验证和转发

**HedgeDoc 2.0**（正在开发中）：
- 从 OT 迁移到 **Yjs（CRDT-based）**
- 去中心化的数据结构，更自然的离线支持
- 服务端只需要负责持久化和转发，不需要理解操作语义
- 更好的冲突解决和 undo/redo 支持
- 前端使用 EventEmitter2 事件系统解耦组件

**权限与协作的组合**：
- 编辑中实时显示在线协作者光标（authorColors）
- 权限控制颗粒度：组权限 + 用户权限（additive 模式）
- owner 拥有绝对控制权（删除、修改 alias、清空 revision）

### 4.5 实时协作对比总结

| 维度 | Outline | AppFlowy | Standard Notes | HedgeDoc |
|------|---------|----------|---------------|----------|
| 实时协作 | 无 | 基础版（开发中） | 无 | 强（OT 1.x / Yjs 2.x） |
| 冲突解决 | 保存后覆盖 | 最后写入胜出 | 最后写入胜出 | OT/CRDT 自动合并 |
| WebSocket | 通知推送 | IPC 内部通信 | 无 | Socket.io (1.x) |
| 协作者光标 | 无 | 无 | 无 | 有（authorColors） |
| 离线编辑 | 不支持 | 支持 | 支持 | Yjs 天然支持 |
| 加密冲突 | 不加密 | 不加密 | E2E 限制协作 | 不加密 |

---

## 五、加密安全对比

### 5.1 Outline：传输加密 + 存储加密

- **传输层**：HTTPS
- **存储层**：数据库无内置加密（依赖部署环境）
- **密码存储**：bcrypt 哈希
- **会话管理**：Redis session store
- **SSO 认证**：OIDC / Slack / Google 代理认证
- **无端到端加密**：服务端可读所有数据

### 5.2 AppFlowy：本地安全优先

- **本地存储**：SQLite 文件无内置加密（依赖操作系统文件权限）
- **传输层**：HTTPS（AppFlowy Cloud）
- **认证**：JWT token 机制
- **架构优势**：所有数据在本地 Rust 端处理，攻击面小
- **无端到端加密**（设计上可选，但未实现）

### 5.3 Standard Notes：端到端加密（行业标杆）

Standard Notes 的加密体系是所有项目中**最完善的**，基于 **Protocol 004**：

**加密算法**：
- XChaCha20-Poly1305（非对称 AEAD 加密）
- Argon2id（密码 stretching KDF）
- HMAC-SHA256（数据完整性签名）

**三层密钥体系**：

```
用户密码
    │
    ▼ Argon2id KDF
    │
Root Key (128-bit)
    ├── 前半: Master Key (64-bit) ──► 留在本地，从不发送
    │
    ├── 后半: Server Password (64-bit) ──► 发送到服务器验证身份
    │
    ▼ 加密 ItemsKeys
    │
Items Key (随机生成, 每个 protocol version 一个)
    │
    ▼ 加密 Item Key (每个笔记随机生成)
    │
    ▼ 加密笔记内容
```

**关键设计**：

1. **密钥层级分离**：Root Key 变化时只重加密 ItemsKeys（KB 级），而非全部笔记（MB/GB 级）
2. **Progressive Re-encryption**：协议升级不一次性重加密全部数据，用户修改时渐进完成
3. **Root Key Wrapping**：可选本地密码（passcode）额外包裹 Root Key，实现 Web 浏览器中的安全存储
4. **Strict Sign In (SSI)**：可选的严格模式，拒绝降级攻击（恶意服务器报低版本协议）
5. **零知识证明**：服务器完全无法读取任何数据，包括元数据中的标题（也在加密 content 中）

**第三方审计**：已完成多次独立安全审计，代码完全公开。

### 5.4 HedgeDoc：基本安全措施

- **传输层**：HTTPS
- **认证**：OIDC / LDAP / 内置用户系统
- **权限**：owner / group / user 三级权限，additive 模型
- **无端到端加密**：服务端可读所有笔记内容
- **部署安全**：自托管可搭配反向代理 + 防火墙

### 5.5 加密安全对比总结

| 维度 | Outline | AppFlowy | Standard Notes | HedgeDoc |
|------|---------|----------|---------------|----------|
| 端到端加密 | 无 | 无 | **有** (XChaCha20-Poly1305) | 无 |
| 密码保护 | bcrypt | bcrypt | Argon2id | bcrypt |
| 数据签名 | 无 | 无 | HMAC-SHA256 | 无 |
| 零知识服务端 | 否 | 否 | **是** | 否 |
| 安全审计 | 无公开 | 无公开 | **有 (第三方)** | 无公开 |
| 自托管 | 是 | 是 | 是 | 是 |

---

## 六、核心架构模式摘要

### Outline 可借鉴
- **Block-based 编辑器数据模型**：Slate.js JSON 结构化文档，灵活扩展
- **Collection → Document 嵌套树**：直观的知识库组织
- **PostgreSQL tsvector 全文搜索**：成熟的全文索引方案
- **三组件存储分离**：PostgreSQL（结构数据）、Redis（缓存/队列）、S3（附件）

### AppFlowy 可借鉴
- **Local-first 架构**：离线可用，用户完全掌控数据
- **Rust 后端 + Flutter 前端的 IPC 模式**：protobuf 序列化的 Event/Notification 机制
- **Workspace → App → View 数据抽象**：统一的视图层，Grid/Board/TextEditor 统一为 View
- **Crate 模块化**：功能模块（folder/database/document/grid）各自独立 crate

### Standard Notes 可借鉴
- **三层密钥体系**：Root Key → Items Keys → Item Keys，性能与安全的平衡
- **统一 Item 模型**：所有实体用同一加密/同步流程，简化工程
- **Progressive Re-encryption**：协议升级时数据的渐进式迁移策略
- **编辑器插件化**：Plain → In-house → Derived/Third-party 三层编辑器体系

### HedgeDoc 可借鉴
- **OT → CRTD (Yjs) 迁移路径**：从中央协调到去中心化的演进经验
- **Frontmatter + Markdown**：内容 + 元数据的纯文本文档模型
- **EventEmitter2 事件系统**：服务端模块解耦
- **Additive 权限模型**：组权限 + 用户权限叠加，灵活管理

---

## 七、差距分析总结

### 7.1 综合对比雷达

```
                Outline   AppFlowy   StdNotes   HedgeDoc
数据模型          ██████    ███████    ████      █████
存储方案          ██████    ███████    ██████    █████
实时协作          ██        ███        █         ███████
加密安全          ██        ██         ████████  ██
自托管能力        ███████   ███████    ████████  ███████
性能              ███████   ███████    ██████    █████
离线能力          █         ███████    ███████   ██
```

### 7.2 关键可借鉴架构模式

1. **写时组合，读时分离**：AppFlowy 的 View 抽象 + Standard Notes 的扁平 Item 模型，内容与结构分离
2. **三层密钥架构**：Standard Notes 的分层加密，最小化密码变化时的 re-encrypt 代价
3. **Local-first + CRDT 同步**：HedgeDoc 2.0 的 Yjs 方案 + AppFlowy 的本地优先设计
4. **Block 编辑器 + Markdown fallback**：Outline 的 Slate JSON 内容模型 + HedgeDoc 的纯文本兼容

### 7.3 当前项目的架构缺口

| 需求 | 最佳参考 | 差距 |
|------|---------|------|
| 实时协作 | HedgeDoc Yjs | 需要自建 CRDT 层或集成 Yjs |
| 端到端加密 | Standard Notes | 需要实现三层密钥体系 |
| 本地优先 | AppFlowy | 需要 Rust/Python 本地数据层 |
| 树形文档组织 | Outline | 嵌套 JSON 模型 + PostgreSQL 查询 |
| 插件系统 | Standard Notes | 编辑器沙箱 + 安全权限控制 |

---

## 参考来源

- Outline GitHub: https://github.com/outline/outline
- AppFlowy GitHub: https://github.com/AppFlowy-IO/AppFlowy
- AppFlowy Architecture Docs: https://docs.appflowy.io/docs/documentation/software-contributions/architecture
- Standard Notes GitHub: https://github.com/standardnotes/app
- Standard Notes Encryption Whitepaper: https://standardnotes.com/help/security/encryption
- HedgeDoc GitHub: https://github.com/hedgedoc/hedgedoc
- HedgeDoc 2 Docs: https://docs.hedgedoc.dev/
- "从零开始使用 Outline": https://sspai.com/post/68618
- "AppFlowy 开源笔记工具完全指南": https://blog.csdn.net/Java_superman822/article/details/159473663
