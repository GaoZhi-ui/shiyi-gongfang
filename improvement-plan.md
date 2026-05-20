# 拾遗工坊 · 改进方案

> 调研日期：2026-05-20
> 范围：本地写作工具最佳实践 + AI写作助手必备功能 + 中文写作工具痛点
> 竞品参考：Scrivener, Ulysses, iA Writer, Obsidian, Sudowrite, Novelcrafter, Lex.page, Lattics, yWriter

---

## 一、调研发现汇总

### 1.1 本地写作工具最佳实践

| 竞品 | 核心范式 | 关键功能 | 学习曲线 | 平台 |
|------|----------|----------|----------|------|
| **Scrivener** | 文档管理式写作 | Binder树/Corkboard卡片/Snapshots快照/Outliner大纲/Compile编译/目标跟踪/研究文件夹 | 高 | Win/Mac/iOS |
| **Ulysses** | 沉浸式Markdown写作 | 组+文稿层次/过滤组/修订模式/写作目标/第二编辑器/直接发布/版本历史 | 中 | Mac/iOS |
| **iA Writer** | 极简无干扰写作 | Focus模式/语法高亮(词性着色)/Content Blocks/Style Check/文库链接 | 低 | Win/Mac/iOS/Android |
| **Obsidian** | 双向链接知识库 | 图谱视图/插件生态/本地Markdown/双链/标签系统/Canvas画布 | 中 | 全平台 |

**共性特征：**
- 写作大纲可视化（Scrivener Corkboard / Obsidian Graph / Ulysses Groups）
- 无干扰编辑环境（Focus Mode / 全屏 / 打字机模式）
- 版本追溯能力（Snapshots / 版本历史 / Git）
- 多格式导出（ePub / PDF / DOCX / HTML）
- 写作目标追踪（字数/时间/进度环）
- 素材/研究内容与正文同项目管理

### 1.2 AI写作助手必备功能

| 竞品 | AI核心能力 | 独创亮点 | 中文支持 |
|------|------------|----------|----------|
| **Sudowrite** | 风格感知续写/五感描写/多版本改写/结构分析 | Story Bible逐步引导/插件市场(1000+)/Canvas情节地图 | 弱（中文常跑英文） |
| **Novelcrafter** | 场景beats引导续写/Chat→Extract一键提取/Codex自动关联 | 透明提示词系统/自选AI供应商/Review仪表盘 | 有限(英文为主) |
| **Lex.page** | AI Ghostwriter/改写/语气调整 | 极简编辑器+AI内联/邮件式流畅交互 | 有限 |
| **KimiAI (中文)** | 超长上下文(200w字)/素材整合/中文适配 | 200万token记忆/多文档协同 | 强 |
| **FeelFish (中文)** | 全流程创作/角色世界观构建/上下文管理 | 多模型适配/本地保存/场景化设计 | 强 |

**AI写作工具的成熟功能图谱：**

```
构思阶段 ─→ 大纲生成 / 头脑风暴 / 灵感激发
规划阶段 ─→ Story Bible / Codex / 世界观设定
写作阶段 ─→ 风格续写 / 扩写 / 描写增强 / 多版本改写
审校阶段 ─→ 结构分析 / 逻辑校验 / 一致性检查
管理阶段 ─→ 角色出场统计 / 字数仪表盘 / 关联图谱
```

### 1.3 中文写作工具痛点（用户反馈整理）

**数据：** 72%创作者曾遭遇"工具选不对，创作反受累"；35%产品功能冗余且场景适配不足（艾瑞咨询2026）。

**核心痛点列表：**

| 痛点 | 描述 | 涉及场景 |
|------|------|----------|
| **AI中文写作质量不稳定** | 英文工具遇到中文提示词跑偏（英文/韩文乱入）、生成内容生硬不自然 | 续写/扩写/改写 |
| **高质量长文连贯性不足** | AI写着写着就忘记人物设定/世界观规则，导致人设崩塌、情节矛盾 | 长篇连载 |
| **写作大纲管理工具脱节** | 用Scrivener写大纲但在AI工具里写正文，两套体系之间频繁切换 | 全流程 |
| **中文排版/编辑器体验粗糙** | 英文工具对中文标点、段落间距、字体的支持不到位 | 编辑/导出 |
| **缺乏"创作节奏"管理** | 没有字数目标/每日进度/章节状态等创作管理功能 | 写作管理 |
| **灵感→正文之间的摩擦大** | 灵光一现的念头没有快速入口转为场景/章节 | 灵感记录 |
| **跨设备/云端体验差** | 本地工具+AI调用之间的数据同步复杂 | 日常使用 |
| **版本迭代中"功能堆砌"** | 追求功能数量而非深度体验，工具越更新越臃肿 | 产品设计 |
| **缺少适合中文的审查工具** | 英文有Grammarly/Hemingway，但中文缺乏密度/句式/修辞层面的检查 | 审校 |
| **大纲→正文→导出的闭环不完整** | 写完了却要手动排版、手动转格式、手动交付 | 发布流程 |

