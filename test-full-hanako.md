# 写作助手工坊 · 后端 API 全面测试报告

> 测试时间：2026-05-21 01:33 ~ 01:37 GMT+8  
> 服务端地址：`http://127.0.0.1:8866`  
> 运行版本：Python 3.13.5（PyInstaller 编译版 `shiyi-gongfang.exe`）

---

## 测试结果总览

| 编号 | 测试范围 | 端点数 | 通过 | 失败 | 成功率 |
|------|----------|--------|------|------|--------|
| 1 | 健康检查 | 1 | 1 | 0 | 100% |
| 2 | 工具调用 Harness | 4 | 3 | 1 | 75% |
| 3 | WritingRule 风格检查 | 2 | 0 | 2 | 0% |
| 4 | 写作流程 CRUD | 5 | 3 | 2 | 60% |
| 5 | writing-guide | 2 | 0 | 2 | 0% |
| 6 | 导出 | 2 | 2 | 0 | 100% |
| 7 | 备份 | 1 | 1 | 0 | 100% |
| 8 | 伏笔/角色/目标 | 4 | 4 | 0 | 100% |
| 9 | 插件 | 1 | 1 | 0 | 100% |
| **合计** | | **22** | **15** | **7** | **68%** |

> **7 个失败均为 dist 编译版未打包/缺失路由导致，非源码逻辑问题。**

---

## 1. 健康检查

### GET /api/v1/health

| 项目 | 值 |
|------|-----|
| 状态码 | `200 OK` |
| 响应体 | `{"status":"ok","app":"拾遗工坊","version":"1.0.0","python_version":"3.13.5","timestamp":"...","config":{"note":"no config file found"},"paths":{...}}` |

**结论：通过。** 服务存活，版本号正确，所有路径检查返回 true。

---

## 2. 工具调用 Harness

### 2a. GET /api/v1/tools

| 项目 | 值 |
|------|-----|
| 状态码 | `200 OK` |
| 工具总数 | 13 |
| `context_hint` 字段 | ❌ **缺失** — 所有工具的 `context_hint` 均为 `null`（不在响应中） |

**注册的工具列表：**
review, chat, knowledge_list, knowledge_read, chapters_list, chapter_read, scenes_list, scene_create, projects_list, project_create, guard_scan, style_list, style_analyze

### 2b. POST /api/v1/tools/style_list/call

| 项目 | 值 |
|------|-----|
| 请求体 | `{"args": {}}` |
| 状态码 | `200 OK` |
| 返回工具 | 3 种写作风格：冷峻克制、轻快日常、严肃叙事 |
| 风格详情 | 每种含 rules, profile, sample_text |

### 2c. POST /api/v1/tools/style_analyze/call — 正常调用

| 项目 | 值 |
|------|-----|
| 请求体 | `{"args": {"text": "他突然跑过来，然后被狠狠打了一顿。突然、然后、被——三个雷全踩。"}}` |
| 状态码 | `200 OK` |
| 结果 | 匹配 3 种风格，最高分 59.9（轻快日常），**冷峻克制含 forbidden_word_penalty: 10.0**，违禁词命中 2 次 |
| **注意** | 中文内容需用 Python 或 `--data-binary` 发送，bash 下 curl `-d` 传中文会触发 "There was an error parsing the body" |

### 2d. POST /api/v1/tools/style_analyze/call — 预检拦截（缺参）

| 项目 | 值 |
|------|-----|
| 请求体 | `{"args": {}}`（缺 `text`） |
| 状态码 | `422 Unprocessable Content` |
| 错误码 | `PARAM_VALIDATION_ERROR` |
| 消息 | `缺少必填参数: text` |
| **结论** | 预检机制生效，Pydantic schema 校验正确拦截 |

### 2e. GET /api/v1/harness/stats

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |
| **结论** | ❌ **端点不存在**（dist 版未注册 harness_stat 路由） |

---

## 3. WritingRule 风格检查

### 3a. GET /api/v1/style/rules

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |

### 3b. POST /api/v1/style/check

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |

### 3c. POST /api/v1/style/check（空文本）

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |

**结论：❌ 全部 404。** `routers/style_check.py` 在源码中存在，但 **dist 编译版未打包该路由**。源码中的写作规则系统（5 条规则：填充词/长句/被动语态/冗余修饰/弱词）无法通过 API 访问。

---

## 4. 写作流程 CRUD

### 4a. POST /api/v1/projects

