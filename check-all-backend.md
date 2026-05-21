# 写作助手工坊 · 后端回归测试报告

**测试时间**: 2026-05-22 00:10 ~ 00:14  
**测试环境**: Windows_NT 10.0.26200 (bash/curl)  
**服务端**: `http://127.0.0.1:8872`  
**测试项目**: `0b19865b464a`（新创建）/ `b53bebd08552`（已有数据）

---

## 测试结果总览

| # | 端点 | 方法 | 状态码 | 响应时间 | 结果 |
|---|------|------|--------|----------|------|
| 1 | `/api/v1/chapters` | POST | **无响应** | **>30s (超时)** | ❌ **卡死未修复** |
| 2 | `/api/v1/projects` | POST | **201** | 250ms | ✅ |
| 3 | `/api/v1/stats/{project_id}` | GET | **200** | 82ms | ✅ |
| 4 | `/api/v1/projects/{id}/backup` | GET | **200** | 40ms | ✅ (JSON 返回下载链接) |
| 5 | `/api/v1/export/epub` | POST | **201** | 122ms | ✅ |
| 6 | `/api/v1/export/txt` | POST | **201** | 8.5ms | ✅ |
| 7 | `/api/v1/style/check` | POST | **200** | 5.8ms | ✅ |
| 8 | `/api/v1/style/rules` | GET | **200** | 2.2ms | ✅ |
| 9 | `/api/v1/scenes/{chapter_id}` | POST | **201** | 5.2ms | ✅ (注意路径含 chapter_id) |
| 10 | `/api/v1/characters` | POST | **201** | 4.9ms | ✅ |
| 11 | `/api/v1/foreshadowing` | POST | **201** | 5.2ms | ✅ |
| 12 | `/api/v1/goals` | POST | **201** | 4.8ms | ✅ |
| 13 | `/api/v1/plugins` | GET | **200** | 3.2ms | ✅ |
| 14 | `/api/v1/tools` | GET | **200** | 4.2ms | ✅ |
| 15 | `/api/v1/harness/stats` | GET | **200** | 3.2ms | ✅ |

**通过率**: 14/15 = **93.3%**

---

## 详细测试记录

### 1. POST /api/v1/chapters — ❌ 卡死未修复

**测试方法**: 传入 `project_id`, `filename`, `title`, `content` 四个 query 参数  
**结果**: 30 秒后 curl 超时退出（exit code 28），服务端无任何响应返回  
**结论**: 这是测试中最关键的问题。该端点无论传什么参数都**挂起不返回**，与用户之前报告的"卡死"现象一致，说明修复未生效。

```
POST /api/v1/chapters?project_id=xxx&filename=ch01.md&title=ch01&content=test
→ 30.0s 后超时，HTTP 000
```

### 2. POST /api/v1/projects — ✅ 正常

**请求体**: `{"name": "reg-test-project"}`  
**响应**: `{"id": "0b19865b464a", "name": "reg-test-project", ...}`  
**备注**: 字段必须用 `name`，不能用 `title`。多余字段 `author`/`description`/`genre` 会导致 body 解析失败（400）。

### 3. GET /api/v1/stats/{project_id} — ✅ 数据正常

**测试项目**: `b53bebd08552`（已有 32 章数据的项目）  
**返回数据亮点**:
| 指标 | 值 |
|------|----|
| total_chapters | 32 |
| total_words | 1,208 |
| total_characters | 0 |
| total_scenes | 4 |
| total_foreshadowing | 1 |
| longest_chapter | 第1章_第一章 启程.md (459词) |
| shortest_chapter | test_put_only.md (1词) |
| avg words/chapter | 38 |

**结论**: 之前返回 0 的问题已修复，现在能正确聚合统计数据。

### 4. GET /api/v1/projects/{id}/backup — ✅ 正常

