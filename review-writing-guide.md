# Code Review: writing-guide 模块

审查日期：2026-05-21
审查范围：projects.py（guide 端点）、chat.py（guide 注入）、index.html（guide 前端）

---

## 1. GET/PUT 端点设计

**结论：基本合理，PUT 语义正确。**

- `GET /api/v1/projects/{project_id}/guide` —— 读取型，纯查询，RESTful 风格正确。
- `PUT /api/v1/projects/{project_id}/guide` —— 全量替换，PUT 语义正确。Pydantic `WritingGuideUpdate` 的所有字段都有默认值，客户端发部分字段时不会报错。

**问题：**

### 1.1 PUT 返回 body.model_dump() 而非读回磁盘

```python
# projects.py:222-232
guide_path.write_text(
    json.dumps(body.model_dump(), ensure_ascii=False, indent=2),
    encoding="utf-8",
)
return WritingGuideResponse(**body.model_dump())
```

写入后返回的是**客户端发送的原始数据**，而非从磁盘读回的实际内容。如果写入过程中 Pydantic 对某个字段做了类型强转（如 int→str），写入 JSON 的值可能和响应不同。建议改为写入后读回：

```python
guide_path.write_text(...)
saved = json.loads(guide_path.read_text(encoding="utf-8"))
return WritingGuideResponse(**saved)
```

---

## 2. 路径穿越防护

**结论：projects.py 有防护，chat.py 缺失 —— 此为安全漏洞。**

### 2.1 projects.py ✅ 正确

`_find_project` 使用 `.resolve()` + `startswith` 前缀检测：

```python
proj_dir = (PROJECTS_DIR / project_id).resolve()
if not str(proj_dir).startswith(str(PROJECTS_DIR.resolve())):
    raise ProjectOperationError("路径越界")
```

两个端点（GET/PUT）都通过 `_find_project` 获取路径，路径穿越被阻断。级别：**安全**。

### 2.2 chat.py ❌ 未加防护

```python
# chat.py:288-291
def _load_writing_guide(project_id: str) -> str | None:
    guide_dir = BASE / "projects" / project_id
    guide_file = guide_dir / "writing-guide.json"
```

`project_id` 直接拼接进路径，**没有 `.resolve()` 和 `startswith` 校验**。

攻击向量：如果 `req.context.project_id` 来自客户端输入，攻击者可以传入：
- `../../etc` → 尝试读取 `BASE/projects/../../etc/writing-guide.json`
- `../data/chat_history` → 尝试读取聊天历史目录下的 `writing-guide.json`

虽然最终文件必须是 `writing-guide.json`（文件名固定），但目录遍历可以探测系统上任何存在 `writing-guide.json` 的路径是否存在，或尝试读取项目外的敏感文件（如符号链接）。

**严重程度：中等。** 必须修复。

**修复建议：** 复用 `_find_project` 的逻辑，或者直接让 `_load_writing_guide` 走 REST API 请求 `GET /projects/{id}/guide` 获取数据，避免重复实现路径解析。如果一定要直接读文件，至少加上：

```python
guide_dir = (BASE / "projects" / project_id).resolve()
project_base = (BASE / "projects").resolve()
if not str(guide_dir).startswith(str(project_base)):
    return None  # 或抛异常
```

---

## 3. 前端标签输入框

**结论：功能可用，实现有瑕疵。**

### 3.1 回车添加 ✅ 基本正确

- `keydown` 监听 `Enter`，`preventDefault` 阻止提交。
- 重复检测使用 `indexOf === -1`，去重正确。
- 添加后清空输入框。正确。

### 3.2 X 删除 ✅ 基本正确

- 点击 `×` 按钮后读取当前标签列表，splice 删除对应索引，重新渲染。
- `_guideFormDirty` 标记正确。

### 3.3 getGuideTagValues 使用 textContent 解析 ❌ 脆弱