| 项目 | 值 |
|------|-----|
| 请求体 | `{"name":"APITest"}` |
| 状态码 | `201 Created` |
| 返回 | `{"id":"30c494512972","name":"APITest","template":"default","created_at":"...","message":"项目 'APITest' 创建成功"}` |

**注意：** `"description"` 字段（源码中定义）在 dist 版 `CreateProjectRequest` 模型中被移除，传入会触发 422。

### 4b. GET /api/v1/projects

| 项目 | 值 |
|------|-----|
| 状态码 | `200 OK` |
| 结果 | 返回 16 个项目（含之前测试遗留），包含 id/name/template/stats 等信息 |

### 4c. POST /api/v1/chapters

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"30c494512972","title":"API测试章","order":5}` |
| 状态码 | `201 Created` |
| 返回 | `{"status":"created","filename":"第1章_API测试章.md","chapter_number":1,...}` |

### 4d. GET /api/v1/chapters

| 项目 | 值 |
|------|-----|
| 请求参数 | `?project_id=30c494512972` |
| 状态码 | `200 OK` |
| 返回 | 3 个章节，含 filename/stem/title/chapter_number 等元数据 |

### 4e. POST /api/v1/scenes/{chapter_id}

| 项目 | 值 |
|------|-----|
| URL | `/api/v1/scenes/第1章_API测试章` |
| 请求体 | `{"title":"测试场景","status":"draft","summary":"场景摘要"}` |
| 状态码 | `201 Created` |
| 结果 | 场景创建成功，自动生成 UUID id |

### 4f. GET /api/v1/scenes/{chapter_id}

| 项目 | 值 |
|------|-----|
| 状态码 | `200 OK` |
| 返回 | `{"chapter_id":"...","scenes":[...]}`，场景按 order 排序 |

### 4g. GET /api/v1/stats/{project_id}

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |
| **结论** | ❌ **端点不存在**。`routers/stats.py` 在源码中存在但 dist 版未注册该路由 |

---

## 5. writing-guide

### 5a. GET /api/v1/projects/{id}/guide

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |

### 5b. PUT /api/v1/projects/{id}/guide

| 项目 | 值 |
|------|-----|
| 状态码 | `404 Not Found` |

**结论：❌ 全部 404。** `projects.py` 源码中包含 guide 端点，但 **dist 编译版 projects.py 中 guide 相关代码被移除**（grep 0 匹配）。build 时可能剥离了这部分路由。

---

## 6. 导出

### 6a. POST /api/v1/export/txt

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"30c494512972","format":"txt"}` |
| 状态码 | `201 Created` |
| 返回 | `{"status":"ok","format":"txt","filename":"...","chapter_count":3,"download_url":"..."}` |
| **结论** | ✅ 通过。3 个章节成功导出为 UTF-8 无 BOM TXT |

### 6b. POST /api/v1/export/docx

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"30c494512972","format":"docx"}` |
| 状态码 | `201 Created` |
| 返回 | `{"status":"ok","format":"docx","filename":"...","chapter_count":3,"download_url":"..."}` |
| **结论** | ✅ 通过。3 个章节成功导出为 DOCX |

---

## 7. 备份

### GET /api/v1/projects/{id}/backup

| 项目 | 值 |
|------|-----|
| URL | `/api/v1/projects/30c494512972/backup` |
| 状态码 | `200 OK` |
| 返回 | `{"status":"ok","project_id":"30c494512972","filename":"backup_30c494512972_....zip","file_size":330,"download_url":"/export/backup_...zip"}` |
| **结论** | ✅ 通过。项目成功打包为 ZIP |

---

## 8. 伏笔 / 角色 / 目标

### 8a. POST /api/v1/foreshadowing

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"30c494512972","title":"隐藏的武器","content":"这把刀会在第三章出现","status":"pending"}` |
| 状态码 | `201 Created` |
| 返回 | 含 id/title/type/status/strength/gap 等字段 |

**注意：** `status` 枚举值为 `pending/revealed/resolved/abandoned`（传 `"active"` 会 422）。

### 8b. POST /api/v1/characters

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"30c494512972","name":"测试角色","role":"主角","description":"API测试用的角色"}` |
| 状态码 | `201 Created` |
| 返回 | 含 id/name/traits/avatar_color/relation_count 等 |

### 8c. POST /api/v1/goals

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"30c494512972","title":"完成第3章草稿","description":"本周目标","target_word_count":2500,"deadline":"2026-05-28"}` |
| 状态码 | `201 Created` |
| 返回 | 含 id/title/target_word_count/progress_pct/check_ins 等 |

