# 写作助手工坊 · 新功能 + Ollama 集成测试报告

检查时间：2026-05-24 00:27
检查范围：routers/chat.py、routers/chapters.py、services/key_manager.py、static/index.html

---

## 🔴 严重问题

### 1. `_split_diary` 函数不存在（chapters.py:577）

`update_chapter` 中调用了 `_split_diary(clean_content)`，但此函数在整个项目中**没有定义过**。

```python
# chapters.py:577
body_only, diary_text, day_number = _split_diary(clean_content)
# NameError: name '_split_diary' is not defined
```

**后果**：任何对 `PUT /api/v1/chapters/{filename}` 的调用都会触发 `NameError`，500 响应。日记分离逻辑完全不可用。

**建议**：在 chapters.py 中实现 `_split_diary()` 函数，语义应为：
- 在正文末尾查找 `---` 分隔线，分隔线后为日记文本
- 用正则匹配中文数字天数（`第\d+天` / `第九十天` 等）
- 返回 `(body_without_diary, diary_text, day_number_or_None)`

---

### 2. `@router.post` 装饰器挂错了函数（chapters.py:439-451）

```python
@router.post("", status_code=201)   # ← 这个装饰器

def _vectorize_chapter(project_id: str, filename: str, title: str, content: str):
    """Background task: vectorize chapter"""
    ...

def create_chapter(body: ChapterCreate):   # ← 这个函数没有装饰器
    """创建新章节文件"""
    ...
```

`@router.post("")` 装饰的是 `_vectorize_chapter`，而不是 `create_chapter`。后果：
- **POST /api/v1/chapters → 调 `_vectorize_chapter(project_id, filename, title, content)`**——接收不到请求体，4个位置参数不可能从 HTTP 请求中填充，必定报错
- **`create_chapter` 函数没有任何路由绑定**——创建章节的接口完全无法使用

**建议**：删除 `@router.post("", status_code=201)` 与 `def _vectorize_chapter` 之间的空行，将装饰器移到 `create_chapter` 上方。

---

### 3. `create_chapter` 中使用未注入的 `background_tasks`（chapters.py:515）

```python
def create_chapter(body: ChapterCreate):
    ...
    background_tasks.add_task(...)   # ← background_tasks 未定义
```

由于 `create_chapter` 不是 FastAPI 路由（见问题2），`background_tasks` 参数根本不会注入。但即使修复了装饰器问题，`background_tasks` 也**不在函数参数列表中**——需要加 `background_tasks: BackgroundTasks` 参数。

**`update_chapter` 也存在同样问题**（chapters.py:610）：函数签名是 `def update_chapter(filename: str, body: ChapterUpdate)`，没有 `background_tasks` 参数，但内部调用了 `background_tasks.add_task(...)`。

**建议**：两个函数都加上 `background_tasks: BackgroundTasks` 参数。

---

### 4. `create_chapter` 中 `fm_text` 变量作用域 bug（chapters.py:503-509）

```python
    if stem.startswith(TMP_PREFIX):
        display_title = stem[len(TMP_PREFIX):]
    else:
        display_title = stem
        fm_text = _build_frontmatter(     # ← fm_text 只在 else 分支中定义
        title=display_title,
        ...
    )
    target.write_text(fm_text + content, encoding="utf-8")  # ← 无论哪个分支都会用到 fm_text
```

当文件名以 `_tmp_` 开头时，进入 `if` 分支，`fm_text` 从未赋值。然后 `target.write_text(fm_text + content, ...)` 会抛出 `NameError`。

**建议**：无论文件名是否以 `_tmp_` 开头，都应当生成 frontmatter。把 `fm_text = _build_frontmatter(...)` 移到 `if-else` 之外。

---

## 🟡 中等问题

### 5. `list_chapters` 状态过滤逻辑完全错误（chapters.py:413-423）

```python
if status and not name.startswith(TMP_PREFIX):
    continue
if status == ChapterStatus.DRAFT and not name.startswith(TMP_PREFIX):
    continue
```

- 第一行：只要传了 `status` 参数，所有不以 `_tmp_` 开头的文件都被跳过→只返回 `_tmp_*` 文件
- 第二行：在上述过滤后，再次判断 `status == DRAFT` 且非 `_tmp_` 前缀→此时永远不会触发（已被第一行过滤），纯死代码
- `status=reviewing` 或 `status=final` 时直接返回空列表

**根本原因**：代码仅通过文件名前缀 `_tmp_` 判断草稿状态，忽略了 frontmatter 中的 `status` 字段。

**建议**：先读取前几行解析 frontmatter，再根据 `status` 字段过滤。

---

### 6. `read_chapter` 中 `---` 分隔逻辑误伤 frontmatter（chapters.py:457）

```python
parts = content.split("---", 1)
parsed = {
    "has_diary": len(parts) > 1,
    ...
}
```

`read_chapter` 用 `---` 拆分文件来判断是否包含日记。但文件开头的 YAML frontmatter 也是以 `---` 包裹的。如果文件有 frontmatter，这个 `split` 会在 frontmatter 处截断，导致 `has_diary` 误报、body_length/diary_length 统计错误。