---

## 二、改进方案

### 2.1 功能改进矩阵

| # | 改进项 | 竞品参考 | 优先级 | 预估工作量 | 说明 |
|---|--------|----------|--------|------------|------|
| 1 | **场景级管理（章节下分场景）** | yWriter, Novelcrafter, Scrivener | **P0** | 中(3-5天) | 当前章节文件是单一.md，改为章节→场景两级。每个场景可独立写概要、挂角色/关联伏笔。场景卡片可拖拽排序 |
| 2 | **可视化场景看板（Corkboard）** | Scrivener, Novelcrafter | **P0** | 大(5-8天) | 将场景以卡片形式铺开在画布上，显示概要/状态/字数/角色标签，支持拖拽重组和筛选过滤。可以基于现有三栏布局的右侧Panel扩展 |
| 3 | **AI续写/扩写/重写** | Sudowrite, Novelcrafter | **P0** | 中(3-5天) | 选中文本后浮出工具栏：续写(从光标处向后)、扩写(展开当前段)、缩写(压缩)、重写(多版本)。调用现有AI对话能力但封装为写作专用交互 |
| 4 | **版本快照（Snapshots）** | Scrivener | **P0** | 小(1-2天) | 修改前自动或手动拍快照，保存当前.md副本到 `_snapshots/` 目录。支持差异对比和回退。对频繁改稿的写作场景极为实用 |
| 5 | **Chat→写作内容一键提取** | Novelcrafter | **P1** | 中(2-3天) | AI对话中产生的角色设定/场景描述/对话片段，点击即可提取为场景内容或Codex条目，减少从对话到正文的"搬运"成本 |
| 6 | **Codex式自动知识关联** | Novelcrafter | **P1** | 大(5-7天) | AI在续写/审查时自动识别当前内容涉及的角色/地点/设定，关联到知识库条目。用户可持续右面板看到"当前高活跃条目" |
| 7 | **写作目标追踪系统** | Ulysses, Scrivener | **P1** | 小(1-2天) | 项目总字数目标 + 章节独立目标 + 每日写作目标。进度环/进度条显示在底栏或章节列表。可与现有审查的"字数统计"合并 |
| 8 | **分屏对照模式** | Ulysses, Scrivener | **P1** | 小(1天) | 同时打开两个.md文件分屏对比（原文 vs 修改版，或大纲 vs 正文）。可复用现有编辑区域的split布局 |
| 9 | **关键词标签 + 筛选系统** | Scrivener | **P1** | 中(2-3天) | 给场景/章节打标签（人物/地点/时间线/状态）。左侧增加标签筛选器，点击标签即可过滤显示对应场景 |
| 10 | **导出编译引擎增强** | Scrivener, Ulysses | **P2** | 中(3-4天) | 当前手动MD→docx，改为编译管线：选择章节范围→选择格式模板→一键导出。支持ePub/PDF/DOCX/HTML。整合Pandoc或python-docx |
| 11 | **灵感/片段捕获** | Novelcrafter, iA Writer | **P2** | 小(1天) | 右下角浮动"灵感"按钮，随时弹出极简编辑器记录灵感片段。支持标签标记，可一键插入到指定场景 |
| 12 | **多Agent/多角色写作助手** | LobeHub, Sudowrite | **P2** | 大(5-8天) | 分角色AI助手：一个负责检查逻辑/一个负责润色文笔/一个负责伏笔追踪。在对话中通过 @ 切换助手 |
| 13 | **打字机Focus模式** | Ulysses, iA Writer | **P2** | 小(0.5天) | 编辑时当前行/段始终居中或置顶，其他内容半透明。CSS实现，纯前端改动 |
| 14 | **修订模式（样式检查）** | Ulysses, iA Writer | **P2** | 中(2-3天) | 长句标黄 / 重复词开头提醒 / 被动语态检测 / 替代词建议。可与现有审查模块合并扩展 |
| 15 | **智能过滤组** | Ulysses | **P2** | 中(2-3天) | 自动分组："今日修改过"/"字数不足800"/"待审查"等。基于标签/日期/字数的虚拟筛选 |
| 16 | **编辑区语法高亮** | iA Writer | **P2** | 小(1天) | 对编辑器中的名词/动词/形容词/副词进行词性着色（中文分词+词性标注）。辅助文笔审查 |
| 17 | **项目统计仪表盘** | Novelcrafter, yWriter | **P2** | 中(2-3天) | 总字数/各章字数分布/场景数量/角色出场频次/写作天数/日均产量。用图表展示 |
| 18 | **画布/思维导图式情节规划** | Lattics, Sudowrite Canvas | **P2** | 大(5-7天) | 在无限画布上用节点和连线规划情节走向、人物关系、时间线。参考Obsidian Canvas |
| 19 | **插件/扩展框架** | Sudowrite, Open WebUI | **P3** | 极大(10-15天) | 定义插件接口规范，开放第三方扩展能力。长期生态建设，非当前阶段核心 |
| 20 | **Web搜索集成** | Open WebUI | **P3** | 中(3-4天) | 对话中可直接搜索网络资料并注入上下文。写作调研场景有用但非高频 |

