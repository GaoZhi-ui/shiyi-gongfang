# Harness 增强代码审查

> 审查日期：2026-05-21
> 审查范围：tools_router.py（Harness 增强部分）、harness_report.py、tool_definitions.py（context_hint 部分）、tools.py（context_hint 字段）
> 审查目标：xiao-huang 实现的工具调用 Harness 增强

---

## 一、参数预检逻辑（`_validate_against_schema`）

**文件**：`tools_router.py:75-122`

### 已覆盖的校验

| 校验项 | 状态 | 说明 |
|--------|------|------|
| 必填字段缺失 | ✅ | `required` 列表遍历，清晰 |
| 基础类型（string/number/integer/boolean） | ✅ | isinstance 对应正确 |
| 复合类型（array/object） | ✅ | 区分判定了 |
| array 项类型（string/number/integer/object） | ✅ | 遍历每项检查 |
| enum 枚举值 | ✅ | `value not in enum_values` |
| 嵌套 object 不做深度检查 | 明确注明 | 合理，复杂度与收益不成正比 |
| format（uri/date-time/email 等） | 明确注明 | 合理，writing-app 无此需求 |

### 问题 & 改进建议

#### ① `integer` 类型误收 `bool`（低风险）

```python
elif prop_type == "integer":
    if not isinstance(value, int):
        return False, ...
```

Python 中 `bool` 是 `int` 的子类，`isinstance(True, int)` 返回 `True`。如果一个 schema 字段声明为 `integer`，传 `true`（JSON 反序列化后为 Python `True`）会通过检查。而后续调用 handler 时可能收到 `True` 而非 `1`，造成意料之外的行为。

**建议**：在 `boolean` 分支之前所有 isinstance(int) 检查增加 `type(value) is not bool` 排除：

```python
if prop_type == "integer":
    if isinstance(value, bool) or not isinstance(value, int):
        return False, ...
```

或者利用 Python 3 的 `types` 模块：

```python
from types import NoneType  # Python 3.10+
# 或者用 type(value) is int
```

#### ② `null` 类型未处理（低风险）

如果工具的 inputSchema 中包含 `"type": "null"`，或者用数组形式定义多类型（如 `"type": ["string", "null"]`），当前分支均未匹配。`null` 类型的字段传任何值都会静默通过预检，不会报错。

当前 writing-app 的工具没有用到 nullable 字段，所以不是阻塞问题。但如果后续工具定义了 nullable 参数，需要补充处理。

#### ③ array items 缺少 `boolean` 和 `null` 项类型

```python
expected_types = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "object": dict,
}
```

缺少 `"boolean": bool` 和 `"null": NoneType`。同样不是现阻塞问题，但后续扩展时容易漏掉。

#### ④ 字段不在 properties 中时静默忽略

```python
if field not in properties:
    continue
```

如果调用方传入了一个 schema 中未定义的参数，不会报错。这其实是 **宽松模式**，在某些场景下是优点（允许 future-proof 扩展）。但如果需要严格校验，建议增加一个 `additionalProperties` 检查：

```python
# 检查未定义字段
for field in args:
    if field not in properties:
        return False, f"未知参数: {field}"
```

**决策建议**：当前宽松模式对 writing-app 的 AI agent 调用场景更友好（LLM 偶尔会补多余字段），建议保留。

---

## 二、结果后验（`_validate_result`）

**文件**：`tools_router.py:126-152`

### 已覆盖的校验

| 检查项 | 说明 |
|--------|------|
| 结果是 dict | 必须 |
| 含 content 字段 | 符合 MCP 规范 |
| content 是 list | 符合 MCP 规范 |
| content 非空 | 合理，空 content 无意义 |
| 每项含 type 和 text | 符合 MCP text content 规范 |
| text 是字符串 | 符合 MCP 规范 |

### 问题 & 改进建议

#### ① 冗余的 model 字段（非问题，是设计选择）

`ToolCallResponse` 直接复用 MCP 格式使用了 `content: list[dict]` 而非 `list[ToolContentItem]`。Pydantic 不会对内部 dict 做深层校验。不过已有 `_validate_result` 做运行时后验，Pydantic model 层面的深层约束不是必须的。

#### ② content 非空的强制要求可能过于严格

部分工具在特殊情况下可能返回空列表（例如 `knowledge_list` 在知识库为空时，理论上返回空列表是合理的）。建议把 `len(content) == 0` 降级为 warning 而非 fatal error，或者接受空 content 但只在 `isError=False` 时视为成功：

```python
if len(content) == 0 and not result.get("isError"):
    return True, ""  # 空内容但不是错误
```

