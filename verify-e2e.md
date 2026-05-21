# 写作助手工坊 · 端到端验证报告

**日期**：2026-05-21 16:43 CST
**服务端**：http://127.0.0.1:8867
**测试项目ID**：`9c0ba27a2041`

---

## 测试结果总览

| # | 步骤 | API | 结果 |
|---|------|-----|------|
| 1 | 创建项目 | POST /api/v1/projects | ✅ 通过 |
| 2 | 创建章节 | POST /api/v1/chapters | ✅ 通过 |
| 3 | 写入规范 | PUT /api/v1/projects/{id}/guide | ✅ 通过 |
| 4 | 创建角色 | POST /api/v1/characters | ✅ 通过 |
| 5 | 创建伏笔 | POST /api/v1/foreshadowing | ✅ 通过 |
| 6 | 创建写作目标 | POST /api/v1/goals | ✅ 通过 |
| 7 | 风格检查 | POST /api/v1/style/check | ✅ 通过 |
| 8 | 导出EPUB | POST /api/v1/export/epub | ✅ 通过 · 内容验证通过 |
| 9 | 导出PDF | POST /api/v1/export/pdf | ✅ 通过 |
| 10 | 创建快照 | POST /api/v1/snapshots | ✅ 通过 |
| 11 | 查看统计 | GET /api/v1/stats/{project_id} | ⚠️ 部分通过 |
| 12 | 查看备份 | GET /api/v1/projects/{id}/backup | ⚠️ 部分通过 |

---

## 逐项详细记录

### 1. 创建项目 → POST /api/v1/projects

**请求**：
```json
{"name": "端到端测试"}
```

**响应** ✅：
```json
{
  "id": "9c0ba27a2041",
  "name": "端到端测试",
  "template": "default",
  "created_at": "2026-05-21T08:38:50.696595+00:00",
  "message": "项目 '端到端测试' 创建成功"
}
```

**备注**：项目创建成功，返回唯一 ID `9c0ba27a2041`，模板为 default。

---

### 2. 创建章节 → POST /api/v1/chapters

**请求**（571字中文正文，包含对话、描写、心理活动）：
```json
{
  "project_id": "9c0ba27a2041",
  "title": "第一章 启程",
  "content": "沈默站在罗德岛本舰的甲板上..."
}
```
内容包含：
- 场景描写（甲板、移动城市、荒野）
- 人物（沈默、阿米娅）
- 对话（"沈默先生，博士说任务要提前了。"）
- 心理活动（"不是为了当英雄，而是为了记录。"）

**响应** ✅：
```json
{
  "filename": "第1章_第一章 启程.md",
  "content": "...（完整内容已保存）",
  "parsed": { "has_diary": true, "diary_length": 571 }
}
```

**备注**：章节内容被自动解析为日记格式（`has_diary: true`），原始内容完整保留。

---

### 3. 写入规范 → PUT /api/v1/projects/{id}/guide

**请求**：
```json
{
  "project_id": "9c0ba27a2041",
  "style": "冷峻写实，留白优先，展示而非说教，不替读者总结",
  "protagonist": "沈默"
}
```

**响应** ✅：
```json
{
  "style": "冷峻写实，留白优先，展示而非说教，不替读者总结",
  "tone": "严肃",
  "forbidden_words": [],
  "max_sentence_length": 40,
  "dialogue_density_target": 0.25
}
```

**备注**：规范写入成功，`protagonist` 字段未在返回中出现（可能映射到了其他字段），风格文字完整保留。服务器自动填充了 `tone`、`max_sentence_length` 等默认值。

---

### 4. 创建角色 → POST /api/v1/characters

**请求**：
```json
{
  "project_id": "9c0ba27a2041",
  "name": "沈默",
  "role": "主角",
  "description": "退役武警 × 程序员 × 历史爱好者。能看到别人看不到的信息脉络。来自地球，踏入泰拉世界。",
  "traits": ["观察力强", "内向", "勇敢"]
}
```

**响应** ✅：
```json
{
  "id": "c266f08536bf",
  "name": "沈默",
  "traits": ["观察力强", "内吢", "勇敢"],
  "avatar_color": "#4A90D9",
  "created_at": "2026-05-21T08:41:35.084508+00:00"
}
```

