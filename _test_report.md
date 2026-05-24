# 写作助手工坊 综合测试报告

测试日期：2026-05-24 00:26 GMT+8
测试人：小黑
服务器：http://127.0.0.1:8000

---

## 1. 样式检查 API

### GET /api/v1/style/rules
**结果：通过 ✅**

返回 5 条规则：
- `filler_words` — 检测填充词（突然、然后、其实、竟然等）
- `long_sentence` — 检测长句（超过40个中文字）
- `passive_voice` — 检测被动语态（被字句）
- `redundant_modifiers` — 检测冗余修饰（非常/极其/太/很 + 形容词）
- `weak_words` — 检测虚弱词（觉得、有点、似乎、好像、可能等）

**注意：** 规则的 description 字段在 `curl` / `python -m json.tool` 等工具中可能出现乱码，这是终端编码（GBK vs UTF-8）问题，API 返回的实际字节是合法 UTF-8，前端显示正常。**非 bug。**

### POST /api/v1/style/check
**结果：通过 ✅**

| 测试场景 | 结果 |
|---------|------|
| "突然、然后、其实" 填充词 | 检测出 3 个 issue，均为 warning |
| 超长中文句（>40字） | 检测出 long_sentence 为 info |
| 空文本 | 返回 400 EMPTY_TEXT 错误 |
| 纯英文文本 | 通过（无 issue） |

---

## 2. save_check.py 检查逻辑验证

文件：`routers/save_check.py` — 四类检测规则，均正确触发。

### 规则 1：字数 < 2000 → severity: error ✅
- 测试：CJK 字数 = 9 → 触发 `word_count` type, severity `error`
- 消息：`正文字数9（需2000+）`
- 边界正确：>2000 时不触发

### 规则 2："不是A而是B" 句式 ≥ 2 → severity: warning ✅
- 测试：3 处 → 触发 `sentence_pattern` type, severity `warning`
- 消息：`"不是A而是B"句式3次（上限2次）`
- 边界正确：1 次时不触发

### 规则 3：句号密度 > 6/百字 → severity: warning ✅
- 测试：7 句号 / 35 字 = 20.0/百字 → 触发 `period_density` type
- 消息：`句号密度20.0/百字`
- 边界正确：密度 ≤ 6 时不触发

### 规则 4："好的"过渡 → severity: info ✅
- 测试：2 处 → 触发 `transition` type, severity `info`
- 消息：`"好的"过渡2处`
- 正常情况为 0 处时不触发

### 规则 5：日记检查（缺事实 / 缺观察）
- 测试："今天天气很好。" → 日记有"天"（事实关键词），无"看到/注意到/发现/想起"（观察关键词）
- 结果：触发 `diary` type，提示"缺观察" ✅
- 边界正确：包含事实和观察关键词时不触发

### 整体结论：save_check.py 全部 4+1 条规则逻辑正确，无异常。

---

## 3. style_scanner.py 正则修正验证

文件：`core/style_scanner.py`

### 3.1 "不是而是" 模式 ✅
- 正则：`不是[^。。，；！？]*?是[^。。，；！？]*?[。。，]`
- 3 处命中 → 正确计数（limit=2）
- 注意：该正则与 save_check.py 的版本有细微差异：
  - style_scanner：使用 lazy `*?`，终止符仅包含 `。。，`
  - save_check：使用 greedy `*`，终止符包含 `。。，；！？`
  - **不影响实际检测功能，但存在不一致风险**

### 3.2 "但" 排除 "但是" ✅（核心修正验证通过）
- 正则：`[。，；！？]但(?!是)`
- 测试验证全通过：
  - `。但` → 匹配 ✅
  - `。但是` → 不匹配 ✅（被 `(?!是)` 排除）
  - `，但` → 匹配 ✅
  - `，但是` → 不匹配 ✅
  - `；但` → 匹配 ✅
  - `；但是` → 不匹配 ✅
  - `！但` → 匹配 ✅
  - `！但是` → 不匹配 ✅
  - `？但` → 匹配 ✅
  - `？但是` → 不匹配 ✅

### 3.3 "却" 模式 ✅
- 正则：`，却`
- 正常匹配，无异常

### 3.4 "没有……只有" 模式 ✅
- 正则：`没有[^。]*只有`
- 正常匹配，无异常

### 整体结论：style_scanner.py 的正则修正有效，"但是" 被正确排除。✅

---

## 4. 前端页面检查

### 4.1 页面加载 ✅
- URL http://127.0.0.1:8000/ 返回 HTML 页面 200 OK
- 所有 CSS 样式正确应用
- 无 visible JS 错误（console 未捕获到报错）

### 4.2 模型选择下拉 ✅
- 包含 "Ollama (本地)" 选项
- 位置：topbar 中的 `<select id="modelSelect">`
- value: `ollama`, text: `Ollama (本地)`

### 4.3 侧边栏 "日记" 入口 ❌ **缺失**
- 后端已有完整日记 API（`routers/diary.py` — CRUD 齐全）
- 侧边栏 25 个入口中无 "日记" 或任何 diary 相关入口
- 用户无法通过 UI 访问日记功能

### 4.4 API 端点默认端口不匹配 ❌ **配置问题**
- 前端默认 API 端点：`http://127.0.0.1:8867/api/v1`
- 服务器实际端口：8000
- 导致启动时项目列表 "加载中…" 无法获取，状态栏显示 "API 未连接"
- 用户在设置中修改 API 端点后可用（端口改为 8000 即可）

### 4.5 项目列表加载 ⚠️
- 首次加载时项目选择器显示 "📁 加载中…" 持续不消失
- 原因同上（端口不匹配）

---

## 5. 发现问题汇总

| # | 严重程度 | 类型 | 描述 | 涉及文件 |
|---|---------|------|------|---------|
| 1 | **中** | 前端缺失 | 侧边栏无"日记"入口，日记 API 前端不可用 | `static/index.html` |
| 2 | **中** | 配置错误 | 前端默认 API 端口 8867 与后端端口 8000 不匹配，首次打开项目无法加载 | `static/index.html` line 1242, 1489 |
| 3 | **低** | 代码不一致 | save_check.py 和 style_scanner.py 的"不是而是"正则终止符集合不一致（save_check 含 `；！？`，style_scanner 只有 `。。，`） | `routers/save_check.py` vs `core/style_scanner.py` |

---

## 6. 通过项总结

| 测试项 | 状态 |
|-------|------|
| POST /api/v1/style/check | ✅ |
| GET /api/v1/style/rules | ✅ |
| save_check 字数 < 2000 → error | ✅ |
| save_check "不是A而是B" ≥ 2 → warning | ✅ |
| save_check 句号密度 > 6/百字 → warning | ✅ |
| save_check "好的"过渡 → info | ✅ |
| save_check 日记缺事实/观察检测 | ✅ |
| style_scanner 不是而是计数 | ✅ |
| style_scanner "但"排除"但是" | ✅ |
| style_scanner "却"匹配 | ✅ |
| style_scanner "没有……只有"匹配 | ✅ |
| 页面正常加载 | ✅ |
| Ollama (本地) 模型选项 | ✅ |
| 无 JS Console 报错 | ✅ |