### 2.2 优先级路线图

```
第一梯队（P0 · 立即实施）
├── 场景级管理（章节下分场景）
├── 可视化场景看板（Corkboard）
├── AI续写/扩写/重写
├── 版本快照（Snapshots）

第二梯队（P1 · 下一轮迭代）
├── Chat→写作内容一键提取
├── Codex式自动知识关联
├── 写作目标追踪系统
├── 分屏对照模式
├── 关键词标签 + 筛选系统

第三梯队（P2 · 后期规划）
├── 导出编译引擎增强
├── 灵感/片段捕获
├── 多Agent/多角色写作助手
├── 打字机Focus模式
├── 修订模式（样式检查）
├── 智能过滤组
├── 编辑区语法高亮
├── 项目统计仪表盘
├── 画布/思维导图式情节规划

第四梯队（P3 · 长远考虑）
├── 插件/扩展框架
├── Web搜索集成
```

### 2.3 拾遗工坊差异化优势（应维持和强化）

1. **中文写作专属审查** — 密度检查/句式分析/日记钩子检查，竞品无此能力。保持并扩展
2. **9阶段写作管线** — 比Sudowrite Story Bible更结构化，比Novelcrafter Plan更完整。保持
3. **20个知识库文件体系** — 比Novelcrafter Codex更系统化。可增加自动关联
4. **纯本地 + API Key加密** — 隐私安全性优于所有SaaS工具。保持
5. **低使用成本** — 自有API Key，不依附于任何SaaS订阅。保持

### 2.4 不应盲目跟风的方向

- ❌ 图像生成/角色可视化 — 偏离核心写作场景
- ❌ 语音通话/语音输入 — 写作辅助场景低频
- ❌ 多用户协作 — 单用户工具，增加复杂度不增加价值
- ❌ 自有大模型 — 成本极高，API聚合+提示词工程足够
- ❌ 过度追求"全平台" — 当前锁定Windows桌面端更务实

---

## 三、关键参考来源

### 竞品官方
- [Scrivener](https://www.literatureandlatte.com/) — Corkboard / Binder / Snapshots / Compile
- [Ulysses](https://ulysses.app/) — 组+文稿 / 过滤组 / 修订模式 / 写作目标
- [iA Writer](https://ia.net/writer) — Focus Mode / 语法高亮 / Content Blocks
- [Sudowrite](https://sudowrite.com/) — Story Bible / Write / Describe / Rewrite / Brainstorm
- [Novelcrafter](https://www.novelcrafter.com/) — Codex / Plan / Scene Beats / Chat→Extract / 透明提示词
- [yWriter](https://www.spacejock.com/yWriter.html) — 场景级管理 / 角色DB / 故事板

### 深度评测
- 少数派《我的 Ulysses 使用心得》 — [sspai.com/post/68843](https://sspai.com/post/68843)
- Writer Gadgets《Scrivener Review 2025》 — [writergadgets.com/scrivener-review](https://writergadgets.com/scrivener-review/)
- AITNT《Novelcrafter · 这就是AI写小说该有的样子》 — [aitntnews.com](https://www.aitntnews.com/newDetail.html?newId=8423)
- 人人都是产品经理《浅尝AI写作工具之Sudowrite》 — [woshipm.com/evaluating/5991377](https://www.woshipm.com/evaluating/5991377)
- Lattics《Lattics vs Scrivener 对比评测》 — [lattics.com/zh-CN/review/lattics-vs-scrivener](https://lattics.com/zh-CN/review/lattics-vs-scrivener)
- LeavesCN《全面解析AI写小说工具NovelCrafter》 — [leavescn.com/Forums/Detail/18218](https://www.leavescn.com/Forums/Detail/18218)
- CSDN《2026年5月AI写小说工具横评》 — 搜索可得
- 搜狐《2026优质小说写作软件推荐指南》 — [sohu.com](https://www.sohu.com/a/973247895_120424706)

### 行业数据
- 艾瑞咨询《2026年中国AI写作行业发展报告》 — 37%年增长率，35%产品功能冗余，72%创作者选择困境

---

*生成于 2026-05-20 · 基于对10+竞品的深度调研*
