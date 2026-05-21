# 写作助手工坊 安全/边界压力测试报告（第二轮 — Bandit 修复后）

> 测试日期：2026-05-21 15:34 ~ 15:42  
> 服务地址：`http://127.0.0.1:8867`  
> 测试范围：路径穿越 / XSS / 边界 / 并发 / 错误路径 / Bandit 修复验证

---

## 1. 路径穿越测试

### 1.1 GET `/api/v1/projects/../../../etc/passwd/guide`

| 项目 | 值 |
|------|-----|
| 测试方法 | 在 URL 路径中嵌入 `../` 试图访问 `project_id=../../../etc/passwd` |
| 状态码 | **404** |
| 响应 | `{"detail":"Not Found"}` |
| 结论 | FastAPI 路径标准化先于路由，`../` 被 HTTP 层消耗，请求无法匹配路由。 |

### 1.2 POST `/api/v1/projects/../../../../tmp/xss` 创建项目

| 项目 | 值 |
|------|-----|
| 测试方法 | 在 POST URL 路径中嵌入 `../../../../tmp/xss` |
| 状态码 | **404** |
| 结论 | 同 1.1，路径标准化后不匹配路由。 |

### 1.3~1.4 URL 编码绕过 `%2e%2e%2f`

| 项目 | 值 |
|------|-----|
| 测试方法 | `%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd` |
| 状态码 | **404** |
| 结论 | FastAPI 解码后同样标准化，不构成有效路由。 |

### 1.5~1.7 真实项目 ID + 穿越后缀 / 反斜杠 / 分号注入

| 方法 | 状态码 | 结果 |
|------|--------|------|
| `068ceed94657/../../../etc/passwd/guide` | 404 | 路径标准化消耗 |
| `..\\..\\..\\etc\\passwd/guide` | 404 | 不匹配路由 |
| `..%3B/..%3B/..%3B/etc/passwd/guide` | 404 | 不匹配路由 |

### 1.8 对照：正常无效 ID

| 项目 | 值 |
|------|-----|
| `GET /api/v1/projects/nonexistent123456/guide` | **404** `PROJECT_NOT_FOUND` |
| 结论 | `_find_project` 中有路径越界检查（`resolve().startswith(PROJECTS_DIR.resolve())`），但无法触发，因为 URL 层面的 `../` 已被标准化。 |

### 1.9 双编码 `%252e%252e%252f`

| 项目 | 值 |
|------|-----|
| 状态码 | **404** `PROJECT_NOT_FOUND` |
| 响应 | `"项目 '%2e%2e%2fetc%2fpasswd' 不存在"` |
| 结论 | 双编码以字面量传递，不触发路径穿越。 |

### 1.10 POST body 内路径注入 `name: "../../tmp/xss"`

| 项目 | 值 |
|------|-----|
| 状态码 | **201** |
| 响应 | 项目成功创建，name=`../../tmp/xss` |
| 结论 | 项目 ID 是自动 UUID，name 只存 config.json，**不影响文件系统**。`sanitize_text()` 不拦截 `..` 和 `/`，因为 name 不用于文件路径。**低风险。** |

---

## 2. XSS 测试（确认 Sanitize 修复效果）

### 2.1 POST `/projects` `name="<script>alert(1)</script>"`

| 项目 | 值 |
|------|-----|
| 状态码 | **201** |
| 响应 name | `"<script>alert(1)</script>"`（原始输入） |
| 存储 name | `"alert(1)"`（script 标签被移除） |
| **问题** | **响应体泄露原始输入**。`create_project()` 返回 `name=body.name`（原始值）而非 `clean_name`（消毒后值）。虽然存储安全，但 API 响应反射了 XSS payload。 |

### 2.2 POST `/characters` `name="<img src=x onerror=alert(1)>"`

| 项目 | 值 |
|------|-----|
| 状态码 | **201** |
| 响应 name | `""`（空字符串） |
| 存储 name | `""` |
| 结论 | `onerror` 被 `_JS_EVENT` 移除，`<img>` 被 `_HTML_TAG` 移除，全部清空。**无风险。** |

### 2.3 POST `/projects` `name="<svg onload=alert(1)>"`