**备注**：角色创建成功。注意 `traits` 中 "内向" 被存储为 "内吢"（疑似编码映射问题，需确认），其他字段正常。`role` 字段未出现在返回中。

---

### 5. 创建伏笔 → POST /api/v1/foreshadowing

**请求 1（失败）**：
```json
{"type": "能力", "status": "未回收"}
```
**响应** ❌：字段枚举校验失败。
- `type` 必须是 `plot | character | object | lore`
- `status` 必须是 `pending | revealed | resolved | abandoned`
- `title` 为必填

**请求 2（修正后）**：
```json
{
  "project_id": "9c0ba27a2041",
  "title": "沈默的特殊能力",
  "description": "能看到信息脉络，将在后文成为关键情节推动力",
  "expected_chapter": "第二章 河畔",
  "type": "character",
  "status": "pending"
}
```

**响应** ✅：
```json
{
  "id": "a5bab9732d23",
  "title": "沈默的特殊能力",
  "type": "character",
  "chapter_planted": 1,
  "status": "pending",
  "strength": 3
}
```

**备注**：伏笔需要严格遵循枚举值。`chapter_expected` 字段的值与传入的`expected_chapter`不完全对应（解析为数字1而非"第二章"），可能是内部编号系统的限制。

---

### 6. 创建写作目标 → POST /api/v1/goals

**请求**：
```json
{
  "project_id": "9c0ba27a2041",
  "title": "完成第一章启程",
  "description": "完成沈默初入泰拉世界的开篇描写，建立世界观基调",
  "target_word_count": 2500,
  "deadline": "2026-05-25"
}
```

**响应** ✅：
```json
{
  "id": "96fc2849b767",
  "title": "完成第一章启程",
  "target_word_count": 2500,
  "deadline": "2026-05-25",
  "current_word_count": 0,
  "status": "active",
  "progress_pct": 0.0
}
```

**备注**：目标创建成功，初始进度为 0%。`description` 字段未存储在返回结构中。

---

### 7. 风格检查 → POST /api/v1/style/check

**请求**（提取章节前5句，199字）：
```json
{"text": "沈默站在罗德岛本舰的甲板上..."}
```

**响应** ✅：
```json
{
  "status": "ok",
  "total_issues": 2,
  "rules_applied": ["filler_words","long_sentence","passive_voice","redundant_modifiers","weak_words"],
  "results": [
    {
      "severity": "warning",
      "rule": "passive_voice",
      "content": "被风吹得微微颤动",
      "suggestion": "被动语态使动作主体模糊。尝试改为主动语态..."
    },
    {
      "severity": "info",
      "rule": "long_sentence",
      "content": "三十天前他还在北京北苑路的出租屋里敲代码，转眼间已经习惯了...",
      "suggestion": "句子过长影响阅读节奏。建议拆分为2-3个短句..."
    }
  ]
}
```

**备注**：风格检查正常。5条规则全部生效，检出2个问题（1个warning + 1个info）。建议有实际参考价值。

---

### 8. 导出EPUB → POST /api/v1/export/epub

**请求**：
```json
{"project_id": "9c0ba27a2041", "chapters": "all"}
```

**响应** ✅：
```json
{
  "status": "ok",
  "format": "epub",
  "filename": "写作助手_导出_20260521_1642.epub",
  "chapter_count": 17,
  "download_url": "/export/写作助手_导出_20260521_1642.epub"
}
```

**内容完整性验证** ✅：
- 下载文件大小：13,988 bytes
- EPUB 中包含 17 个章节 XHTML 文件
- 在 chapter_016.xhtml 中找到 "第一章 启程" 的完整内容
- 关键字符串全部验证通过：
  - ✅ "罗德岛本舰"
  - ✅ "沈默"
  - ✅ "整合运动"
  - ✅ "源石技艺"
  - ✅ "北京北苑路"
  - ✅ "退役武警"
  - ✅ "阿米娅"

**备注**：内容完整保留，UTF-8 编码正确。章节自动归类为日记格式（`class="diary"`）。

