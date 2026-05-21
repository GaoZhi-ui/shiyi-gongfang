# 写作助手工坊 — 第1轮后端 API 回归测试报告

> 测试时间：2026-05-21 15:33 ~ 15:45 (CST)
> 测试方式：curl 直连 http://127.0.0.1:8867
> 测试目的：Bandit 修复后功能回归，确保核心与新功能 API 正常工作

---

## 测试摘要

| 分类 | 测试项 | 通过 | 失败 | 异常 |
|------|--------|------|------|------|
| 1. 核心API | 4 | 4 | 0 | 0 |
| 2. 新功能 | 6 | 5 | 1 | 0 |
| 3. 导出 | 3 | 3 | 0 | 0 |
| 4. 备份/Git | 2 | 2 | 0 | 0 |
| 5. 命名生成 | 1 | 1 | 0 | 0 |
| **合计** | **16** | **15** | **1** | **0** |

通过率：**93.75%**

---

## 1. 核心 API

### GET /api/v1/health
- **状态码**: `200`
- **结果**: `{"status":"ok","app":"写作助手工坊","version":"0.4.1",...}`
- **结论**: ✅ 通过，版本号 0.4.1 符合预期

### GET /api/v1/tools
- **状态码**: `200`
- **结果**: 返回 14 个可用工具列表（review / chat / knowledge_list / knowledge_read / chapters_list / chapter_read / scenes_list / scene_create / projects_list / project_create / guard_scan / style_list / style_analyze / export）
- **结论**: ✅ 通过，工具注册完整

### GET /api/v1/style/rules
- **状态码**: `200`
- **结果**: 5 条检查规则（filler_words / long_sentence / passive_voice / redundant_modifiers / weak_words）
- **结论**: ✅ 通过

### POST /api/v1/style/check
- **状态码**: `200`
- **请求体**: `{"text":"沈默站在罗德岛舰桥边缘..."}`
- **结果**: 检出 1 处冗余修饰（"很大" → redundant_modifiers）
- **注意**: 直接 inline 含中文的 JSON 会返回 400（编码问题），通过文件读取编码正常
- **结论**: ✅ 通过，建议前端确保 UTF-8 编码

---

## 2. 新功能

### POST /api/v1/projects
- **状态码**: `201`
- **请求体**: `{"name":"回归测试项目","template":"default"}`
- **结果**: 项目创建成功，返回 id: `21243c40b4ed`
- **注意**: template `"empty"` 不存在，可用模板为 `["default","novel"]`
- **结论**: ✅ 通过

### POST /api/v1/chapters
- **状态码**: `000`（连接超时，code 28）
- **请求体**: 多种组合（含 title + content / 仅 title / 带 filename）
- **结果**: 文件已存在时返回 `409`（预期行为）；新创建时 HTTP 连接维持不返回，超时后断开
- **推测原因**: 后端触发 AI 生成（续写/扩写），LLM 调用阻塞或未响应
- **结论**: ❌ 失败。章节创建接口存在阻塞性超时，需后端加入超时保护或异步队列

### POST /api/v1/scenes/{chapter_id}
- **状态码**: `201`
- **请求体**: `{"title":"测试场景","scene_type":"narration","summary":"回归测试场景","word_count":500}`
- **结果**: `{"status":"created","scene":{"id":"a40a4daa6658",...}}`
- **结论**: ✅ 通过

### POST /api/v1/foreshadowing
- **状态码**: `201`
- **请求体**: `{"project_id":"21243c40b4ed","title":"测试伏笔","type":"plot",...}`
- **结果**: 伏笔创建成功，返回完整元数据
- **结论**: ✅ 通过

### POST /api/v1/characters
- **状态码**: `201`
- **请求体**: `{"project_id":"21243c40b4ed","name":"测试角色-林渊","traits":["冷静","神秘","博学"]}`
- **结果**: 角色创建成功
- **结论**: ✅ 通过

### POST /api/v1/goals
- **状态码**: `201`
- **请求体**: `{"project_id":"21243c40b4ed","title":"完成回归测试","target_word_count":10000,"deadline":"2026-06-01"}`
- **结果**: 目标创建成功，含进度追踪
- **结论**: ✅ 通过

---

## 3. 导出

### POST /api/v1/export/epub
- **状态码**: `201`
- **请求体**: `{"chapters":"all","title":"回归测试EPUB"}`
- **结果**: EPUB 导出成功，8 章节，返回 download_url
- **结论**: ✅ 通过

### POST /api/v1/export/pdf
- **状态码**: `201`
- **请求体**: `{"chapters":"all","title":"回归测试PDF"}`
- **结果**: PDF 导出成功，8 章节
- **结论**: ✅ 通过

### POST /api/v1/export/txt
- **状态码**: `201`
- **请求体**: `{"chapters":"all","title":"回归测试TXT"}`
- **结果**: TXT 导出成功，8 章节
- **结论**: ✅ 通过

---

## 4. 备份 / Git

### GET /api/v1/projects/{id}/backup
- **状态码**: `200`
- **结果**: 项目打包为 zip（357 bytes），返回下载链接
- **结论**: ✅ 通过

### GET /api/v1/git/{id}/status
- **状态码**: `200`
- **结果**: `{"git_available":true,"branch":"master","clean":true,"changes":[]}`
- **结论**: ✅ 通过

---

## 5. 命名生成

### POST /api/v1/generate/name
- **状态码**: `200`
- **请求体**: `{"type":"character","style":"eastern","count":3}`
- **结果**: `{"names":["沈默","林渊","江澈"],"source":"fallback"}`
- **说明**: 未配置 AI Key 时自动使用预设库降级
- **结论**: ✅ 通过（降级机制正常）

---

## 失败项详细分析

### 失败项 #1：POST /api/v1/chapters（超时）

**现象**：HTTP 连接建立后，服务端不返回任何响应，直至 curl 超时（>60s 仍无响应）。

**复现步骤**：
1. 重复发送多次，均超时
2. 当 filename 冲突时，`409 FILE_ALREADY_EXISTS` 正常返回（说明路由正常）
3. 创建新章节时挂死

**推测根因**：后端 `@ai` 装饰器或显式 LLM 调用在创建章节时生成内容（续写），但 AI 调用未完成或阻塞。

**建议**：
- 章节创建应默认空内容或异步化
- AI 续写应单独作为工具调用（已有 `chat` 工具支持 continue 模式），不阻塞创建接口
- 加入请求级超时保护（如 `asyncio.timeout` 或 Uvicorn timeout）

**风险等级**：高 — 影响核心写作流程

---

## 备注

- 所有 POST 含中文 JSON 均通过文件读取 (`@/tmp/xxx.json`) 确保编码
- 回归测试使用了同一项目 `21243c40b4ed`，测试数据可手动清理
- 未测试 PUT/DELETE/批量接口，待下轮补充