**建议**：先用 `_extract_frontmatter()` 移除 frontmatter，再对正文用 `---` 拆分。

---

## 🟢 轻微问题

### 7. `_vectorize_chapter` 缩进异常（chapters.py:443）

```python
def _vectorize_chapter(...):
    try:
                _get_vector_store().add_chapter(project_id, filename, title, content)
```

`add_chapter` 调用缩进了 16 个空格（应该是 8 个）。Python 不会报错，但代码风格不一致。

---

### 8. `_build_frontmatter` 调用参数缩进错误（chapters.py:507）

```python
        fm_text = _build_frontmatter(
        title=display_title,      # ← 应该缩进 8 个空格而不是 0
        content=content,
```

`_build_frontmatter` 的参数应该对齐到左括号内侧。当前缩进格式会让静态分析工具告警。

---

### 9. 前端的 `</select>` 重复闭合标签（index.html:1071-1072）

```html
    </select>   <!-- 正确闭合 #modelSelect -->
    </select>   <!-- 多余，无匹配的 <select> -->
```

多余 `</select>` 会被浏览器忽略，不会崩溃但违反 HTML 规范。

---

### 10. 前端无日记相关视图代码

前端 `static/index.html` 中完全不存在 `loadDiaryView`、`saveDiary` 等函数。搜索 `diary`（大小写不限）无匹配。后端有日记分离和存储逻辑，但前端没有对应的 UI 入口。

**建议**：如果日记功能是计划中的新功能，前端视图尚未实现属于预期状态。如果已上线则是缺失。

---

## ✅ Ollama 集成专项检查

### 11. `PROVIDER_CONFIGS` 中 ollama 条目

```python
"ollama": {
    "base_url": "http://localhost:11434",
    "default_model": "llama3.2",
    "chat_endpoint": "/v1/chat/completions",
    "auth_header": lambda key: {},
    "content_type": "application/json",
    "local": True,
},
```

- `auth_header` 返回空字典 ✓（Ollama 不需要 key）
- `local: True` 存在 ✓
- `base_url` 指向 localhost ✓

**结论：配置正确，无问题。**

---

### 12. `_get_api_info` 中本地 provider 跳过 key 检查

```python
if config.get("local"):
    api_key = ""
else:
    km = _get_key_manager()
    api_key = km.get_key(provider_lower)
    if not api_key:
        raise HTTPException(503, ...)
```

- `local` 为 True 时直接设 `api_key = ""` ✓
- 不会调用 `km.get_key()` ✓
- 不会触发 "API Key 未配置" 错误 ✓

**结论：逻辑正确，无问题。**

---

### 13. `key_manager.py` 中 `test_key` 对 Ollama 的支持

```python
async def test_key(provider: str, key: str) -> bool:
    if provider == "ollama":
        return True
    ...
```

- Ollama 直接返回 `True`，跳过网络测试 ✓

**结论：正确，无问题。**

---

### 14. 前端模型选择包含 Ollama（index.html:1064, 1292）

- 主工具栏：`<option value="ollama">Ollama (本地)</option>` ✓
- 设置弹窗：`<optgroup label="Ollama (本地)">` 包含 `llama3.2`、`qwen2.5`、`deepseek-coder-v2`、`mistral` ✓

**结论：前端模型选项完整，无问题。**

---

## 汇总

| 编号 | 严重度 | 文件 | 描述 |
|------|--------|------|------|
| 1 | 🔴 | chapters.py | `_split_diary` 函数未定义，日记分离不可用 |
| 2 | 🔴 | chapters.py | `@router.post` 挂错函数，创建章节接口不可用 |
| 3 | 🔴 | chapters.py | `background_tasks` 未注入，两个路由都报错 |
| 4 | 🔴 | chapters.py | `fm_text` 作用域 bug，`_tmp_` 开头的文件写入时崩溃 |
| 5 | 🟡 | chapters.py | `list_chapters` 状态过滤逻辑完全错误 |
| 6 | 🟡 | chapters.py | `read_chapter` 拆分 `---` 误伤 frontmatter |
| 7 | 🟢 | chapters.py | `_vectorize_chapter` 缩进异常 |
| 8 | 🟢 | chapters.py | `_build_frontmatter` 参数缩进错误 |
| 9 | 🟢 | index.html | 多余 `</select>` 闭合标签 |
| 10 | 🟡 | index.html | 前端无日记相关视图代码 |
| 11 | ✅ | chat.py | Ollama provider 配置正确 |
| 12 | ✅ | chat.py | 本地 provider key 检查跳过逻辑正确 |
| 13 | ✅ | key_manager.py | `test_key` 对 Ollama 返回 True |
| 14 | ✅ | index.html | 前端 Ollama 模型选项完整 |

**Ollama 集成方面全部验证通过，无任何问题。** 主要风险集中在 `chapters.py` 的日记分离逻辑和路由配置上——4 个严重 bug 中 3 个直接导致章节管理 API 不可用，1 个导致日记功能不可用。建议按优先级依次修复。
