# 写作助手工坊 0.4.1-beta 后端全链路 API 测试报告（第一轮）

> 测试日期：2026-05-21 13:02 ~ 13:05  
> 测试者：Hanako  
> 服务端：http://127.0.0.1:8867  

---

## 测试结果总览

| 序号 | 端点 | 状态 | 说明 |
|------|------|------|------|
| 1.1 | `GET /api/v1/health` | ✅ | 版本号正确 |
| 1.2 | `GET /api/v1/tools` | ✅ | 返回 14 个工具 |
| 1.3 | `POST /api/v1/tools/style_list/call` | ✅ | 返回 3 种风格定义 |
| 1.4 | `GET /api/v1/style/rules` | ✅ | 返回 5 条检查规则 |
| 1.5 | `POST /api/v1/style/check` | ✅ | 正确检测填充词/弱词 |
| 2.1 | `POST /api/v1/export/epub` | ✅ | 生成 .epub (6387 bytes) |
| 2.2 | `POST /api/v1/export/ebook` | ✅ | 生成含封面 .epub (7041 bytes) |
| 3.1 | `POST /api/v1/generate/name` (character/eastern) | ✅ | 返回 3 个名字（fallback） |
| 3.2 | `POST /api/v1/generate/name` (place/fantasy) | ✅ | 返回 5 个名字（fallback） |
| 4   | `GET /api/v1/git/{id}/status` | ✅ | 返回 git 仓库状态 |
| 5   | `GET /api/v1/knowledge/search` | ❌ | 路由被 `/{filepath:path}` 劫持 |

---

## 详细测试记录

### 1. 健康检查 & 核心API回归

#### 1.1 GET /api/v1/health

**参数**：无  
**响应码**：200  
**响应体关键字段**：
```json
{
  "status": "ok",
  "app": "写作助手工坊",
  "version": "0.4.1",
  "python_version": "3.13.5",
  "paths": {
    "chapters": true,
    "knowledge": true,
    "data": true,
    "routers": true,
    "static": true
  }
}
```
**结论**：✅ 版本号 0.4.1 确认，所有关键路径可达。

---

#### 1.2 GET /api/v1/tools

**参数**：无  
**响应码**：200  
**响应体**：返回 14 个 tools，包括 review、chat、knowledge_list、knowledge_read、chapters_list、chapter_read、scenes_list、scene_create、projects_list、project_create、guard_scan、style_list、style_analyze、export。  
**结论**：✅ 工具列表完整。

---

#### 1.3 POST /api/v1/tools/style_list/call

**参数**：`{}`  
**响应码**：200  
**响应体**：返回 3 种写作风格的完整定义（含 rules、profile、sample_text）：冷峻克制、轻快日常、严肃叙事。每种风格包含 sentence_length、dialogue_density、metaphor、forbidden_words 等规则。  
**结论**：✅ 写法引擎正常。

---

#### 1.4 GET /api/v1/style/rules

**请求方式**：GET（POST 返回 405 Method Not Allowed，正确行为）  
**响应码**：200  
**响应体**：5 条检查规则
| 规则 | 严重度 | 说明 |
|------|--------|------|
| filler_words | warning | 填充词检测（突然、然后、其实、竟然等） |
| long_sentence | info | 长句检测（>40字） |
| passive_voice | warning | 被动语态检测（被字句） |
| redundant_modifiers | warning | 冗余修饰检测（非常/极其/太/很+形容词） |
| weak_words | warning | 弱词检测（觉得、感到、认为、好像等） |

**结论**：✅

---

#### 1.5 POST /api/v1/style/check

**参数**：`{"text":"他站在城墙上，看着远处的地平线。那里曾经有一座城。现在只剩下废墟。突然他感到一阵莫名的恐惧。"}`  
**注意**：Windows bash 下 curl 命令行直接传中文 JSON 会因编码问题报 400。需将 JSON 写入文件后通过 `-d @file` 提交。  
**响应码**：200  
**检出问题**：

| 严重度 | 行号 | 命中内容 | 规则 | 建议 |
|--------|------|---------|------|------|
| warning | 1 | 突然 | filler_words | 填充词通常可删除，或替换为更具象的描写 |
| warning | 1 | 感到 | weak_words | 尝试用具体行为或感官描写替代主观判断 |

**结论**：✅ 风格检查正确检出填充词和弱词。

---

### 2. 新功能：EPUB导出 + 电子书编译

#### 2.1 POST /api/v1/export/epub

**参数**：`{"chapters":"all"}`  
**响应码**：201  
**响应体**：
```json
{
  "status": "ok",
  "format": "epub",
  "filename": "写作助手_导出_20260521_1302.epub",
  "chapter_count": 6,
  "download_url": "/export/写作助手_导出_20260521_1302.epub"
}
```
**验证**：下载 URL 可正常获取文件（HTTP 200），文件大小 **6387 bytes**，6 个章节。  
**结论**：✅

