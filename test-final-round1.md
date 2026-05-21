# 写作助手工坊 · 后端回归测试报告（修复验证版）

> 测试时间：2026-05-21 21:00 - 21:06 CST
> 服务端：http://127.0.0.1:8867
> 测试人：Hanako

---

## 1. 健康检查 `GET /api/v1/health`

| 项目 | 值 |
|------|-----|
| 状态码 | **200** |
| 响应时间 | **0.003s** |
| 关键字段 | `version: "0.4.1"` ✅ 版本符合预期 |
| 其他 | app: "写作助手工坊", python_version: "3.13.5", 所有路径检查通过 |

**结论：通过 ✅**

---

## 2. 创建项目 `POST /api/v1/projects`

| 项目 | 值 |
|------|-----|
| 请求体 | `{"name":"regression-test-round1","template":"default","description":"first round fix verification"}` |
| 状态码 | **201** |
| 响应时间 | **0.280s** |
| 关键字段 | `id: "9e1d6f0960e0"`, `message: "项目 'regression-test-round1' 创建成功"` |

**结论：通过 ✅** （响应很快，不卡死）

---

## 3. 创建章节 `POST /api/v1/chapters` ⚠️ **UNFIXED**

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"9e1d6f0960e0","title":"回归验证-开端","content":"..."}` |
| 首次请求 | **超时（15s 无响应）** |
| 重复请求 | **409（0.004s，提示 FILE_ALREADY_EXISTS）** |

**行为模式**：第一次 POST 请求挂死，但服务器端实际已完成文件创建。第二次相同请求立即返回 409。文件写入成功，但 HTTP 响应未返回。

**结论：未修复 ❌** — 服务器端写入成功，但响应被阻塞。同之前的 bug 现象。

---

## 4. 更新章节 `PUT /api/v1/chapters/{filename}` ⚠️ **UNFIXED**

| 项目 | 值 |
|------|-----|
| URL | `/api/v1/chapters/%E7%AC%AC1%E7%AB%A0_%E5%9B%9E%E5%BD%92%E9%AA%8C%E8%AF%81-%E5%BC%80%E7%AB%AF.md` |
| 请求体 | `{"project_id":"9e1d6f0960e0","title":"回归验证-开端","content":"更新后的..."}` |
| 首次请求 | **超时（10s）** |
| 二次请求 | **再次超时（5s）** |

**行为模式**：每次 PUT 请求都挂死，无任何响应返回。

**结论：未修复 ❌** — 同 POST 一样，写入类章节端点全部阻塞。

---

## 5. 统计 `GET /api/v1/stats/{project_id}`

| 项目 | 值 |
|------|-----|
| 请求 | `project_id: b53bebd08552`（已有章节的老项目） |
| 状态码 | **200** |
| 响应时间 | **0.016s** |
| 关键字段 | `total_chapters: 2`, `total_words: 51`, `total_scenes: 4`, `total_foreshadowing: 1`, `daily_stats: [...]`, `average_words_per_chapter: 26`, `streak_days: 1`, `focus_minutes_today: 20` |

**结论：通过 ✅** — 返回了真实统计数据，不再是 0。

---

## 6. 备份 `GET /api/v1/projects/{id}/backup`

| 项目 | 值 |
|------|-----|
| 请求 | `project_id: b53bebd08552` |
| 状态码 | **200**（JSON 元数据） |
| 响应时间 | **0.037s** |
| 元数据 | `download_url: "/export/backup_b53bebd08552_ba6a7711.zip"`, `file_size: 817` |

### 实际 zip 内容

```
Length   Date       Name
------   --------   ----
   265   2026-05-20 config.json
   150   2026-05-21 chapters/第1章_测试.md
   106   2026-05-21 chapters/第2章_另一个测试.md
```

**结论：通过 ✅** — 包含 config.json + 2 个章节文件。之前"只有 config.json"的 bug 已修复。

---

## 7. 导出 TXT `POST /api/v1/export/txt`

| 项目 | 值 |
|------|-----|
| 请求体 | `{"project_id":"b53bebd08552","format":"txt","chapters":["第1章_测试章节.md"]}` |
| 状态码 | **201** |
| 响应时间 | **0.006s** |
| 返回格式 | 元数据 JSON，含 `download_url` |
| 实际内容 | 格式化 TXT，含章节标题、正文、Markdown 渲染良好 |

**结论：通过 ✅**

---

## 8. 风格检查 `POST /api/v1/style/check`

| 项目 | 值 |
|------|-----|
| 请求体 | 约 70 字文学性文本 |
| 状态码 | **200** |
| 响应时间 | **0.003s** |
| 关键字段 | `total_issues: 1`, `rules_applied: 5` |
| 检查项 | `filler_words`, `long_sentence`, `passive_voice`, `redundant_modifiers`, `weak_words` |
| 发现 | "很大" — 冗余修饰（warning） |

**结论：通过 ✅**

---

## 汇总

| # | 端点 | 状态 | 响应时间 | 备注 |
|---|------|------|---------|------|
| 1 | GET /health | ✅ 通过 | 0.003s | 版本 0.4.1 |
| 2 | POST /projects | ✅ 通过 | 0.280s | 快速创建 |
| 3 | POST /chapters | ❌ 未修复 | 超时 | 文件创建成功但响应阻塞 |
| 4 | PUT /chapters/{fn} | ❌ 未修复 | 超时 | 每次请求都挂死 |
| 5 | GET /stats/{id} | ✅ 通过 | 0.016s | 有真实数据 |
| 6 | GET /backup | ✅ 通过 | 0.037s | 含章节文件，不再只有 config.json |
| 7 | POST /export/txt | ✅ 通过 | 0.006s | 导出正常 |
| 8 | POST /style/check | ✅ 通过 | 0.003s | 5 规则正常生效 |

### 核心发现

**两个关键 bug 未修复：**

1. **POST/PUT 章节请求阻塞** — 写入类端点（POST 创建、PUT 更新）均无响应返回，尽管服务器端实际完成了文件写入（重复请求返回 409 FILE_ALREADY_EXISTS 证明）。这是之前就有的问题，本轮修复没有覆盖。

2. **症状细节**：请求发送后 curl 无任何响应头返回，直到超时断开（status 000）。第二次相同请求立即返回（表明第一次已写入文件系统）。推测是 `Response` 对象的序列化或返回链路出现问题——可能是生成 Response 时某个阻塞操作（如数据库写后读、事件通知、WebSocket 广播）没有正确处理超时或异常。

### 已修复的项

- 备份 zip 现在包含章节文件 ✅
- 统计端点返回真实数据 ✅
- 其他只读端点（health, projects, chapters-list, export, style/check）均正常 ✅
