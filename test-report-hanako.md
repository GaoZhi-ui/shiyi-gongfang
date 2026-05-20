# 拾遗工坊 · 软件测试报告

> 测试日期：2026-05-20 23:31 (GMT+8)
> 测试地址：http://127.0.0.1:8866
> 测试范围：写作相关功能 API
> 测试工具：curl + Python3 urllib

---

## 1. 写法引擎 — style_list / style_analyze

| 属性 | 值 |
|------|-----|
| **端点** | `POST /api/v1/tools/{name}/call` |
| **说明** | 原始计划中的 `/api/v1/tools/call` 不存在，正确路径为 `/api/v1/tools/{name}/call`，负载格式 `{"args":{...}}` |

### 1.1 style_list（无参数）

- **请求**：`POST /api/v1/tools/style_list/call`，`{"args":{}}`
- **响应状态码**：`200 OK`
- **响应结构正常**：`{"content": [...], "isError": false, "meta": {"total": 3}}`
- **返回数据**：3 种写作风格，每项含 `name`、`description`、`rules[]`、`profile`、`sample_text`
  - 冷峻克制（《泰拉拾遗录》主力风格）
  - 轻快日常
  - 严肃叙事
- **异常**：无

### 1.2 style_analyze（带文本）

- **请求**：`POST /api/v1/tools/style_analyze/call`，`{"args":{"text":"一段示例文字，用于测试风格分析功能。"}}`
- **响应状态码**：`200 OK`
- **响应结构正常**：`{"content": [...], "isError": false, "meta": {"total_styles": 3, "best_match": "冷峻克制", "best_score": 69.2}}`
- **返回数据**：每种风格评分 + 详细维度（句子长度匹配度、对话密度匹配度、禁用词命中等）+ 文本特征统计（CJK 字数、平均句长等）
- **异常**：中文/引号在 curl shell 中容易导致 JSON 解析错误，建议使用 Python 或文件传参

---

## 2. AI对话 — chat/completions

| 属性 | 值 |
|------|-----|
| **端点** | `POST /api/v1/chat/completions`（原始任务为 `/api/v1/chat`，实际路径不同） |

- **请求**：`POST /api/v1/chat/completions`，`{"messages":[{"role":"user","content":"..."}], "stream":false}`
- **响应状态码**：`503 SERVICE_UNAVAILABLE`
- **响应内容**：`{"detail":{"code":"SERVICE_UNAVAILABLE","message":"key_manager 尚未实现","suggestion":"请实现 services/key_manager.py"}}`
- **结论**：AI 对话功能**不可用**——后端依赖 key_manager 服务来管理 API Key（如 DeepSeek/OpenAI 等），该模块尚未实现。
- **API 路由和请求格式正确**，返回了有意义的错误信息，属于合理的功能未就绪状态。
- **元数据**：支持 model/mode/stream/temperature/max_tokens/system_prompt 等参数

---

## 3. 场景管理 — CRUD

| 属性 | 值 |
|------|-----|
| **端点** | `POST/GET /api/v1/scenes/{chapter_id}` |
| **前置** | 需要先有项目 + 章节 |

### 3.1 创建场景

- **前置操作**：
  - 创建项目：`POST /api/v1/projects` → `201`（id: `b53bebd08552`，template: `novel`）
  - 创建章节：`POST /api/v1/chapters` → `201`（filename: `第1章_测试章节.md`）
- **请求**：`POST /api/v1/scenes/{chapter_id}`，`{"title":"开篇场景","summary":"...","status":"draft","word_count":0}`
- **响应状态码**：`201 Created`
- **返回数据**：包含 `id`、`chapter_id`、`title`、`status`、`order`、`created_at`、`updated_at`
- **异常**：URL 中含中文需要 URL 编码，否则 Python urllib 报 ASCII 编码错误

### 3.2 列出场景

- **请求**：`GET /api/v1/scenes/{chapter_id}`
- **响应状态码**：`200 OK`
- **返回数据**：场景数组（含刚创建的场景），带完整字段
- **异常**：无

---

## 4. 写作工作流 — Stage Pipeline

| 属性 | 值 |
|------|-----|
| **端点** | `GET /api/v1/workflow`、`PUT /api/v1/workflow`、`GET /api/v1/workflow/history` |
| **说明** | 原始任务为 `POST /api/v1/workflow`，实际为 GET（读取）/ PUT（更新） |

### 4.1 获取工作流状态