---

#### 2.2 POST /api/v1/export/ebook

**参数**：`{"chapters":"all","author":"测试","subtitle":"Beta版"}`  
**注意**：同 style/check，中文参数字段需用 `-d @file` 方式传递。  
**响应码**：201  
**响应体**：
```json
{
  "status": "ok",
  "format": "ebook",
  "filename": "写作助手_导出_20260521_1303.epub",
  "chapter_count": 6,
  "author": "测试",
  "download_url": "/export/写作助手_导出_20260521_1303.epub"
}
```
**验证**：下载可获取，文件大小 **7041 bytes**（比纯 EPUB 大 654 bytes，差异源于封面 + 作者元数据）。  
**结论**：✅ 含封面 + 目录的电子书编译正常工作。

---

### 3. 新功能：命名生成器

#### 3.1 POST /api/v1/generate/name (character/eastern)

**参数**：`{"type":"character","style":"eastern","count":3}`  
**响应码**：200  
**响应体**：
```json
{
  "names": ["沈默", "林渊", "江澈"],
  "type": "character",
  "style": "eastern",
  "source": "fallback"
}
```
**结论**：✅ 无 API Key 时正确降级到 preset 库，返回 3 个东方角色名。

---

#### 3.2 POST /api/v1/generate/name (place/fantasy)

**参数**：`{"type":"place","style":"fantasy","count":5}`  
**响应码**：200  
**响应体**：
```json
{
  "names": ["浮空岛·辰辉", "幽暗裂隙", "星辉图书馆", "龙骨荒漠", "镜湖"],
  "type": "place",
  "style": "fantasy",
  "source": "fallback"
}
```
**结论**：✅ 返回 5 个奇幻地点名。预设库数据完整。

---

### 4. Git 集成

#### GET /api/v1/git/{project_id}/status

**参数**：路径参数 `project_id = "b53bebd08552"`（测试项目，含 2 章节）  
**响应码**：200  
**响应体**：
```json
{
  "git_available": true,
  "branch": "main",
  "clean": true,
  "changes": []
}
```
**结论**：✅ 正确检测 git 仓库状态（branch、clean 状态、变更列表）。

---

### 5. 向量知识库搜索

#### GET /api/v1/knowledge/search?q=测试&project_id=default&top_k=3

**响应码**：400  
**响应体**：
```json
{
  "detail": {
    "code": "FILE_TYPE_ERROR",
    "message": "不支持的文件类型",
    "detail": "仅支持 {'.yaml', '.json', '.txt', '.md', '.yml'}",
    "suggestion": "仅支持 .md .txt .json 文件"
  }
}
```

**根因分析**：  
`/knowledge/search` 路由被 `/{filepath:path}` 通配路由劫持。在 `knowledge.py` 中路由注册顺序为：

```
@router.get("")                   → 列表
@router.get("/{filepath:path}")  → 文件读取（path 转换器匹配一切）
@router.get("/search")           → 搜索（永远无法被触发）
```

由于 FastAPI 中 `path` 类型的路径参数匹配任意路径（包括 `/search`），且路由按注册顺序匹配，`/{filepath:path}` 先捕获了请求，试图将"search"当作一个文件路径读取，触发了 `FILE_TYPE_ERROR`。

**修复建议**：  
将 `/search` 路由移到 `/{filepath:path}` 之前注册，或改为 `POST /api/v1/knowledge/search` 避免路径冲突。

**结论**：❌ 路由顺序 bug，需修复。

---

## 汇总

| 类别 | 通过 | 失败 | 通过率 |
|------|------|------|--------|
| 核心API回归 | 5 | 0 | 100% |
| EPUB/电子书导出 | 2 | 0 | 100% |
| 命名生成器 | 2 | 0 | 100% |
| Git集成 | 1 | 0 | 100% |
| 向量知识库 | 0 | 1 | 0% |
| **总计** | **10** | **1** | **90.9%** |

## 发现的 Bug

1. **B1 (高) — 知识库搜索路由被劫持**  
   `GET /api/v1/knowledge/search` 因路由顺序被 `/{filepath:path}` 通配路由拦截，需调整路由注册顺序或将 search 改为 POST。

## 注意点

1. **Windows bash 中文编码**：curl 命令行直接嵌入中文字符会导致 JSON body 解析错误（400）。通过文件传递 `-d @file.json` 可解决。这是测试环境的已知差异，非服务端问题。
2. **命名生成器降级策略**：无 API Key 时正常使用预设库（fallback）。预设库数据完整，覆盖 3 种类型 × 3 种风格 = 9 组。
3. **ebook 与 epub 端点差异**：ebook 端点多接收 `author` 和 `subtitle` 字段，输出文件比纯 EPUB 大约 10%，内容包含封面页和作者元数据。
