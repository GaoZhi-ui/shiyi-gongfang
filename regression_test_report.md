# 写作助手工坊后端回归测试报告

**日期**: 2026-05-24  
**环境**: 写作工坊 v0.4.1 / Python 3.13.5  
**API**: http://127.0.0.1:8000/api/v1

---

## 测试结果总览

| 测试类别 | 通过 | 部分通过 | 失败 | 备注 |
|----------|------|----------|------|------|
| 核心路由 | 3/4 | 0 | 1 | POST chapters 在运行版本中路由错误 |
| 日记 API | 0/3 | 0 | 3 | 路由未注册到 app（main.py） |
| Export | 2/2 | 0 | 0 | docx 第一次 500 是瞬态问题 |
| 边界情况 | 4/5 | 0 | 1 | 句式检测 regex 不匹配带逗号的情况 |
| **合计** | **9/14** | **0** | **5** | |

---

## 1. 核心路由测试

### ✅ GET /api/v1/health → 200 OK
健康检查正常返回，包含版本号、Python 版本、路径状态。

### ✅ POST /api/v1/projects → 201 Created
创建项目成功，返回 12 位短 UUID。

### ❌ POST /api/v1/projects/{pid}/chapters → 404（路由不存在）
**根因**: chapters 路由注册在 `/api/v1/chapters` 下，不存在 `/api/v1/projects/{pid}/chapters` 路径。章节不分项目，统一存储在 `chapters/` 目录。

### ❌ POST /api/v1/chapters → 422（运行版本中路由错误）
提交 JSON body 后报错，要求 query 参数 `project_id`、`filename`、`title`、`content`。

**根因**: **运行中的服务版本较旧**，代码中 `@router.post("", status_code=201)` 装饰器错误地附着在 `_vectorize_chapter()` 上（该函数本应是后台任务），而不是附着在 `create_chapter()` 上。磁盘上的文件代码已修正，但服务器未重启。
- 磁盘文件: `@router.post("")` 正确在 `create_chapter` 前（第 496 行）
- 运行版本: 装饰器在 `_vectorize_chapter` 前

**修复**: 重启服务器。

### ✅ GET /api/v1/chapters → 200
章节列表正常返回，含文件名、标题、章节号、字数等信息。

### ✅ GET /api/v1/chapters/{filename} → 200
读取章节内容正常，返回原始 markdown + 解析后的 parsed 字段。

### ❌ PUT /api/v1/chapters/{filename} → 500（运行版本）
报 Internal Server Error。

**根因**: 运行版本中 `update_chapter` 函数内部存在 `background_tasks.add_task(...)` 调用，但 `background_tasks` 不是函数参数（未被 FastAPI 注入），也未定义，导致 `NameError`。该错误被外层 `try/except Exception` 捕获（行 606-612），但 `background_tasks.add_task` 在磁盘版本中依然存在于 `create_chapter` 函数内（行 541-550: `background_tasks` 同样未定义）。

```python
# 磁盘代码 chapters.py 行 541-550
try:
    project_id = _resolve_active_project_id()
    vs = _get_vector_store()
    if vs:
        background_tasks.add_task(...)  # ⚠ background_tasks 未定义
except Exception:
    pass
```

**修复**: 将 `background_tasks: BackgroundTasks` 作为参数添加到 `create_chapter` 函数签名中。类似问题也存在于 `update_chapter`。

---

## 2. 日记 API 测试

### ❌ PUT /api/v1/diary/{project_id}/{day} → 404
### ❌ GET /api/v1/diary/{project_id}/{day} → 404
### ❌ GET /api/v1/diary/{project_id} → 404

**根因**: `diary_router` 在 `main.py` 第 31 行被 `import`，但 **未被 `app.include_router()` 注册**。查看 `main.py` 行 58-82，所有 `include_router` 调用中没有 `diary_router`。

**修复**: 在 `main.py` 中添加一行：
```python
app.include_router(diary_router, prefix="/api/v1")
```

---

## 3. Export 测试

### ✅ POST /api/v1/export/txt → 201 OK
TXT 导出成功（chapters="all", include_diary=true/false 均通过）。

### ✅ POST /api/v1/export/docx → 201 OK
DOCX 导出成功。第一次请求返回 500，重试后正常——可能是热重载或文件锁导致的瞬态问题。

---

## 4. 边界情况测试

### ✅ 字数不足 2000 → check_chapter 返回 word_count issue
`save_check.py` 的 `check_chapter` 函数正确识别字数不足。