| 项目 | 值 |
|------|-----|
| 状态码 | 201 |
| 响应 name | `"<svg onload=alert(1)>"`（原始输入） |
| 存储 name | `""`（标签和事件均被移除） |
| 结论 | 同 2.1，响应反射原始输入，但存储安全。 |

### 2.4 POST `/projects` `name="javascript:alert(1)"`

| 项目 | 值 |
|------|-----|
| 状态码 | 201 |
| 响应 name | `"javascript:alert(1)"` |
| 存储 name | `"alert(1)"`（`javascript:` 协议被 `_DANGEROUS_URI` 移除） |
| 结论 | 存储安全，响应反射原始输入。 |

### 2.5 存储验证（config.json 读取确认）

| ID | 原始输入 | 存储值 |
|----|---------|--------|
| e0acbab34d92 | `<script>alert(1)</script>` | `alert(1)` |
| fc4031b1ca55 | `<svg onload=alert(1)>` | `` |
| 2338a0f802fd | `javascript:alert(1)` | `alert(1)` |

> **XSS 结论：santize_text() 在存储层正确工作，但 create_project 的响应体返回 `body.name`（原始值）而非 `clean_name`（消毒后值），导致响应反射 XSS payload。修复建议：将 return 中的 `name=body.name` 改为 `name=clean_name`。**

---

## 3. 边界测试

### 3.1 POST `/projects` 空 name

| 项目 | 值 |
|------|-----|
| 状态码 | **422** |
| 响应 | Pydantic `string_too_short` `min_length=1` |
| 结论 | Pydantic 验证层拦截 ✅ |

### 3.2 POST `/characters` 空 name

| 项目 | 值 |
|------|-----|
| 状态码 | **422** |
| 结论 | 同 3.1 ✅ |

### 3.3 POST `/projects` 超长 name (5000 字符)

| 项目 | 值 |
|------|-----|
| 状态码 | **422** |
| 响应 | Pydantic `string_too_long` `max_length=64` |
| 结论 | Pydantic 验证层拦截 ✅ |

### 3.4 POST `/projects` Emoji name `🌍🚀テストプロジェクトαβγ`

| 项目 | 值 |
|------|-----|
| 状态码 | **201** |
| 存储 name | `🌍🚀テストプロジェクトαβγ`（完整保留） |
| 结论 | Emoji 通过 Pydantic 验证（max_length=64 按字符计数）。Python 3.13 支持 Unicode 代理对。**无安全问题。** |

### 3.5 POST `/characters` Emoji name `😀🔥💀`

| 项目 | 值 |
|------|-----|
| 状态码 | 201 |
| 结论 | 正常创建。 |

### 3.6 POST `/projects` null byte `test\u0000nullbyte`

| 项目 | 值 |
|------|-----|
| 状态码 | **201** |
| 存储 name | `test\x00nullbyte`（null byte 被 JSON 转义存储） |
| **问题** | **控制字符（\x00、\x1F、\x7F）未过滤**。`sanitize_text()` 只移除 HTML 标签和事件属性，不处理控制字符。 |
| 风险 | 低——项目 ID 是 UUID，name 仅用于显示和 config.json 存储。但若 name 用于文件命名或路径拼接，控制字符可能引发截断。 |

---

## 4. 并发测试

### 4.1 3个线程同时 POST `/api/v1/chapters`（不同文件名）

| Req | 状态码 | 耗时 | 文件是否创建 |
|-----|--------|------|------------|
| 0 | **T/O** (15s) | 15.1s | ✅ 已创建 |
| 1 | **T/O** (15s) | 15.1s | ✅ 已创建 |
| 2 | **T/O** (15s) | 15.1s | ✅ 已创建 |

| 结果 | 值 |
|------|-----|
| 文件冲突 | 无（各有独立文件名） |
| 全部创建成功 | ✅ 3个 .md 文件均写入 |
| HTTP 响应超时 | ❌ **所有请求超时** |

### 根本原因分析

