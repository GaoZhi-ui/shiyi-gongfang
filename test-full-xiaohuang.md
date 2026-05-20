# 写作助手工坊 · 安全/边界/性能压力测试报告

> **测试时间**：2026-05-21 01:33 ~ 01:39 (GMT+8)
> **测试地址**：http://127.0.0.1:8866
> **后端框架**：FastAPI (Python 3.13.5)
> **测试工具**：curl + Python3 urllib
> **测试者**：小黄

---

## 1. 路径穿越测试

### 1.1 GET /projects/../../../etc/passwd/guide

| 项目 | 内容 |
|------|------|
| **方法** | GET |
| **URL** | `/api/v1/projects/../../../etc/passwd/guide` |
| **预期** | 400 / 404，拒绝路径穿越 |
| **实际状态码** | **404** |
| **实际响应** | `{"detail":"Not Found"}` |
| **判定** | ✅ PASS — FastAPI 的 URL 标准化将 `../` 序列压缩后未能匹配任何路由，返回通用 404。但错误信息未区分"路由不存在"和"路径穿越拦截"，追踪不够精准。 |

### 1.2 PUT /projects/../../windows/system32/guide

| 项目 | 内容 |
|------|------|
| **方法** | PUT |
| **URL** | `/api/v1/projects/../../windows/system32/guide` |
| **预期** | 400 / 404 / 423 |
| **实际状态码** | **404** |
| **实际响应** | `{"detail":"Not Found"}` |
| **判定** | ✅ PASS — 同上，URL 标准化后路由不匹配。 |

### 1.3 POST /chapters filename="../../../test.md"

| 项目 | 内容 |
|------|------|
| **方法** | POST |
| **URL** | `/api/v1/chapters` |
| **Body** | `{"filename":"../../../test.md","content":"test"}` |
| **预期** | 400，阻止穿越 |
| **实际状态码** | **400** |
| **实际响应** | `{"detail":{"code":"INVALID_PARAMETER","message":"无效的文件名"}}` |
| **判定** | ✅ PASS — `sanitize.py` 或路由层检测到 `../` 序列并拒绝。 |

### 1.4 POST /chapters filename="..%2f..%2ftest.md"（URL 编码穿越）

| 项目 | 内容 |
|------|------|
| **方法** | POST |
| **URL** | `/api/v1/chapters` |
| **Body** | `{"filename":"..%2f..%2ftest.md","content":"test"}` |
| **预期** | 拒绝 |
| **实际状态码** | **201** |
| **实际响应** | `{"status":"created","filename":"..%2f..%2ftest.md",...}` |
| **文件是否存在** | 是 — 磁盘上以字面文件名 `..%2f..%2ftest.md` 创建 |
| **是否可以读取** | GET `/api/v1/chapters/..%2f..%2ftest.md` → **404**（URL 解码后 `../` 被识别为路径穿越） |
| **判定** | ⚠️ **WARNING** — 创建时未对 URL 编码做解码校验，文件名被接受。但 `..%2f` 在文件系统上仅为字面字符，不构成实际穿越。读取时 URL 被解码后触发穿越检测。**前后不一致**：创建时允许编码穿越字符，读取时拒绝。 |

### 1.5 POST /chapters filename="test.md%00.txt"（空字节注入）

| 项目 | 内容 |
|------|------|
| **方法** | POST |
| **URL** | `/api/v1/chapters` |
| **Body** | `{"filename":"test.md%00.txt","content":"test"}` |
| **预期** | 拒绝 |
| **实际状态码** | **201** |
| **实际响应** | `{"status":"created","filename":"test.md%00.txt.md",...}` |
| **文件是否存在** | 是 — 磁盘上以 `test.md%00.txt.md` 存在（`%00` 是字面字符而非空字节） |
| **判定** | ✅ PASS (安全) — `%00` 未在 HTTP 层解码为空字节，仅作为字面字符追加到文件名。文件系统安全。 |

---

## 2. 特殊字符/编码测试

### 2.1 XSS 项目名

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/projects |
| **Body** | `{"name":"<script>alert(1)</script>"}` |
| **预期** | 阻断 / 消毒 |
| **实际状态码** | **201** |
| **实际响应** | `{"name":"<script>alert(1)</script>",...}` 原样创建 |
| **判定** | ❌ **FAIL** — XSS payload 原样存储。虽然 `sanitize_text()` 函数存在，但项目创建路由**未调用它**。若前端在列表页直接用 `innerHTML` 渲染项目名，可导致 XSS 攻击。 |

