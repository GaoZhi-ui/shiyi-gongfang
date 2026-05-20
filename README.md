# 拾遗工坊

> 跨平台 AI 写作伴侣 — 为《泰拉拾遗录》创作的专属写作工坊。

---

## 功能清单

### ✍️ 写作

- **Markdown 编辑器** — 左侧编辑，右侧实时预览，支持双栏/单栏切换
- **章节管理** — 创建、编辑、删除、版本回溯
- **项目模板** — 空白文档 / 小说章节 / 随笔日记 / 知乎回答草稿
- **导出** — 支持 `.docx`、`.txt` 格式导出

### 📋 管理

- **项目工作区** — 多项目隔离，每个项目独立存储章节、场景、知识库
- **快照管理** — 随时保存/恢复项目快照
- **场景管理** — 场景级细纲组织
- **目标追踪** — 写作进度与计划管理
- **伏笔追踪** — 伏笔的添加、关联、状态追踪
- **人物档案** — 角色信息管理

### 🤖 AI

- **AI 聊天** — 侧栏浮动面板，流式输出，支持多轮对话
- **上下文关联** — 选中文本 `Ctrl+Shift+L` 送入 AI 分析/续写
- **深度审查** — AI 分析连贯性、风格一致性（需 API Key）
- **多 Provider** — DeepSeek / OpenAI / Anthropic 兼容

### 🛠 工具

- **自动审查** — 正则引擎 + 规则库，毫秒级检查拼写、句式、字数、密度
- **风格引擎** — 写作风格检测与一致性校验
- **知识库** — 作品设定、人物关系、时间线等速查
- **工作流引擎** — 分阶段写作流程管理

---

## 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 安装与启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python main.py
```

或双击 `run.bat`（Windows）一键启动：自动检测 Python 版本、创建虚拟环境、安装依赖、启动服务并打开浏览器。

浏览器访问 `http://localhost:8000`。

---

## 一键构建

构建独立可执行文件（无需 Python 环境）：

```bash
# 目录模式打包（推荐，启动更快）
python build.py --onedir

# 单文件模式打包
python build.py

# 清理旧构建后打包
python build.py --clean --onedir
```

产物输出到 `dist/` 目录。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + uvicorn |
| 前端 | 原生 HTML / CSS / JavaScript + Marked.js |
| 存储 | SQLite + 文件系统（.md） |
| AI | OpenAI 兼容接口（DeepSeek / OpenAI / Anthropic） |
| 打包 | PyInstaller（跨平台） |

---

## 项目结构

```
writing-app/
├── main.py                     # FastAPI 入口
├── requirements.txt            # pip 依赖
├── build.py                    # PyInstaller 构建脚本
├── build.sh                    # Linux/macOS 构建脚本
├── run.bat                     # Windows 一键启动
├── .env.example                # 环境变量模板
├── .gitignore
├── LICENSE                     # MIT 许可
├── README.md
│
├── core/                       # 业务核心
│   ├── __init__.py
│   ├── style_engine.py         # 写作风格引擎
│   ├── tool_definitions.py     # 工具定义
│   └── tools.py                # 工具实现
│
├── routers/                    # API 路由
│   ├── __init__.py
│   ├── chapters.py             # 章节 CRUD
│   ├── characters.py           # 人物档案
│   ├── chat.py                 # AI 流式聊天
│   ├── export.py               # 导出
│   ├── foreshadowing.py        # 伏笔追踪
│   ├── goals.py                # 目标管理
│   ├── health.py               # 健康检查
│   ├── keys.py                 # API Key 管理
│   ├── knowledge.py            # 知识库
│   ├── projects.py             # 项目管理
│   ├── sanitize.py             # 审查
│   ├── scenes.py               # 场景管理
│   ├── snapshots.py            # 快照
│   ├── tools.py                # 写作工具
│   ├── tools_router.py         # MCP 工具路由
│   └── workflow.py             # 工作流引擎
│
├── services/                   # 公共服务
│   └── key_manager.py          # 密钥加密存储
│
├── static/                     # 前端资源
│   ├── index.html
│   └── prototype.html
│
├── templates/                  # 项目模板
│   ├── arknights/
│   ├── default/
│   └── novel/
│
├── chapters/                   # 章节存档
├── characters/                 # 人物数据
├── scenes/                     # 场景细纲
├── knowledge/                  # 知识库
├── export/                     # 导出产物
├── foreshadowing/              # 伏笔数据
├── goals/                      # 写作目标
├── snapshots/                  # 项目快照
├── projects/                   # 用户项目
│   └── {project_id}/
│       ├── chapters/
│       ├── knowledge/
│       ├── scenes/
│       └── config.json
│
├── api-design.md               # API 设计文档
├── design-notes.md             # 设计笔记
├── distribution-plan.md        # 分发计划
├── improvement-plan.md         # 改进计划
├── security-review.md          # 安全审查
├── test-report-hanako.md       # 测试报告
├── test-report-xiaohei.md
├── test-report-xiaohuang.md
├── ui-improvements.md          # UI 改进计划
├── ux-improvement-plan.md
├── ux-plan.md
└── comparison.md               # 方案对比
```

---

## 离线降级

| 功能 | 有 API Key | 无 API Key |
|------|-----------|------------|
| 编辑器 | ✓ | ✓ |
| 快速审查 | ✓ | ✓ |
| 写作工具 | ✓ | ✓ |
| AI 聊天 | ✓ | 不可用 |
| 深度审查 | ✓ | 不可用 |
| 知识库 | ✓ | ✓ |
| 导入导出 | ✓ | ✓ |

---

## 许可协议

[MIT License](LICENSE)

Copyright (c) 2026 GaoZhi-ui