**当前影响**：检查 writing-app 的所有 handler，没有一个会返回空 content 加 `isError=False`。所以不会是现有问题，但边界分支需要留意。

---

## 三、失败重试机制（`_execute_with_harness`）

**文件**：`tools_router.py:158-213`

### 核心问题

#### 🔴 **问题 1：重试是盲重试，未区分错误类型（高风险）**

重试条件：`if is_error or not post_ok:`

重试时用**完全相同的参数**再次调用 handler。对于写操作（有副作用的工具），这是危险的：

| 工具 | 可能被重试执行两次的效果 |
|------|------------------------|
| `scene_create` | 向 scenes JSON 文件追加两条相同记录 |
| `project_create` | 创建两次同名项目目录（第二次会失败，但第一次的副作用已经存在） |
| `export` | 生成两个相同文件 |

**当前受影响的具体路径**：
- `scene_create_handler` 调用 `_append_scene` → 文件追加写入
- `project_create_handler` 调用 Path.mkdir → 目录创建
- `_guard_scan_handler` 调用 subprocess → 子进程执行

**建议方案**：

**方案 A（推荐）**：区分临时错误和逻辑错误，只对临时错误重试

```python
def _is_transient_error(result: dict) -> bool:
    """判断错误是否可能是瞬时的，值得重试"""
    if not result.get("isError"):
        return False
    text = result.get("content", [{}])[0].get("text", "")
    transient_patterns = ["timeout", "连接超时", "connection", "网络", "network",
                          "429", "rate limit", "too many requests", "500", "502", "503"]
    return any(p in text.lower() for p in transient_patterns)
```

然后在重试条件中增加：

```python
if (is_error and _is_transient_error(result)) or (not is_error and not post_ok):
    # 只对临时错误或结构问题重试
    ...
```

**方案 B（轻量）**：在 Tool 类上增加 `retry_safe` 标记

```python
class Tool:
    def __init__(self, ..., retry_safe: bool = False):
        self.retry_safe = retry_safe  # True 表示重试是安全的
```

然后在 `_execute_with_harness` 中：非 `retry_safe` 的工具即使 `isError=True` 也不重试。

#### 🟡 **问题 2：后验失败但 isError=False 时会返回 200（中风险）**

逻辑路径：
1. 第一次执行：`isError=False`, `post_ok=False`
2. 进入重试块
3. 重试后：`isError=False`, `post_ok=False`（依然结构异常）
4. `harness_meta["post_validation"] = "fail"`
5. 函数返回 `(result, harness_meta)` 给 `call_tool` 路由
6. 路由检查 `isError=False` → 返回 200 ✅ 带着结构异常的数据

Route 层没有检查 `harness_meta["post_validation"]`。后验失败应该被提升为 HTTP 错误。

**建议**：在 `call_tool` 路由中增加对 harness 后验结果的检查：

```python
if harness_meta.get("post_validation") == "fail":
    raise HTTPException(
        status_code=500,
        detail={
            "code": "INVALID_RESULT",
            "message": "工具返回的结果结构异常",
            "tool": name,
            "harness": harness_meta,
        },
    )
```

#### 🟢 **问题 3：重试结果的后验判断有边界分支（低风险）**

```python
if is_error or not post_ok:
    # ...retry...
    if not post_ok:
        harness_meta["post_validation"] = "fail"
    else:
        harness_meta["post_validation"] = "ok"
```

这里有个微妙的情况：第一次执行时 `isError=True` 但 `post_ok=True`（结构完整但语义错误），重试后 `isError=False` 且 `post_ok=True`（成功）。此时 `post_validation = "ok"`，合理。

但如果重试后 `isError=True` 且 `post_ok=True`（结构完整但语义错误），`post_validation` 仍为 `"ok"`。这其实不算错——结构确实没问题，isError 会被路由正确处理。

#### 🟢 **问题 4：没有退避策略（低风险）**

当前重试是立即执行的，没有 `time.sleep`。对于写入操作的失败，即时重试几乎不可能成功。建议至少加短暂退避：

```python
if ...:  # 需要重试
    time.sleep(0.5)  # 500ms 退避
    harness_meta["retry_count"] = 1
    ...
```

---

## 四、Harness 元数据字段

**文件**：`tools_router.py:56-63`

```python
class HarnessMeta(BaseModel):
    pre_validation: str       # ok / fail
    post_validation: str      # ok / fail
    retry_count: int          # 0 / 1
    execution_time_ms: float
```

### 评估