`create_chapter()` 执行路径（`chapters.py:462-515`）：
1. ✅ `_safe_chapter_path(filename)` → 写入 `.md` 文件
2. ❌ `_auto_git_commit("create", filename)` → 调用 `subprocess.run(["git", ...])`，**阻塞直到 git 完成**
3. ❌ `get_vector_store().add_chapter(...)` → 调用 `_ensure_encoder()`，首次加载 **SentenceTransformer 模型 `all-MiniLM-L6-v2`**，需从 HuggingFace 下载或加载

**第 2、3 步均为同步阻塞操作**，HTTP 请求必须等待两者完成。多个线程同时请求时，向量库的延迟初始化（模型下载/加载）导致响应超时（>15s）。文件已写入但响应未返回。

> **并发风险分级：** 不产生数据竞争或文件损坏（文件名独立，文件写入先完成），但**响应超时**暴露了同步阻塞架构问题。非并发场景下单请求也可能超时（模型未缓存时）。

---

## 5. 错误路径测试

### 5.1 GET `/api/v1/nonexistent`

| 项目 | 值 |
|------|-----|
| 状态码 | **404** |
| 响应 | `{"detail":"Not Found"}` |
| 结论 | 标准 404 处理 ✅ |

### 5.2 POST `/api/v1/nonexistent`

| 项目 | 值 |
|------|-----|
| 状态码 | **404** |
| 结论 | ✅ |

### 5.3 POST `/api/v1/style/check` 空文本 `{"text":""}`

| 项目 | 值 |
|------|-----|
| 状态码 | **422** |
| 结论 | Pydantic `min_length=1` 拦截 ✅ |

### 5.4 POST `/api/v1/style/check` 空白文本 `{"text":"   "}`

| 项目 | 值 |
|------|-----|
| 状态码 | **400** |
| 结论 | 手动 `if not body.text.strip()` 校验拦截 ✅ |

### 5.5 POST `/api/v1/style/check` 缺失 text 字段

| 项目 | 值 |
|------|-----|
| 状态码 | **422** |
| 结论 | Pydantic `Field required` ✅ |

### 5.6 PUT `/api/v1/projects`（方法不允许）

| 项目 | 值 |
|------|-----|
| 状态码 | **405** |
| 结论 | 标准 HTTP 方法拒绝 ✅ |

---

## 6. Bandit 修复验证（源码审计）

### 6.1 Git 命令路径检查

| 文件 | 函数 | 使用方式 | Bandit 合规 |
|------|------|---------|------------|
| `routers/projects.py:27` | 模块级 | `_git_cmd = shutil.which("git") or "git"` | ✅ 已解析 |
| `routers/projects.py:142` | `_is_git_available` | `[_git_cmd, "--version"]` | ✅ |
| `routers/projects.py:159-176` | `_init_git` | `[_git_cmd, "init"/"add"/"commit"]` | ✅ |
| `routers/git.py:27` | 模块级 | `_git_cmd = shutil.which("git") or "git"` | ✅ 已解析 |
| `routers/git.py:65` | `_git_available` | `[_git_cmd, "rev-parse"]` | ✅ |
| `routers/git.py:77` | `**_git_run**` | `**["git"] + args**` | ❌ **用字面量 `"git"` 而非 `_git_cmd`** |
| `routers/chapters.py:82` | `_is_git_repo` | `**["git", "rev-parse"]**` | ❌ **字面量 `"git"`** |
| `routers/chapters.py:99-104` | `_auto_git_commit` | `**["git", "add"/"commit"]**` | ❌ **字面量 `"git"`** |
| `routers/chapters.py:891-895` | `chapter_diff` | `**["git", "log"/"diff"]**` | ❌ **字面量 `"git"`** |

**发现问题：**
- `git.py` 的 `_git_run` 函数虽然是所有 git 路由的核心调用器，但它使用了 `["git"] + args` 而非 `[_git_cmd] + args`（虽然 `_git_cmd` 已在模块级解析）。这是修复遗漏。
- `chapters.py` 完全没有 git 路径解析，全部使用字面量 `"git"`。

### 6.2 Try/Except 注释检查