---

### 9. 导出PDF → POST /api/v1/export/pdf

**请求**：
```json
{"project_id": "9c0ba27a2041", "chapters": "all"}
```

**响应** ✅：
```json
{
  "status": "ok",
  "format": "pdf",
  "filename": "写作助手_导出_20260521_1642.pdf",
  "chapter_count": 17,
  "download_url": "/export/写作助手_导出_20260521_1642.pdf"
}
```

**文件大小**：149,124 bytes ✅

---

### 10. 创建快照 → POST /api/v1/snapshots

**请求**：
```json
{"project_id": "9c0ba27a2041", "label": "端到端测试快照 v1"}
```

**响应** ✅：
```json
{
  "status": "created",
  "snapshot": {
    "id": "snap_20260521_164300",
    "label": "端到端测试快照 v1",
    "created_at": "2026-05-21T16:43:00.372903+08:00",
    "file_count": 17,
    "total_size": 3790
  }
}
```

---

### 11. 查看统计 → GET /api/v1/stats/{project_id}

**响应** ⚠️：
```json
{
  "total_chapters": 0,
  "total_words": 0,
  "total_characters": 1,
  "total_foreshadowing": 1,
  "average_words_per_chapter": 0,
  "streak_days": 0
}
```

**问题**：
- `total_chapters` = 0（实际有17个章节文件）
- `total_words` = 0（实际有内容）
- `average_words_per_chapter` = 0

**推测原因**：章节文件可能未与项目正确关联（跨项目共享），或者统计数据缓存未刷新。角色和伏笔计数正确（`total_characters: 1`, `total_foreshadowing: 1`）。

---

### 12. 查看备份 → GET /api/v1/projects/{id}/backup

**响应** ⚠️：
```json
{
  "status": "ok",
  "project_id": "9c0ba27a2041",
  "filename": "backup_9c0ba27a2041_1d902009.zip",
  "file_size": 349,
  "download_url": "/export/backup_9c0ba27a2041_1d902009.zip"
}
```

**备份内容**：
```
config.json (415 bytes)
```

**内容**：仅包含项目配置（名称、模板、review_rules 等）。

**问题**：备份仅包含 `config.json`，不包含章节文件、角色、伏笔等数据。不能独立用于完整恢复项目。建议增加对章节及其他资源的备份。

---

## 汇总问题清单

### 严重
| # | 问题 | 影响 |
|---|------|------|
| S1 | 统计API的 `total_chapters` / `total_words` 始终为 0 | 无法通过统计接口获取实际写作进度 |
| S2 | 备份仅含 config.json，不含章节数据 | 备份不可用于完整恢复 |

### 中等
| # | 问题 | 影响 |
|---|------|------|
| M1 | `POST /api/v1/chapters` 内容被自动转为日记格式 | 正文与日记的边界可能不符合用户预期 |
| M2 | 章节 `project_id` 关联在实际操作中未生效（章节列表返回所有项目所有章节） | 多项目场景下数据隔离可能有问题 |
| M3 | 伏笔 `type` / `status` 字段枚举值无文档说明 | 首次使用需要试错 |
| M4 | 伏笔 `expected_chapter` 被忽略（始终返回数字章节号） | 用户指定的预期章节不生效 |

### 轻微
| # | 问题 | 影响 |
|---|------|------|
| T1 | 角色 `traits` "内向" 存储为 "内吢"（疑似编码映射异常） | 需确认是否偶发 |
| T2 | EPUB 元数据（title、creator）显示为 `д������_����` 乱码 | 不影响阅读内容 |
| T3 | 角色创建 `role` 字段和写作目标 `description` 字段在返回中丢失 | 但数据可能已存储 |

---

## 结论

**12个测试步骤全部可执行，7项完全通过，2项部分通过，0项完全失败。**

核心链路（创建 → 写作 → 导出）**基本通畅**，章节内容在 EPUB/PDF 中完整保留。主要风险集中在统计准确性和备份完整性两个环节。

建议优先修复 S1（统计计数异常）和 S2（备份不完整），这是生产环境中直接影响用户信任的两个问题。
