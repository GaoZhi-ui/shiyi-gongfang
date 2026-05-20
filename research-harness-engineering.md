# Harness Engineering 调研报告

> 写作助手工坊 × Harness 驾驭工程 — 可借鉴的设计模式

---

## 一、什么是 Harness Engineering

由 HashiCorp 联合创始人 Mitchell Hashimoto 于 2026 年 2 月提出。

**核心哲学**：瓶颈不在模型智能，而在基础设施。优化模型运行的环境比换一个更强的模型更有效。

**四大护栏：**

| 护栏 | 解决的问题 | 写作工坊的对应 |
|------|-----------|--------------|
| 上下文工程 Context | Agent 不知道该看什么 | 知识库 RAG + 项目配置 |
| 架构约束 Constraints | Agent 复制坏模式 | 枚举类型系统、API 路由规范 |
| 反馈循环 Feedback | Agent 不知做错了 | 风格检查、写作工作流审查 |
| 熵管理 Entropy | 技术债务和文档腐烂 | FSAL 缓存、文件系统管理 |

---

## 二、对写作助手工坊最有价值的 5 个借鉴

### ① AGENTS.md → 项目写作规范文件

Harness 的每个项目有一个 AGENTS.md 作为 AI 的第一份指南。
**借鉴**：为每个写作项目生成一个 `writing-guide.md`，由用户在创建项目时填写或选择模板，包含：
- 文体风格描述
- 禁用词列表
- 常用角色名和地名（避免 AI 自己编造）
- 对照已有的 `writing-guide.md` 风格检查

**工作量**：模板系统已有，加一个文件即可 ⭐

### ② 自定义检查规则 → Linter 化

Harness 把架构规则编码为自定义 Linter。
**借鉴**：`core/style_checker.py` 当前只有 5 条硬编码规则。
改为可扩展的规则注册系统：
- `WritingRule` 基类：`name, check(text) -> list[Issue]`
- 规则可从 `rules/` 目录动态加载（复用插件框架 `core/plugin_manager.py`）
- 用户可创建自定义规则（"不能连续三段以'他'开头"）

**工作量**：复用已有插件框架 ⭐⭐

### ③ 循环审查 → "AI 审 AI"

Harness 用 Codex 自我审查代码。
**借鉴**：写作流程的第 3.4 阶段（外部评审）可以做成自动化的 Agent-to-Agent 审查链：
1. 风格检查引擎扫描（已有 `POST /api/v1/style/check`）
2. 逻辑一致性检查（跨章节名/地名/角色名）
3. 伏笔回收检查（对比伏笔追踪表）
4. 生成审查报告

**工作量**：已有风格检查 API + 伏笔 API ⭐⭐

### ④ 持续垃圾回收 → 知识库园丁

Harness 有 Doc-gardening Agent 自动维护文档。
**借鉴**：后台 Agent 定期扫描：
- 知识库中提到的角色/地点是否还在用
- 人物关系图是否与章节内容一致
- 伏笔是否已超期未回收（对比预期回收章节）
- 章节状态自动推进（写了新章→标记为 draft）

**工作量**：需要 cron 任务 + 检查逻辑 ⭐⭐⭐

### ⑤ 思考与执行分离

Harness 将 Orchestrator 和 Worker 分层。
**借鉴**：AI 对话的两种模式分离：
- **规划模式**：用户说"我想写下一章"，AI 先做大纲、不做具体写作
- **写作模式**：用户说"写正文"，AI 根据大纲和风格规范执行
- 两种模式上下文分离，不会互相污染

**工作量**：修改 chat.py 的路由分发 ⭐⭐

---

## 三、LangChain 的 Harness 改进案例

LangChain 仅改变 Harness（文档结构、验证回路、追踪系统），Terminal Bench 排名从 30 → 5，得分 52.8% → 66.5%。

**核心启示**：*底层模型一个参数都没动。*

对应到写作工坊：不用换 AI 模型，优化工具调用的方式就能显著提升质量。

### 当前问题

我们当前的 `POST /api/v1/tools/{name}/call` 是一个通用接口，AI 调用工具时：
- 不知道工具的上下文（哪些章节已写、角色有哪些）
- 没有验证循环（调用了不代表用对了）
- 没有失败重试

### 改进方案

工具调用加一层 Harness：
1. **工具描述增强**：每个工具的描述中加入上下文提示（当前项目状态）
2. **参数预检**：调用前验证参数合法性（已通过 Pydantic 实现）
3. **结果验证**：调用后 AI 自行评估结果是否符合预期
4. **失败重试**：自动重试 1-2 次再报错

**工作量**：修改 `tools_router.py` 和 `tool_definitions.py` ⭐

---

## 四、现有代码中的 Harness 元素

**已实现的：**
- `core/enums.py` — 架构约束（ChapterStatus/SceneType 等）
- `core/style_checker.py` — 反馈循环（5 条规则）
- `core/fsal.py` — 熵管理（缓存 + mtime 校验）
- `core/plugin_manager.py` — 可扩展性（钩子系统）
- `routers/workflow.py` — 写作工作流（流程控制）
- `.github/workflows/release.yml` — CI 自动化约束

**尚缺的：**
- 项目级 writing-guide.md（AGENTS.md 对应）
- 可扩展的 WritingRule 注册系统
- Agent-to-Agent 审查链
- 知识库园丁后台任务

---

## 五、建议实施优先级

| 项目 | 工作量 | 影响 | 优先级 |
|:-----|:------:|:----:|:------:|
| 工具调用 Harness 增强 | ⭐ | 高 | P0 |
| writing-guide.md 项目规范 | ⭐ | 中 | P1 |
| 可扩展 WritingRule 系统 | ⭐⭐ | 高 | P1 |
| Agent-to-Agent 审查链 | ⭐⭐ | 中 | P2 |
| 知识库园丁后台任务 | ⭐⭐⭐ | 中 | P3 |
