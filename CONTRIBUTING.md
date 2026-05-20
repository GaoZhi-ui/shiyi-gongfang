# 贡献指南

欢迎贡献！无论是 Bug 修复、功能建议还是文档改进，请先花几分钟阅读本指南。

---

## 提交 Issue

### Bug 报告

创建 Issue 时选择 Bug 模板，并包含以下信息：

- **环境** — 操作系统 + Python 版本
- **复现步骤** — 从启动到问题出现的完整操作
- **实际行为 vs 预期行为** — 出什么问题，本应是什么
- **日志/截图** — 终端输出或浏览器控制台错误（如有）

### 功能建议

- 说明提议解决的问题或场景
- 如果涉及 UI 改动，欢迎附带线框图或描述
- 指出该功能对离线/在线模式的影响

### 提问

使用 Discussion 标签提问，不保证一一回复，但好问题会被归档到 FAQ。

---

## PR 规范

### 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 稳定版，保持可发布状态 |
| `dev` | 日常开发，功能集成 |
| `feature/*` | 新功能分支，从 `dev` 切出 |
| `fix/*` | Bug 修复分支 |

### 提 PR 前 checklist

- [ ] 代码通过编译（`python -m py_compile main.py`）
- [ ] 新增功能包含对应测试或审查规则
- [ ] README 已同步（如有界面或 API 变化）
- [ ] 遵循现有代码风格
- [ ] Commit 信息清晰、原子化

### 提交流程

1. 从 `dev` 切出工作分支
2. 实现功能或修复，保持 commit 原子化
3. 推送后提交 Pull Request 到 `dev` 分支
4. 等待 review，根据反馈修改
5. 合并后工作分支会被删除

### Commit 信息

建议用中文或英文清晰描述改动内容：

```
feat: 新增场景合并功能
fix: 审查引擎未正确处理空章节
docs: 更新 API 路由文档
refactor: 抽取审查规则为独立模块
```

---

## 本地开发环境搭建

### 前置条件

- Python 3.10+
- Git

### 步骤

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/你的用户名/writing-app.git
cd writing-app

# 2. 创建虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
# source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装开发/构建依赖
pip install pyinstaller  # 如需构建 exe

# 5. 启动开发服务器
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 环境变量

复制 `.env.example` 为 `.env`，按需配置：

```
# API 接口地址（默认 DeepSeek）
API_BASE_URL=https://api.deepseek.com/v1
# 从对应平台获取
API_KEY=sk-your-key-here
# 模型名
API_MODEL=deepseek-chat
```

> `.env` 已加入 `.gitignore`，不会误提交。

### 验证开发环境

```
服务启动后访问 http://localhost:8000
  ├── 欢迎页正常渲染     — 前端服务正常
  ├── 可创建新项目       — API 正常
  └── 编辑器正常输入预览 — 核心功能正常

# 运行审查引擎自检
python -c "from core.tools import review_text; print(review_text('测试文本'))"
```

---

## 代码风格

### Python

- **缩进** — 4 空格，禁止 Tab
- **行宽** — 不超过 88 字符（兼容 Black 默认值）
- **命名** — 函数/变量用 `snake_case`，类用 `PascalCase`，常量用 `UPPER_CASE`
- **类型注解** — 所有公开函数必须标注参数和返回值类型
- **Docstring** — 模块/类/公开函数使用 `"""三重双引号"""` 写简短说明
- **Imports** — 标准库 → 第三方 → 本地模块，每组空行分隔

```python
"""模块简短说明。"""

import os
import re
from pathlib import Path

import httpx
from fastapi import APIRouter

from core.tools import review_text
```

### Python（FastAPI 路由）

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/example", tags=["example"])


@router.get("/")
async def list_items():
    """返回所有条目。"""
    return {"items": []}
```

### 前端

- **HTML** — 语义化标签，缩进 2 空格
- **CSS** — 类名使用 `kebab-case`，避免 `!important`
- **JavaScript** — 函数用 `camelCase`，常量用 `UPPER_CASE`，缩进 2 空格

### 审查规则扩展

如需新增审查项，在 `core/tools.py` 的 `review_text` 函数中添加规则。一条规则 = 一个名称 + 一个正则/条件 + 一条错误消息。

```python
# 示例：检查"他"字频次
HE_COUNT = len(re.findall(r'他', text))
if HE_COUNT > 30:
    issues.append({
        "type": "style",
        "message": f'"他"字出现 {HE_COUNT} 次，建议控制在 30 次以内',
        "severity": "warning",
    })
```

---

## API Key 安全

- API Key 使用本地加密存储，绑定当前机器
- 提交代码时确保 `.env` 不被包含
- 审查代码时不触碰密钥相关的明文日志

---

再次感谢你的贡献。