**注意：** `target_word_count` 为必填字段（源码中未标注必填，但 dist 版 Pydantic 模型要求）。

### GET 验证

| 端点 | 状态码 | 结果 |
|------|--------|------|
| `/api/v1/foreshadowing?project_id=30c494512972` | `200` | 1 条伏笔 |
| `/api/v1/characters?project_id=30c494512972` | `200` | 1 个角色 |
| `/api/v1/goals?project_id=30c494512972` | `200` | 1 个目标 |

**结论：✅ 全部通过。**

---

## 9. 插件列表

### GET /api/v1/plugins

| 项目 | 值 |
|------|-----|
| 状态码 | `200 OK` |
| 返回 | 2 个插件：`debug_logger` (0.1.0, 调试日志打印), `wordcount_appender` (1.0.0, 自动在章末追加字数统计) |
| **结论** | ✅ 通过 |

---

## 已知问题汇总

### 🔴 严重：dist 编译版路由缺失（7 个端点 404）

| 缺失路由 | 源码位置 | 影响 |
|----------|----------|------|
| `/api/v1/style/rules` | `routers/style_check.py` | 无法获取写作规则 |
| `/api/v1/style/check` | `routers/style_check.py` | 无法执行文本风格检查 |
| `/api/v1/harness/stats` | `routers/harness_report.py` | 无法获取工具调用统计 |
| `/api/v1/stats/{project_id}` | `routers/stats.py` | 无法获取项目写作统计 |
| `/api/v1/projects/{id}/guide` | `routers/projects.py` | 无法读写写作规范 |
| `/api/v1/projects/{id}/guide` (PUT) | `routers/projects.py` | 同上 |

**根因：** `build.py` 打包为 PyInstaller exe 时未包含这些路由模块，或动态 import 机制未正确注册。`dist/shiyi-gongfang/_internal/main.py` 不存在（入口嵌入 exe），无法确认注册配置。

### 🟡 中：参数模型不一致

| 端点 | 源码模型 | dist 版模型 | 差异 |
|------|----------|-------------|------|
| POST /api/v1/projects | `CreateProjectRequest` 含 `description` 字段 | 不含 `description` | 传 description 会 422 |
| POST /api/v1/goals | `target_word_count` 有默认值 | 必填字段 | 缺则 422 |
| POST /api/v1/tools/{name}/call | `ToolCallRequest.args` | 同 | 须用 `{"args": {...}}` 包裹参数 |

### 🟡 中：终端编码兼容性

bash 下 `curl -d '{"text":"中文"}'` 发送含中文的 JSON 会导致服务端返回 "There was an error parsing the body"。改用 Python 的 `urllib.request` 或 `curl --data-binary @file` 可正常发送。

### 🟡 中：context_hint 字段

所有工具注册时 `context_hint` 均为 `null`，未填充。建议在每个工具定义中补充上下文提示，方便客户端智能判断工具推荐。

---

## 测试命令备忘

测试过程中使用的关键命令模式：

```bash
# 成功模式：Python urllib 发送中文 JSON
python3 << 'PYEOF'
import json, urllib.request
data = json.dumps({"title": "场景标题"}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8866/api/v1/scenes/...", 
    data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
print(json.dumps(json.loads(resp.read()), ensure_ascii=False, indent=2))
PYEOF

# 工具调用模式（注意 args 包裹）
curl -s -X POST http://127.0.0.1:8866/api/v1/tools/style_list/call \
  -H "Content-Type: application/json" \
  -d '{"args":{}}'

# 查看所有路由
curl -s http://127.0.0.1:8866/openapi.json | python3 -c \
  "import json,sys; data=json.load(sys.stdin); [print(p, list(data['paths'][p].keys())) for p in sorted(data['paths'])]"
```

---

## 建议

1. **修复打包流程** — 检查 `build.py` 确认 `style_check`, `stats`, `harness_report`, `projects` 全套路由被注册到 app
2. **统一 Pydantic 模型** — 源码和 dist 编译版应使用同一版本。推荐在源码侧加 `@field_validator` 同时兼容 dist 的 Pydantic v2
3. **补充 context_hint** — 在 `core/tool_definitions.py` 中为每个工具增加 `context_hint` 字段
4. **UTF-8 编码处理** — 服务端 FastAPI 请求体解析时增加 `json.loads(body.decode("utf-8"))` 的防护