| 字段 | 评价 |
|------|------|
| `pre_validation` | ✅ 有用，能区分是参数问题还是执行问题 |
| `post_validation` | ✅ 有用，能发现 handler 返回格式异常 |
| `retry_count` | ✅ 有用，能判断结果是否经过重试 |
| `execution_time_ms` | ✅ 有用，性能监控基础数据 |
| 结构 | ✅ Pydantic model，序列化/校验都方便 |

### 可扩展建议

后续版本可以考虑补充：

```python
class HarnessMeta(BaseModel):
    pre_validation: str
    post_validation: str
    retry_count: int
    execution_time_ms: float
    retry_reason: str | None = None  # 是什么触发了重试
    error_category: str | None = None  # transient / logic / validation
```

但当前 4 字段已经够用，不必过度设计。

### 输出时机问题

`_execute_with_harness` 中，`harness_meta` 被嵌入 `final_meta["harness"]` 作为响应的一部分。当 `isError=True` 时，路由直接抛出 HTTPException，并在 `detail["harness"]` 中也包含了 `harness_meta`。元数据在两个地方都有，设计上是对的——无论成功失败调用方都能看到。

但有一个微妙的点：`call_tool` 路由在抛出异常时：

```python
raise HTTPException(
    status_code=422,
    detail={
        "code": "TOOL_EXECUTION_ERROR",
        "message": error_text,
        "tool": name,
        "harness": harness_meta,
    },
)
```

这里的 `harness` 是直接传的 `harness_meta`（dict），而 Pydantic 在 FastAPI 异常 detail 中不会做额外序列化，所以类型是安全的。但如果未来 `harness_meta` 包含非 JSON 可序列化值（如 datetime），会出问题。建议显式 `harness_meta` 已经是基本类型，暂时安全。

---

## 五、线程安全实现（`harness_report.py`）

**文件**：`harness_report.py`

### 现有实现分析

| 关注点 | 状态 | 说明 |
|--------|------|------|
| 所有写操作加锁 | ✅ | `record_call` 使用 `with _lock` |
| 读操作加锁 | ✅ | `_compute_stats` 使用 `with _lock` |
| reset 加锁 | ✅ | `reset_harness_stats` 使用 `with _lock` |
| 内部函数在锁内调用 | ✅ | `_ensure_tool` 在 `record_call` 的锁内被调用 |
| `_ensure_tool` 自身不加锁 | ✅ | 正确——调用方已持有锁 |

### 设计合理性

**锁的选择恰当**：使用 `threading.Lock`（互斥锁）而非 `RLock`（可重入锁），因为 `record_call` 和 `_compute_stats` 之间没有递归调用关系。单一函数内调用 `_ensure_tool` 也不涉及递归。`Lock` 比 `RLock` 更轻量，选择正确。

### 潜在问题

#### ① `started_at` 的竞态条件窗口（极低风险）

在 `record_call` 中：

```python
with _lock:
    if _stats["started_at"] is None:
        _stats["started_at"] = time.time()
    ...
```

逻辑上没问题。但如果第一个请求进来时 `started_at` 是 None，设置成当前时间。后续请求用同一个时间戳。这里唯一的问题是：`started_at` 记录的是**第一次调用**的时间，不是应用启动的时间。对于统计口径来说，这个语义是合理的，但需要明确 it's not application uptime。

#### ② `uptime` 计算结果语义模糊

```python
uptime = round(time.time() - (_stats["started_at"] or time.time()))
```

当 `started_at` 为 None（尚无调用）时，`time.time() - time.time() = 0`。正确。

但"服务运行时间"和"首次调用后的时间"是两个不同的指标。如果服务启动后 1 小时才有人调用工具，`uptime` 是 1 小时还是 0？这里是 0（因为 `started_at` 记录的是首次调用时间）。

**建议**：增加一个 `app_started_at` 字段（在模块加载时设置），用于更准确地表示服务运行时间。或者明确在文档中说明 `uptime` 是"自首次工具调用以来的时长"。

#### ③ 浮点数累加的精度损失（可忽略）

`_stats["total_time_ms"] += duration_ms` 是浮点数累加。在百万次调用量级下，精度损失在微秒级别，不影响均值计算。不构成问题。

#### ④ 缺乏重置/恢复能力

"不落盘，重启后统计清零"的设计在文档中已说明。但对于生产环境，可能希望 Crash 后恢复统计。当前不是问题，如果后续需要持久化，建议在现有 API 不变的前提下追加 `load()` / `save()` 方法。

### 线程安全结论

✅ **实现正确**。锁的使用方式、粒度、范围都恰当，没有明显的线程安全性问题。

---

## 六、context_hint 设计评估

**文件**：`tools.py:4`（构造函数参数）、`tool_definitions.py:116-169`（注册时赋值）

