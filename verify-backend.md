# 写作助手工坊 · 后端交叉验证报告

**验证日期**: 2026-05-21 16:38 - 16:50  
**服务地址**: http://127.0.0.1:8867  
**API 版本**: 0.4.1  
**验证方式**: curl 对 11 个端点逐一调用

---

## 1. GET /api/v1/health — 健康检查

- **响应码**: `200`
- **结果**: ✓ 通过
- **版本确认**: `version: "0.4.1"`，符合预期
- **额外信息**: Python 3.13.5，无配置文件，基础路径全部可达

```json
{"status":"ok","app":"写作助手工坊","version":"0.4.1","python_version":"3.13.5"}
```

---

## 2. POST /api/v1/projects — 创建项目

- **请求体**: `{"name":"验证测试","template":"default"}`
- **响应码**: `201 Created`
- **结果**: ✓ 通过
- **项目 ID**: `f0abef3a0f8e`
- **注意**: `template` 字段必须传，可选值为 `default` 或 `novel`。用 `general` 会返回 `TEMPLATE_NOT_FOUND` 错误

```json
{"id":"f0abef3a0f8e","name":"验证测试","template":"default","created_at":"2026-05-21T08:39:07.328008+00:00","message":"项目 '验证测试' 创建成功"}
```

---

## 3. POST /api/v1/chapters — 创建章节

- **请求体**: `{"title":"第一章 开端","content":""}`
- **响应码**: `409 Conflict`（首次请求超时但服务端已创建，第二次返回冲突）
- **结果**: ⚠️ 存在阻塞问题
- **说明**: 传空内容后请求挂起 >15s（首次）和 >120s（第二次），curl 超时退出。后端实际完成了创建（文件 `第1章_第一章 开端.md` 已生成），再次请求才返回 `409 FILE_ALREADY_EXISTS`
- **问题**: POST /chapters 中大概率触发了 LLM/embedding 调用，无有效配置时长时间阻塞

```json
{"detail":{"code":"FILE_ALREADY_EXISTS","message":"章节文件 '第1章_第一章 开端.md' 已存在","suggestion":"使用 PUT /api/v1/chapters/{filename} 覆盖写入"}}
```

---

## 4. PUT /api/v1/chapters/{filename} — 更新章节内容

- **请求体**: `{"content":"短内容更新测试"}` → `{"content":"a"}`
- **响应码**: 多次尝试均无响应（curl exit code 28, timeout）
- **结果**: ⚠️ 后端执行成功但响应超时
- **说明**: 多次请求均 >10s 无响应（设 180s 超时也超时）。但事后 GET 章节内容确认后端确实执行了写入——内容已变为更新值。**确认是后端未在 HTTP 层面返回响应，而非请求失败**
- **问题**: PUT 的 handler 存在同步阻塞操作（推测为 vector store 更新），未设置客户端超时保护

**事后 GET 确认内容已更新**:
```json
{"filename":"第1章_第一章 开端.md","content":"---\ntitle: 第1章_第一章 开端\n...\n---\na","parsed":{"has_diary":true,"body_length":0,"diary_length":92}}
```

---

## 5. GET /api/v1/chapters — 列出章节

- **响应码**: `200 OK`
- **结果**: ✓ 通过
- **说明**: 返回 18 个章节（含此前其他测试遗留），结构清晰。每个条目包含 filename、title、chapter_number、status、size、cjk_chars、modified 等字段
- **目标章节确认**: `第1章_第一章 开端.md` 存在，size 118，cjk_chars 7

```json
{"chapters":[
  {"filename":"第1章_第一章 开端.md","title":"第一章 开端","status":"draft","size":118,"cjk_chars":7},
  ...
]}
```

---

## 6. POST /api/v1/scenes/{chapter_id} — 创建场景

- **请求体**: `{"title":"测试场景","scene_type":"dialogue","status":"draft","word_count":0,"summary":"场景验证测试"}`
- **请求路径**: `/api/v1/scenes/第1章_第一章 开端.md`
- **响应码**: `201 Created`
- **结果**: ✓ 通过
- **场景 ID**: `7b3e323e140f`
- **说明**: 字段完整，order 自动编号为 0，timestamps 正常

```json
{"status":"created","scene":{"id":"7b3e323e140f","chapter_id":"第1章_第一章 开端.md","title":"测试场景","scene_type":"dialogue","status":"draft","word_count":0,"summary":"场景验证测试","order":0}}
```

---

## 7. POST /api/v1/style/check — 文本风格检查