**响应**: JSON 元数据，含 `download_url`  
**实际 zip 文件**: 817 bytes，有效 ZIP 格式，内含：
- `config.json`
- `chapters/*.md`（两个章节文件）

### 5. POST /api/v1/export/epub — ✅ 正常

**响应**: 201 Created，返回下载链接  
**文件**: `写作助手_导出_20260522_0012.epub` (23KB)，实际可下载

### 6. POST /api/v1/export/txt — ✅ 正常

**响应**: 201 Created，返回下载链接  
**文件**: 32个章节合并为单个 txt 文件

### 7. POST /api/v1/style/check — ✅ 正常

**输入**: `{"text": "他慢慢的走进房间。然后他坐在椅子上。"}`（中文）  
**结果**: 检测到 1 个问题：
- `"然后"` → 填充词警告  
**规则命中**: filler_words, long_sentence, passive_voice, redundant_modifiers, weak_words

**注意**: 中文内容需通过文件（`@file`）方式传入，直接 `-d` 传中文 JSON 可能导致解析失败。

### 8. GET /api/v1/style/rules — ✅ 正常

返回 5 条风格规则配置。

### 9. POST /api/v1/scenes/{chapter_id} — ✅ 正常

**实际路径**: `POST /api/v1/scenes/{chapter_id}`（需在路径中指定章节文件名）  
**响应**: 201，自动生成 scene ID

### 10. POST /api/v1/characters — ✅ 正常

**请求体**: `{"project_id": "b53bebd08552", "name": "测试角色", "role": "protagonist", "description": "..."}`  
**响应**: 201，自动生成 ID 和默认颜色

### 11. POST /api/v1/foreshadowing — ✅ 正常

**正确字段**: `project_id`, `title`, `type`（枚举: plot/character/object/lore）, `expected_resolve_chapter`  
**响应**: 201

### 12. POST /api/v1/goals — ✅ 正常

**正确字段**: `project_id`, `title`, `goal_type`, `target_word_count`, `deadline`  
**响应**: 201

### 13. GET /api/v1/plugins — ✅ 正常

**返回**: 2 个已加载插件：
- `debug_logger` (0.1.0) — 调试日志
- `wordcount_appender` (1.0.0) — 自动追加字数统计

### 14. GET /api/v1/tools — ✅ 正常

**返回**: 14 个可用工具（review, chat, knowledge_list, knowledge_read, chapters_list, chapter_read, scenes_list, scene_create, projects_list, project_create, guard_scan, style_list, style_analyze, export）

### 15. GET /api/v1/harness/stats — ✅ 正常

**返回**: `total_calls: 0`, `total_errors: 0`（自上次重置以来无调用，预期之内）

---

## 新发现的 API 路径偏差

部分端点的实际路径与用户列举的有出入：

| 用户列举的路径 | 实际路径 |
|----------------|----------|
| `POST /api/v1/scenes` | `POST /api/v1/scenes/{chapter_id}` |
| `POST /api/v1/chapters` | 也是 `POST /api/v1/chapters`（✓ 正确，但给 query 参数而非 JSON body） |

完整的 OpenAPI 路由表见服务端 `/openapi.json` 或 `/redoc`。

---

## 关键发现汇总

1. **❌ #1 最严重 — POST /api/v1/chapters 卡死**：无论参数如何，端点始终挂起直至超时。这是回归测试的核心失败点，修复未生效。
2. **✅ stats 已从 0 恢复正常**：之前返回 0 的问题已修复，能正确聚合多维度数据。
3. **✅ 导出/备份/风格检查工作正常**：EPUB、TXT 导出、备份 zip、风格规则、字符创建等核心 CRUD 全部正常。
4. **⚠️ 中文 JSON body 的脆弱性**：部分端点直接 `-d` 传中文 JSON 会触发 400，需改用文件加载方式（`@file`），这可能是 FastAPI 的 JSON parsing 在 Windows/curl 环境下的兼容问题。

---

*报告由回归测试脚本自动生成*