### 数据结构侧

Tool 类新增的 `context_hint` 字段被设计为 `str | None`，`to_dict()` 在非空时才包含。这个设计简洁干净，不破坏已有接口的向后兼容性。

```python
# tools.py:38-43
def to_dict(self) -> dict:
    d = {
        "name": self.name,
        "description": self.description,
        "inputSchema": self.inputSchema,
    }
    if self.context_hint:
        d["context_hint"] = self.context_hint
    return d
```

✅ 不会污染没有 context_hint 的工具的序列化输出。

### 内容侧

#### 优点

- **动态上下文**：`chapters_hint` 和 `knowledge_hint` 在注册时根据实际文件数量计算，比硬编码多了实时性
- **统一注入**：所有工具共享相同的基础上下文（项目状态），降低了 LLM 的认知负担
- **AI 友好**：`context_hint` 直接在工具列表 API 暴露给 AI，帮助它判断什么时候用哪个工具

#### 问题

#### ① context_hint 与 description 信息高度重叠

以 `review` 工具为例：

- `description`：`"对指定章节运行 _review.py 写作审查，检查字数、句式、密度等。{chapters_hint}"`
- `context_hint`：`"写作审查工具。审查 {chapters_hint}，默认项目 tales-of-tera，运行 _review.py 脚本。"`

两条信息几乎一样。LLM 看到冗余信息虽然不会出错，但会稀释有效信号的密度。

**建议**：`context_hint` 应该提供 description 中**没有**的信息：

| 应有信息 | 说明 |
|----------|------|
| 调用前提/前置条件 | 比如"确保项目已存在 chapter 文件后再调用" |
| 预期副作用 | 比如"该工具会运行子进程" |
| 常用组合模式 | 比如"常与 chapter_read 配合使用" |
| 失败常见原因 | 比如"脚本不在项目目录时会失败" |

#### ② `chapters_hint` 在多数工具中重复出现

```python
chapters_hint = f"当前项目约有 {chapter_count} 个章节文件"
```

这个信息被注入到 11/14 个工具的 `context_hint` 或 `description` 中。更好的做法是只在一个**全局上下文**中提供（比如工具列表 API 的顶层元数据），而不是每个工具描述里都贴一遍。

#### ③ 动态计算只在注册时执行一次

```python
chapter_count = len([f for f in cd.iterdir() if f.suffix == ".md"])
knowledge_count = ...
```

如果后续新增了章节文件或知识库文件，context_hint 不会自动更新（需要重启服务）。这是一个可接受的权衡——重启刷新比实时查询的开销小得多。如果后续需要实时性，可以用一个定时刷新机制或懒加载。

#### ④ LLM 实际消费验证

当前没有机制验证 `context_hint` 是否真的帮助 AI 做出更好的工具选择。建议后续增加调用日志分析，观察每个工具的调用语境，评估 context_hint 是否影响了调用决策质量。

### context_hint 结论

**总体评价**：✅ 好的设计方向和实现，但内容策略需要优化。建议将 context_hint 和 description 的职责明确区分：

| 字段 | 职责 |
|------|------|
| `description` | 工具做什么 + 输入输出 |
| `context_hint` | 什么时候用 + 用了会怎样 + 常见陷阱 |

---

## 七、综合评分

| 维度 | 评级 | 关键发现 |
|------|------|----------|
| 参数预检 | 🟢 优良 | 覆盖全面，有 2 个低风险边缘分支可优化 |
| 结果后验 | 🟢 优良 | 结构校验完整，非空约束可再考虑边界 |
| 重试安全 | 🟡 需改进 | **未区分副作用工具和查询工具**，盲重试有数据重复风险 |
| Harness 元数据 | ✅ 完整 | 4 字段合理够用，输出时机对 |
| 线程安全 | ✅ 正确 | 锁粒度恰当，没有侦测到问题 |
| context_hint | 🟢 良好设计 | 内容策略有优化空间，职责边界可更清晰 |

### 必须处理（HIGH）

1. **重试副作用问题**：至少增加副作用标记或错误类型判断，避免非幂等工具被重复执行

### 建议处理（MEDIUM）

2. **后验失败未转 HTTP 错误**：Route 层应检查 `post_validation` 状态
3. **`integer` 类型误收 `bool`**：增加 `type(value) is bool` 排除

### 可择机优化（LOW）

4. **context_hint 职责清晰化**：与 description 差异化
5. **退避策略**：重试前加短时 sleep
6. **`uptime` 语义说明**：改为 app 启动时间或添加注释
7. **context_hint 动态刷新**：可添加定时刷新机制