- **请求**：`GET /api/v1/workflow`
- **响应状态码**：`200 OK`
- **返回数据**：完整 8 阶段流水线
  - 阶段 0: 未开始
  - 阶段 1: 写前分析
  - 阶段 2: 写作
  - 阶段 3: 自检清单（含 7 项 checklist）
  - 阶段 3.3: 自动检查
  - 阶段 3.5: 文本润色
  - 阶段 4: 修订
  - 阶段 5: 章末元数据
  - 阶段 6: 知识库同步（含 6 项 checklist）
  - 阶段 7: 发布
- **异常**：无

### 4.2 更新工作流

- **请求**：`PUT /api/v1/workflow`，`{"current_stage": 1, "active_chapter": "第1章_测试章节.md"}`
- **响应状态码**：`200 OK`
- **返回数据**：`{"status":"ok", "current_stage":1.0, "current_stage_name":"写前分析", "changes":["..."]}`
- **异常**：无

### 4.3 工作流历史

- **请求**：`GET /api/v1/workflow/history`
- **响应状态码**：`200 OK`
- **返回数据**：历史记录数组，含 action/stage/detail/timestamp
- **异常**：无

---

## 5. 伏笔追踪 — Foreshadowing

| 属性 | 值 |
|------|-----|
| **端点** | `POST /api/v1/foreshadowing`、`GET /api/v1/foreshadowing` |

### 5.1 创建伏笔

- **请求**：`POST /api/v1/foreshadowing`
- **负载**：`{"project_id":"b53bebd08552", "title":"神秘的信件", "type":"object", "chapter_planted":1, "chapter_expected":5, "status":"pending", "strength":3, ...}`
- **响应状态码**：`201 Created`
- **返回数据**：含自动计算的 `gap`（章节差 = 4）、完整字段
- **注意**：`status` 可选值仅为 `{'revealed', 'resolved', 'pending', 'abandoned'}`，非 `'active'`
- **异常**：第一次测试传了 `"active"`，返回 422 验证错误——错误信息清晰，符合预期

### 5.2 列出伏笔

- **请求**：`GET /api/v1/foreshadowing?project_id=b53bebd08552`
- **响应状态码**：`200 OK`
- **返回数据**：伏笔数组（含刚创建的条目）
- **注意**：`project_id` 为必填查询参数，不传则返回 422
- **异常**：无

---

## 6. 知识库 — Knowledge

| 属性 | 值 |
|------|-----|
| **端点** | `GET /api/v1/knowledge`、`GET /api/v1/knowledge/{filepath}`、`POST /api/v1/tools/knowledge_read/call` |

### 6.1 列出知识库文件

- **请求**：`GET /api/v1/knowledge`
- **响应状态码**：`200 OK`
- **返回数据**：21 个知识文件，每项含 `name`、`title`、`size`、`modified`、`cjk_chars`
- **base_path**：`E:\openhanako-work\knowledge_base\泰拉拾遗录`
- **异常**：无

### 6.2 读取知识文件（REST API）

- **请求**：`GET /api/v1/knowledge/MC0729地点索引.md`（需 URL 编码）
- **响应状态码**：`200 OK`
- **返回数据**：文件完整内容
- **异常**：文件名需与磁盘实际文件名完全一致（大小写、编码）

### 6.3 读取知识文件（Tool API）

- **请求**：`POST /api/v1/tools/knowledge_read/call`，`{"args":{"path":"MC0729地点索引.md"}}`
- **响应状态码**：`200 OK`
- **返回格式**：MCP 风格的 `{"content":[{"type":"text","text":"..."}]}` 结构
- **异常**：无

---

## 总体统计

| 指标 | 数值 |
|------|------|
| 测试 API 端点数 | 11 |
| 通过（200/201） | 9 |
| 不可用（503） | 1（AI对话，因 key_manager 未实现） |
| 验证错误（422） | 1（伏笔 status 参数错误，已纠正） |
| 404 | 1（知识库文件路径拼写不匹配，已纠正） |
| 路由发现差异 | 3 处（tools/call、chat、workflow 端点与原始计划不同） |

### 发现的注意点

1. **路由差异**：写作相关功能 API 实际路径与原始任务描述有出入（tools/{name}/call 而非 tools/call，chat/completions 而非 chat），说明基础设施较新或文档有漂移
2. **AI对话不可用**：依赖 `services/key_manager.py` 尚未实现，需后续开发
3. **编码处理**：URL 中的中文路径需要 URL 编码（Python urllib 的 ASCII 限制），建议前端统一处理
4. **知识库文件读取**：文件名必须精确匹配磁盘，建议在列表 API 中提供可直接用的 path
5. **伏笔状态枚举**：不常见取值 `revealed/resolved/pending/abandoned`，文档需要明确
6. **工作流流水线完整**：8 阶段 + 2 个 checklist 子集，结构严谨，支持变更历史追踪