```javascript
// index.html:2669-2675
function getGuideTagValues(containerId){
    var container = document.getElementById(containerId);
    var tags = [];
    container.querySelectorAll('span').forEach(function(span){
      var text = span.textContent.replace(/\s*×\s*$/, '').trim();
      if(text) tags.push(text);
    });
    return tags;
}
```

`container.querySelectorAll('span')` 选中的是标签容器内的**所有 span 元素**，包括：
- 标签文本的 span（外层）
- 删除按钮 × 的 span（内层，class 为 `guide-tag-remove`）

`×` (U+00D7) 渲染后的文本会在内层 span 的 textContent 里，但外层 span 的 textContent 是 `"tag×"`（内联 span 拼接）。这里的正则 `\s*×\s*$` 试图去掉末尾的 ×，但它的依据是 `×` 渲染后有空格包裹——在 `<span>tag<span>×</span></span>` 这种结构下，没有空格，`textContent` 是 `"tag×"`，`×`（U+00D7）和正则里的 `×` 是同一个字符，而且前面没空格。所以 `@s*×\s*$` 会匹配末尾的 `×` 然后去掉它。

实际上这个函数可以正常工作，因为它遍历的是容器内所有的 span（内层× span 的 textContent 是 `×`，去掉后为空字符串，被 `if(text)` 过滤掉），标签文本 span 的 textContent 是 `"tag×"`，去掉 `×` 后得到 `"tag"`。

**但换个角度看，这个实现过于隐晦**。如果哪天把 `×` 换成别的图标（如 SVG 或 Unicode 字符 ✕），或者模板结构变化（比如标签文本和 × 不再嵌套），这个函数就会静默出错。

**建议：** 改用 `dataset` 存储标签文本，而不是从 textContent 反推：

把渲染模板改为用 `data-value` 记录标签原文：

```javascript
container.innerHTML = tags.map(function(tag, idx){
  return '<span data-value="'+escHtml(tag)+'" ...>'+escHtml(tag)+'<span class="guide-tag-remove" ...>&times;</span></span>';
}).join('');
```

`getGuideTagValues` 改为读 `data-value`：

```javascript
container.querySelectorAll('[data-value]').forEach(function(el){
  tags.push(el.dataset.value);
});
```

这样解析与渲染细节解耦，无论 × 图标怎么变都不受影响。

---

## 4. chat.py 中 guide 注入为 system message 的逻辑

**结论：整体逻辑正确，但有一个潜在的多 system message 问题。**

### 4.1 注入位置 ✅ 正确

```python
# chat.py:349-353
if req.context and req.context.project_id:
    guide_text = _load_writing_guide(req.context.project_id)
    if guide_text:
        messages.append({"role": "system", "content": guide_text})
```

- 在 context notes（知识库引用、当前章节）之后、用户消息之前注入。
- 文件不存在时返回 None，跳过注入。正确。
- 格式化输出 `"风格：冷峻克制；语调：严肃。写作规范：...。禁用词：...。角色名：...。地名：..."` 结构清晰。正确。

### 4.2 多个 system message 的问题 ⚠️

`_build_payload` 最终会生成 0-3 条 system message：

1. `req.system_prompt`（始终存在）
2. context notes（可能有多条合并为一条）
3. guide（条件注入）

某些 LLM 后端（如 DeepSeek API、某些 OpenAI 兼容端点）的行为是：**多条 system message 只取最后一条**。这意味着如果同时有 `req.system_prompt`、context notes 和 guide，可能只有最后一条（guide）生效，前两者被覆盖。

**修复建议（二选一）：**
- **方案 A**：将所有 system 内容合并为一条，不同段落用空行分隔。
- **方案 B**：确认使用的 LLM 后端是否支持多条 system message（如 OpenAI 从 chat.completions v1 开始支持多 system 消息，按序拼接）。如果不支持，采用方案 A。

---

## 5. 默认值处理

**结论：大部分降级路径正确，前端的 `collectGuideFormData` 有数据丢失风险。**