- **请求体**: `{"text":"这是一个测试文本，用于验证风格检查功能是否正常工作。","rules":[]}`
- **响应码**: `200 OK`
- **结果**: ✓ 通过
- **规则应用**: 5 条规则全部成功应用（filler_words, long_sentence, passive_voice, redundant_modifiers, weak_words）
- **检查结果**: 测试文本未发现问题（total_issues: 0）

```json
{"status":"ok","total_issues":0,"rules_applied":["filler_words","long_sentence","passive_voice","redundant_modifiers","weak_words"],"results":[]}
```

---

## 8. GET /api/v1/style/rules — 列出风格规则

- **响应码**: `200 OK`
- **结果**: ✓ 通过（预期 5 条，实得 5 条）
- **规则清单**:

| 规则名 | 描述 | 严重度 |
|--------|------|--------|
| filler_words | 检测填充词（突然、然后、其实、竟然等） | warning |
| long_sentence | 检测长句（超过40个中文字） | info |
| passive_voice | 检测被动语态（被字句） | warning |
| redundant_modifiers | 检测冗余修饰（非常/极其/太/很 + 形容词） | warning |
| weak_words | 检测弱词（觉得、感到、认为、好像等） | warning |

---

## 9. POST /api/v1/export/txt — 导出 TXT

- **请求体**: `{"title":"验证测试导出","chapters":["第1章_第一章 开端.md"]}`
- **响应码**: `201 Created`
- **结果**: ✓ 通过
- **导出路径**: `/export/验证测试导出.txt`
- **说明**: 响应快（瞬间返回），格式正确

```json
{"status":"ok","format":"txt","filename":"验证测试导出.txt","chapter_count":1,"download_url":"/export/验证测试导出.txt"}
```

---

## 10. GET /api/v1/git/{project_id}/status — Git 状态

- **请求路径**: `/api/v1/git/f0abef3a0f8e/status`
- **响应码**: `200 OK`
- **结果**: ✓ 通过
- **Git 可用**: true
- **分支**: master
- **工作区**: clean（无未提交变更）

```json
{"git_available":true,"branch":"master","clean":true,"changes":[]}
```

---

## 11. POST /api/v1/generate/name — 命名生成器

- **请求体（第一次）**: `{"type":"character","style":"玄幻","count":3,"project_id":"f0abef3a0f8e"}`
- **响应码**: `422 Unprocessable Entity`
- **原因**: `style` 字段为字面量枚举，仅接受 `eastern` / `western` / `fantasy` 三个值，中文值被拒绝

- **请求体（第二次）**: `{"type":"character","style":"fantasy","count":3,"project_id":"f0abef3a0f8e"}`
- **响应码**: `200 OK`
- **结果**: ✓ 通过（重试后）
- **生成结果**: `["雾凇","烬羽","霜瞳"]`
- **来源**: fallback（无可用的 LLM 配置）

```json
{"names":["雾凇","烬羽","霜瞳"],"type":"character","style":"fantasy","source":"fallback"}
```

---

## 汇总

| 序号 | 端点 | 方法 | 预期 | 实际 | 结论 |
|------|------|------|------|------|------|
| 1 | /health | GET | 200 | 200 | ✓ |
| 2 | /projects | POST | 201 | 201 | ✓ |
| 3 | /chapters | POST | 201 | 409（冲突） | ⚠️ 阻塞 |
| 4 | /chapters/{filename} | PUT | 200 | 超时（后端已执行） | ⚠️ 阻塞 |
| 5 | /chapters | GET | 200 | 200 | ✓ |
| 6 | /scenes/{chapter_id} | POST | 201 | 201 | ✓ |
| 7 | /style/check | POST | 200 | 200 | ✓ |
| 8 | /style/rules | GET | 200 (5条) | 200 (5条) | ✓ |
| 9 | /export/txt | POST | 201 | 201 | ✓ |
| 10 | /git/{id}/status | GET | 200 | 200 | ✓ |
| 11 | /generate/name | POST | 200 | 200（422→200） | ✓ |

**通过率**: 9/11 端点无异常（81.8%）  
**严重问题**: 2处阻塞（POST /chapters、PUT /chapters/{filename}），均涉及 LLM/vector store 后端处理未设超时保护

---

## 发现的问题

1. **PUT/POST /chapters 阻塞**（严重） — 涉及 AI 处理的端点在后端未设置 HTTP 超时保护。客户端需等待 LLM 或 vector store 操作完成，在无有效 LLM 配置时永久挂起
2. **/generate/name 枚举验证**（轻微） — `style` 字段用字面量枚举而非开放字符串，中文输入直接 422，应在文档中明确标注可选值
3. **项目间数据隔离不严格** — GET /chapters 返回了项目中所有章节（含其他测试数据），无 project_id 过滤机制