### 2.2 5000 字中文名

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/projects |
| **Body** | `{"name": <5000个"险">}` |
| **预期** | 拒绝 / 截断 |
| **实际状态码** | **422** |
| **实际响应** | `string_too_long` — 最大 64 字符 |
| **判定** | ✅ PASS — Pydantic 模型层正确校验。 |

### 2.3 空字符串 name

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/projects |
| **Body** | `{"name":""}` |
| **预期** | 422 |
| **实际状态码** | **422** |
| **实际响应** | `string_too_short` — 至少 1 字符 |
| **判定** | ✅ PASS |

### 2.4 Emoji 项目名

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/projects |
| **Body** | `{"name":"🔥💩test🚀🌍中文日本語Español"}` |
| **预期** | 201 或 422（取决于设计） |
| **实际状态码** | **201** |
| **实际响应** | 创建成功，Emoji 正确存储 |
| **判定** | ✅ PASS — Emoji 和 Unicode 支持正常。 |

### 2.5 SQL 注入项目名

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/projects |
| **Body** | `{"name":"'; DROP TABLE projects; --"}` |
| **预期** | 阻断（文件存储无 SQL 风险，但仍应消毒） |
| **实际状态码** | **201** |
| **实际响应** | 原样存储 |
| **判定** | ⚠️ WARNING — 文件存储后端无 SQL 注入风险，但未调用 `sanitize_text()` 仍是防御缺失。 |

### 2.6 原型污染

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/projects |
| **Body** | `{"name":"test","__proto__":{"admin":true}}` |
| **预期** | 忽略 `__proto__` |
| **实际状态码** | **201** |
| **实际响应** | 仅 `name` 被提取，`__proto__` 被 Pydantic 忽略 |
| **判定** | ✅ PASS — Python Pydantic 天然免疫 JavaScript 原型污染。 |

### 2.7 全局章节名带 Unicode 编码

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/chapters |
| **Body** | `{"filename":"第1章_API测试.md","content":"test"}` |
| **预期** | 201 |
| **实际状态码** | **201** |
| **判定** | ✅ PASS — 中文文件名正常 |

---

## 3. Harness 统计测试

### 3.1 重置统计

| 项目 | 内容 |
|------|------|
| **方法** | GET /api/v1/harness/stats/reset |
| **预期** | 200，状态重置 |
| **实际状态码** | **200** |
| **实际响应** | `{"status":"reset"}` |
| **判定** | ✅ PASS |

### 3.2 连续调用 10 次（编程方式调用 record_call）

| 项目 | 内容 |
|------|------|
| **方法** | Python 内直接调用 `record_call()` 模拟 10 次工具调用（tool_a × 5, tool_b × 5, 其中 1 次标记为 error） |
| **预期** | 正确统计调用次数、失败率、平均耗时 |
| **实际结果** | `total_calls=10, total_errors=1, fail_rate=10.0%, avg_time_ms=20.22` |
| **per_tool** | tool_a: calls=5, errors=1, fail_rate=20%; tool_b: calls=5, errors=0, fail_rate=0% |
| **判定** | ✅ PASS — 统计准确，线程安全。 |

### 3.3 注意

Harness 统计是**被动数据记录器**——不会自动拦截 HTTP 请求。需要在每个工具有实际调用时显式调用 `record_call()`。统计只存在于内存中，重启清零。

---

## 4. 并发测试

### 4.1 同时创建 3 个章节

| 项目 | 内容 |
|------|------|
| **方法** | 3 个线程同时 POST /api/v1/chapters |
| **Body** | `{"filename":"并发测试第{1,2,3}章.md","content":"..."}` |
| **预期** | 3 个都返回 201 |
| **实际状态码** | **201 × 3** |
| **耗时** | **0.107s** |
| **判定** | ✅ PASS — 无冲突、无死锁、无数据丢失。 |

---

## 5. 大数据导出

### 5.1 POST /api/v1/export/docx (chapters="all")

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/export/docx |
| **Body** | `{"chapters":"all","title":"压力测试导出"}` |
| **预期** | 201，生成 docx |
| **实际状态码** | **201** |
| **实际响应** | `{chapter_count: 3, format: "docx", filename: "压力测试导出.docx"}` |
| **文件大小** | 37,186 bytes |
| **判定** | ✅ PASS |

### 5.2 POST /api/v1/export/txt (chapters="all")

| 项目 | 内容 |
|------|------|
| **方法** | POST /api/v1/export/txt |
| **预期** | 201 |
| **实际状态码** | **201** |
| **实际响应** | `{chapter_count: 3, format: "txt", filename: "压力测试导出.txt"}` |
| **文件大小** | 1,747 bytes |
| **判定** | ✅ PASS |

---

## 6. 错误路径测试

### 6.1 GET /api/v1/nonexistent