### 5.1 文件不存在 → 返回 DEFAULT_WRITING_GUIDE ✅

```python
# projects.py:199-201
guide_path = proj_dir / "writing-guide.json"
if not guide_path.exists():
    return WritingGuideResponse(**DEFAULT_WRITING_GUIDE)
```

### 5.2 JSON 解析失败 → 同样降级 ✅

```python
except (json.JSONDecodeError, OSError):
    return WritingGuideResponse(**DEFAULT_WRITING_GUIDE)
```

静默降级，不抛 500，用户无感知。可以接受，但建议在 logs 里记录一条 warning。

### 5.3 chat.py 文件不存在 → return None → 跳过注入 ✅

### 5.4 ❌ 前端 collectGuideFormData 遗漏两个字段

```javascript
function collectGuideFormData(){
    return {
      style: ...,
      tone: ...,
      forbidden_words: ...,
      character_names: ...,
      place_names: ...,
      description: ...,
      // ⚠️ 缺少 max_sentence_length 和 dialogue_density_target
    };
}
```

`WritingGuideUpdate` 模型中有 `max_sentence_length`（默认 40）和 `dialogue_density_target`（默认 0.25），但前端表单既**没有让用户编辑这两个字段**，`collectGuideFormData` 也**不包含它们**。

后果：如果用户之前通过 API 或其他方式将 `max_sentence_length` 设为 60，只要在前端打开「写作规范」面板并点击保存，这两个字段就会被重置为 Pydantic 默认值（40 和 0.25）——**静默数据丢失**。

**修复建议：**
- 如果在 v1 中这两个字段不打算暴露给 UI，后端 `WritingGuideUpdate` 应设为**可选字段**（`Optional[int]`），写入时仅覆盖存在的字段，而非全量覆盖。
- 或者在前端表单中添加这两个参数的控制（滑动条/数字输入框）。
- 最轻量的修复：`collectGuideFormData` 从当前 guide 的响应中保留这两个值，合并后发送 PUT。

---

## 6. 其他发现

### 6.1 guide 文件未在 PUT 时更新项目时间戳

`PUT /projects/{id}/guide` 更新了 `writing-guide.json`，但没有更新 `config.json` 中的 `updated_at` 字段。项目列表（`GET /projects`）显示的更新时间不会反映 guide 变更。

### 6.2 WritingGuideResponse 和 WritingGuideUpdate 完全重复

两个 Pydantic 模型字段定义一模一样。考虑合并为一个 `WritingGuide(BaseModel)` 并用 `response_model=...` 和请求体各自继承 / 引用。

---

## 总结

| 维度 | 评级 | 说明 |
|------|------|------|
| 端点设计 | ✅ 良好 | RESTful 风格正确，PUT 语义准确 |
| 路径穿越防护 | ⚠️ 部分缺失 | projects.py 有防护；chat.py _load_writing_guide 缺 resolve 校验，属安全漏洞 |
| 标签输入框 | ⚠️ 可用但脆弱 | getGuideTagValues 用 textContent 反推标签值，需改用 dataset |
| system message 注入 | ⚠️ 潜在风险 | 多 system message 在不同 LLM 后端行为不一致 |
| 默认值降级 | ✅ 良好 | GET 端点和 chat.py 的 None 判断均正确 |
| 前端数据丢失 | ❌ 有 bug | collectGuideFormData 遗漏 2 个字段，保存时会覆盖已有值 |

**优先修复（按严重程度）：**
1. **chat.py 路径穿越** —— 安全漏洞，改 `_load_writing_guide` 加 resolve 校验
2. **前端缺字段导致的静默覆盖** —— 数据丢失 bug，`collectGuideFormData` 补齐或后端改可选覆盖
3. **多 system message 冲突** —— 合并为一条或确认后端行为
4. **getGuideTagValues 改 dataset 方式** —— 防御性重构
5. PUT 返回读回磁盘而非 model_dump、PUT 后更新 config.json updated_at —— 代码健壮性优化