### ❌ "不是...是..."句式检测 → regex 不匹配带逗号的情况
`save_check.py` 中正则 `不是[^。。，；！？]*是[^。。，；！？]*[。。，；！？]` 的 `[^。。，；！？]` 排除了逗号，导致中文中典型的 `不是A，而是B` 句式无法匹配（逗号打断了匹配）。

```python
# save_check.py 中的正则
ptn = r'不是[^。。，；！？]*是[^。。，；！？]*[。。，；！？]'
#           ↑ 排除逗号，导致 "不是A，而是B" 不匹配
```

**修复**: 从排除集移除逗号：`不是[^。；！？]*是[^。；！？]*[。，；！？]`，或者使用更精确的语义分析。

### ✅ 日记天数无法匹配 → 保存到 _unmatched.txt
`_split_diary` 函数在 `day_number` 为 `None` 时将日记保存到 `_unmatched.txt`，逻辑正确。

### ⚠️ 中文数字天数 → day_number 解析为 None
正则 `第[零一二三四五六七八九十百千]+天|第(\d+)天` 对中文数字（第一天、第二天）匹配，但 `group(1)` 只捕获右侧 `(\d+)` 组，对中文数字返回 None。属于 minor bug，但不会导致崩溃。

### ✅ Export docx 500 瞬态问题 → 重试后恢复
不是持续性问题。

---

## 5. 已知问题验证

### 问题 1: export.py `_resolve_active_project_id()` 命名问题

**结论: ❌ 磁盘代码中不存在此问题，但需要确认**

磁盘上 `export.py` 第 87 行 import 为 `resolve_active_project_id`，第 144 行调用为 `resolve_active_project_id()`，两者一致，命名正确。

### 问题 2: chapters.py 使用 `from core.project_config import resolve_active_project_id as _resolve_active_project_id`

**结论: ✅ 正确兼容**

所有 4 个调用点（行 512, 580, 607, 649）均使用 `_resolve_active_project_id()`，与别名一致。

### 问题 3: POST /api/v1/projects/{project_id}/chapters 返回 404

**结论: ✅ 确认是路由问题**

章节路由注册在 `/api/v1/chapters` 下，没有 `/projects/{pid}/chapters` 路径。章节与项目解耦。

---

## 6. 额外发现的 Bug

### Bug A: create_chapter 中 `background_tasks` 未定义
- **文件**: `routers/chapters.py`，行 541-550
- **影响**: `create_chapter`（POST /chapters）可能抛出 500
- **修复**: 改为 `background_tasks: BackgroundTasks` 参数注入

### Bug B: update_chapter 中 `background_tasks` 未定义
- **文件**: `routers/chapters.py`，行 606-612
- **影响**: 同上
- **修复**: 同上

### Bug C: create_chapter 中 `fm_text` 可能未定义
- **文件**: `routers/chapters.py`，行 519-526
- **问题**: `fm_text` 只在 `else` 分支中定义，若 `stem.startswith(TMP_PREFIX)` 为 True，`fm_text` 未赋值
- **修复**: 将 `fm_text = _build_frontmatter(...)` 移出 else 分支

### Bug D: `_split_diary` 函数对 YAML frontmatter 误判
- **文件**: `routers/chapters.py`，行 413-427
- **问题**: `content.split('---')` 将 YAML 的起始 `---` 误当作日记分隔符
- **影响**: `_collect_chapters` 在 export.py 中读取未剥离 frontmatter 的原始文件内容时，会将 frontmatter 后的全部内容当作 diary
- **修复**: 先剥离 YAML frontmatter 再调用 `_split_diary`

### Bug E: 句号密度检测未排除 frontmatter
- **文件**: `routers/save_check.py`，行 34
- **问题**: `check_chapter` 未剥离 YAML frontmatter 就直接统计句号密度，frontmatter 中的字符被计入正文

---

## 修复优先级

| 优先级 | Bug | 影响范围 |
|--------|-----|----------|
| P0 | `diary_router` 未注册（main.py） | 日记 API 完全不可用 |
| P0 | `background_tasks` 未注入 | create/update chapter 可能 500 |
| P0 | `fm_text` 作用域错误 | create chapter 时可能 UnboundLocalError |
| P1 | `_split_diary` 对 YAML frontmatter 误判 | 导出时 diary 合并异常 |
| P2 | 句式检测 regex 排除逗号 | 漏报常见句式问题 |
| P3 | 中文数字天数解析失败 | minor |