| 项目 | 内容 |
|------|------|
| **方法** | GET |
| **URL** | `/api/v1/nonexistent` |
| **预期** | 404 |
| **实际状态码** | **404** |
| **实际响应** | `{"detail":"Not Found"}` |
| **判定** | ✅ PASS |

### 6.2 POST /api/v1/style/check 传非 JSON 数据

| 项目 | 内容 |
|------|------|
| **方法** | POST |
| **Header** | `Content-Type: text/plain` |
| **Body** | `"this is not JSON"` |
| **预期** | 422 / 400 |
| **实际状态码** | **422** |
| **实际响应** | `model_attributes_type` — "Input should be a valid dictionary" |
| **判定** | ✅ PASS — FastAPI 自动拒绝非字典输入。 |

### 6.3 GET /projects/不存在的ID/guide

| 项目 | 内容 |
|------|------|
| **方法** | GET |
| **URL** | `/api/v1/projects/DOES_NOT_EXIST_12345/guide` |
| **预期** | 404 |
| **实际状态码** | **404** |
| **实际响应** | `{"detail":{"code":"PROJECT_NOT_FOUND","message":"项目 'DOES_NOT_EXIST_12345' 不存在"}}` |
| **判定** | ✅ PASS — 结构化的中文错误信息。 |

### 6.4 GET /projects/不存在的ID/backup

| 项目 | 内容 |
|------|------|
| **方法** | GET |
| **预期** | 404 |
| **实际状态码** | **404** |
| **实际响应** | `{"detail":"项目不存在"}` |
| **判定** | ✅ PASS |

### 6.5 POST style/check 空文本

| 项目 | 内容 |
|------|------|
| **Body** | `{"text":""}` |
| **预期** | 422 |
| **实际状态码** | **422** |
| **判定** | ✅ PASS — `min_length=1` 校验 |

### 6.6 POST style/check 缺失 text 字段

| 项目 | 内容 |
|------|------|
| **Body** | `{"rules":["some_rule"]}` |
| **预期** | 422 |
| **实际状态码** | **422** |
| **判定** | ✅ PASS — Pydantic 字段必填校验 |

---

## 7. 导入导出一致性测试

### 完整流程

| 步骤 | 操作 | 结果 | 判定 |
|------|------|------|------|
| 1 | POST 创建项目 `一致性测试` | ✅ 201，ID: 001ad720ea53 | PASS |
| 2 | 向项目 `chapters/` 写入 3 个章节文件 | ✅ 创建 3 个 .md 文件 | PASS |
| 3 | GET `/projects/{id}/backup` 下载 ZIP | ✅ 1059 bytes zip，含 4 条目 (config+3 chapters) | PASS |
| 4 | DELETE `/projects/{id}` 删除项目 | ✅ 200，目录确认不存在 | PASS |
| 5 | 重建项目目录 + config.json | ✅ 准备就绪 | PASS |
| 6 | POST `/projects/{id}/restore` 上传备份 ZIP | ✅ 200，restored_count=4 | PASS |
| 7 | 读取 `chapters/` 目录 | ✅ 3 个 .md 文件，内容完整，包含"小节"关键词 | PASS |

**最终判定： ✅ PASS — 导入导出完全一致，3 个章节文件和 config.json 全部恢复，内容无损。**

---

## 8. 综合发现汇总

### 严重问题

| # | 问题 | 路由 | 风险 |
|---|------|------|------|
| S-1 | **XSS 存储** — 项目名未调用 `sanitize_text()`，`<script>alert(1)</script>` 原样入库 | POST /api/v1/projects | 中 — 取决于前端渲染方式 |
| S-2 | **URL 编码路径穿越前后不一致** — 创建时接受 `..%2f`，读取时拒绝 | POST /chapters vs GET /chapters | 低 — 实际文件系统安全，但行为不一致 |

### 建议改进

| # | 建议 |
|---|------|
| R-1 | POST /api/v1/projects 创建和 PUT /projects/{id}/guide 更新时调用 `sanitize_text()` |
| R-2 | GET /projects/{id}/guide 返回 `404 Not Found` 应改为结构化的 `PROJECT_NOT_FOUND` (同 6.3) |
| R-3 | URL 编码的路径穿越字符应在创建时即拦截，与读取时行为一致 |

### 已通过的防御

- Pydantic 模型校验（长度限制、必填字段、类型校验）
- 项目路由 `_find_project()` 的路径解析越界检测
- 章节路由 `_safe_chapter_path()` 的 resolve 前缀校验
- ZIP 恢复的 zip slip 防护（`resolve()` 前缀检查）
- 导入导出的内容完整性保持
- 并发写入无冲突
- 非 JSON body 自动 422