| 位置 | 代码 | 有注释 |
|------|------|--------|
| `projects.py:178-179` | `except Exception: pass` | ✅ `# Git not available, 静默跳过` |
| `chapters.py:43-44` | `except Exception: pass` | ✅ `# config optional` |
| `chapters.py:62-63` | `except Exception: pass` | ✅ `# config optional` |
| `chapters.py:108-109` | `except Exception: pass` | ✅ `# Git not available, 静默跳过` |
| `chapters.py:210-211` | `except yaml.YAMLError: pass` | ❌ **无注释** |
| `sanitize.py:90-91` | `except (ValueError, OSError, RuntimeError):` | ❌ **无注释**（但有 return False，非空 pass） |

### 6.3 Bandit 修复整体评估

| 项目 | 状态 |
|------|------|
| `projects.py` git 命令路径 | ✅ 已修复 |
| `git.py` `_git_run` 字面量 `"git"` | ❌ 未修复（遗漏） |
| `chapters.py` 全文字面量 `"git"` | ❌ 未修复 |
| try/except 注释覆盖率 | ⚠️ 部分修复（2个遗漏） |

---

## 7. 结合第一轮报告的部分测试结果（参考）

以下为第一轮测试中已确认的结论，本轮沿用相同配置：

### 常用符号特殊字符项目名

| 名称 | 结果 |
|------|------|
| `!@#$%^&*()_+{}[]\|:;'<>,.?/` | ✅ 201（已存在于列表中） |
| `'; DROP TABLE projects; --` | ✅ 201（已存在于列表中） |
| `Chinese English 日本語 Español العربية` | ✅ 201（已存在于列表中） |

### 项目ID为UUID，name仅做显示

所有边界字符都不会影响文件系统，因为项目目录名是自动生成的 12 位 hex UUID。

---

## 8. 完整问题清单（含严重等级）

| # | 问题 | 等级 | 文件 | 修复建议 |
|---|------|------|------|---------|
| 1 | **响应反射XSS**：`create_project` 返回 `body.name` 而非 `clean_name` | **中** | `projects.py` L357 | 将 `name=body.name` 改为 `name=clean_name` |
| 2 | **控制字符不过滤**：null byte、`\x1F`、`\x7F` 通过 sanitize | **低** | `routers/sanitize.py` | `sanitize_text()` 加入控制字符移除 `[\x00-\x1F\x7F]` |
| 3 | **chapters.py git 无路径解析**：全文字面量 `"git"` | **中** | `routers/chapters.py` | 引入 `shutil.which("git")` 解析路径 |
| 4 | **git.py _git_run 遗漏**：字面量 `"git"` 而非 `_git_cmd` | **低** | `routers/git.py` L77 | 改为 `[_git_cmd] + args` |
| 5 | **请求阻塞**：向量库初始化同步阻塞，首次请求可能 >15s | **低** | `core/vector_store.py` | 考虑移入 `_startup` 异步初始化或后台线程 |
| 6 | **章节创建无并发锁**：相同文件名同时写入可能冲突 | **低** | `routers/chapters.py` L462 | 可考虑文件锁或唯一索引 |

---

## 9. 总结

| 测试维度 | 通过率 | 关键发现 |
|---------|--------|---------|
| 路径穿越 | **100%** | FastAPI 标准化 + `_find_project` 边界检查双层防护 |
| XSS 存储 | **100%** | `sanitize_text()` 在存储层有效 |
| XSS 响应 | ❌ | 响应体反射原始输入（非存储型，但仍需修复） |
| 边界-空/超长 | **100%** | Pydantic 验证层拦截 |
| 边界-控制字符 | ❌ | null byte 等通过，需补过滤 |
| 并发-数据安全 | ✅ | 3个请求均成功写入文件，无冲突 |
| 并发-响应时间 | ❌ | 全部超时，暴露向量库同步阻塞问题 |
| 错误路径 | **100%** | 404/422/405 处理正确 |
| Bandit-git路径 | ⚠️ | `projects.py` 已修，`chapters.py` 和 `git.py._git_run` 未修 |
| Bandit-except注释 | ⚠️ | 大部分覆盖，2处遗漏 |

**总体评估：** 第二轮 Bandit 修复后，XSS 存储层和路径穿越防护有效。主要遗留问题：git 命令路径在 `chapters.py` 和 `git.py._git_run` 中未使用绝对路径（修复遗漏），响应体反射原始输入（非储存型但需修复），控制字符不过滤，以及并发场景下的向量库阻塞问题。
