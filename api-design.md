# 本机写作工坊 — 后端 API 设计

> 设计日期：2026-05-20
> 技术栈：FastAPI + uvicorn + 单页前端
> 部署：本机运行，pip install 启动

---

## 目录

1. [项目结构与数据流](#1-项目结构与数据流)
2. [API 路由总表](#2-api-路由总表)
3. [文件系统接口设计](#3-文件系统接口设计)
4. [API Key 管理方案](#4-api-key-管理方案)
5. [聊天接口消息格式](#5-聊天接口消息格式)
6. [工作流状态追踪](#6-工作流状态追踪)
7. [工具脚本执行接口](#7-工具脚本执行接口)
8. [错误处理规范](#8-错误处理规范)

---

## 1. 项目结构与数据流

### 目录布局

```
writing-app/
├── main.py                 # FastAPI 入口，uvicorn 启动
├── requirements.txt        # 依赖：fastapi, uvicorn, httpx, pyyaml, cryptography
├── .env                    # （不提交）API Key 存储，加密或明文
├── config.yaml             # 应用配置（目录路径、模型选择等）
│
├── routers/
│   ├── __init__.py
│   ├── chat.py             # AI 聊天路由
│   ├── knowledge.py        # 知识库路由
│   ├── chapters.py         # 章节文件路由
│   ├── tools.py            # 工具脚本路由（_review.py, guard.py）
│   ├── workflow.py         # 流程状态路由
│   └── keys.py             # API Key 管理路由
│
├── services/
│   ├── __init__.py
│   ├── llm_client.py       # 多模型统一调用层（DeepSeek/OpenAI/Claude）
│   ├── knowledge_reader.py # 知识库文件读取
│   ├── chapter_manager.py  # 章节文件 CRUD
│   ├── script_runner.py    # 安全运行 .py 脚本并捕获输出
│   └── key_manager.py      # API Key 加解密存储
│
├── models/
│   ├── __init__.py
│   ├── chat_schemas.py     # 请求/响应 Pydantic 模型
│   ├── file_schemas.py     # 文件相关数据结构
│   └── workflow_schemas.py # 工作流状态模型
│
├── static/
│   └── index.html          # 前端 SPA（已写好原型）
│
├── data/
│   ├── keys.json           # 加密后的 API Key 存储
│   ├── chat_history.json   # 聊天历史
│   └── workflow_state.json # 当前流程状态持久化
│
└── tools/                  # 可执行脚本所在目录的引用（通过 config.yaml 定位）
    └── → 指向 writing/tales-of-tera/ 或其他项目
```

### 数据流图（简化）

```
浏览器 (SPA) ──HTTP──→ FastAPI ──→ [本机文件系统]
                              │
                              ├──→ [DeepSeek/OpenAI/Claude API] (通过 httpx)
                              │
                              └──→ [subprocess] _review.py / guard.py
```

---

## 2. API 路由总表

所有路由前缀 `/api/v1`。

### 2.1 健康检查

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/health` | 服务状态，返回版本号和配置概览 |

### 2.2 API Key 管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/keys` | 查看已配置的 key 列表（仅返回是否已配置，不返回密钥原文） |
| POST | `/api/v1/keys` | 新增/更新某个 provider 的 API Key |
| DELETE | `/api/v1/keys/{provider}` | 删除某个 provider 的 key |
| GET | `/api/v1/keys/{provider}/test` | 测试某个 provider 的 key 是否可用（发送短请求验证） |

**请求体 (POST/PUT)：**
```json
{
  "provider": "deepseek",
  "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

### 2.3 知识库文件

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/knowledge` | 列出知识库文件清单（标题、文件名、修改时间、字数） |
| GET | `/api/v1/knowledge/{filepath}` | 读取某个知识库文件内容 |
| POST | `/api/v1/knowledge/{filepath}` | 更新知识库文件（写入新内容） |

**路径参数说明：** `{filepath}` 经过 URL 编码，支持点号和路径分隔符。
例如 `地理地图.md` → `%E5%9C%B0%E7%90%86%E5%9C%B0%E5%9B%BE.md`

**响应 GET /api/v1/knowledge：**
```json
{
  "files": [
    {
      "name": "地理地图.md",
      "title": "地理地图",
      "size": 15234,
      "modified": "2026-05-19T18:33:00+08:00",
      "cjk_chars": 14020
    },
    {
      "name": "伏笔与线索追踪表.md",
      "title": "伏笔与线索追踪表",
      "size": 8901,
      "modified": "2026-05-20T10:15:00+08:00",
      "cjk_chars": 8030
    }
  ]
}
```

### 2.4 章节文件

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/chapters` | 列出所有章节文件（含锚点、合集），支持 `?status=` 过滤 |
| GET | `/api/v1/chapters/{filename}` | 读取某个章节文件 |
| POST | `/api/v1/chapters` | 创建新章节文件 |
| PUT | `/api/v1/chapters/{filename}` | 覆盖写入章节文件 |
| DELETE | `/api/v1/chapters/{filename}` | 删除章节文件 |
| POST | `/api/v1/chapters/{filename}/rename` | 重命名章节文件 |
| GET | `/api/v1/chapters/{filename}/diff` | 显示本章的历史版本差异（如果启用 git 追踪） |

**请求体 (POST/PUT)：**
```json
{
  "content": "# 第40章_离开之前\n\n沈默在清晨收拾行囊...\n\n---\n\n他留了米，加了盐。我留了字。"
}
```

**创建时的自动命名建议：** POST 时如果未提供文件名，服务端根据 `title` 字段自动生成 `第X章_标题.md`。

### 2.5 工具脚本

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/tools/review` | 对指定章节运行 `_review.py` |
| POST | `/api/v1/tools/guard-scan` | 对指定章节运行 `guard.py scan` |
| POST | `/api/v1/tools/guard-filter` | 对指定目录运行 `guard.py filter` |
| GET | `/api/v1/tools/list` | 列出可用工具脚本 |

**请求体 (POST /tools/review)：**
```json
{
  "chapter": "第40章_离开之前.md",
  "project": "tales-of-tera"
}
```

**响应：**
```json
{
  "status": "ok",
  "output": "第40章_离开之前.md: OK",
  "issues": [],
  "metrics": {
    "cjk_chars": 2450,
    "sentence_density": 5.2,
    "diary_length": 95
  }
}
```

有 issues 时的响应：
```json
{
  "status": "issues_found",
  "output": "第40章_离开之前.md: 字数2340(需2000+); 句式重复3次",
  "issues": [
    {"type": "word_count", "severity": "warning", "detail": "字数2340 (基线2500±300)"},
    {"type": "sentence_pattern", "severity": "warning", "detail": "\"不是...是\"句式重复3次"}
  ],
  "metrics": { ... }
}
```

### 2.6 AI 聊天

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/chat/completions` | 发送消息，获取流式或完整响应 |
| GET | `/api/v1/chat/history` | 获取当前会话历史 |
| DELETE | `/api/v1/chat/history` | 清空当前会话历史 |
| POST | `/api/v1/chat/history/export` | 导出聊天记录为 Markdown 文件 |

### 2.7 工作流状态

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/workflow` | 获取当前项目的工作流状态 |
| PUT | `/api/v1/workflow` | 更新工作流阶段 |
| POST | `/api/v1/workflow/checklist/{stage}` | 更新某阶段的检查项完成状态 |
| GET | `/api/v1/workflow/history` | 查看近期工作流变更记录 |

---

## 3. 文件系统接口

### 3.1 核心路径配置

所有路径通过 `config.yaml` 配置，不在代码中硬编码：

```yaml
# config.yaml
projects:
  tales-of-tera:
    name: "泰拉拾遗录"
    root: "E:/openhanako-work/writing/tales-of-tera"
    chapters_dir: "chapters"
    chapters_raw_dir: "chapters_raw"
    review_script: "_review.py"
    guard_script: null  # 使用全局路径

knowledge_base:
  terra:
    name: "泰拉拾遗录知识库"
    root: "E:/openhanako-work/knowledge_base/泰拉拾遗录"
    files: []  # 留空自动扫描所有 .md 文件

global_tools:
  guard: "E:/openhanako-work/terra-writing-skill/pipeline-guard/guard.py"

active_project: "tales-of-tera"
```

### 3.2 文件读取安全约束

```
┌─────────────────────────────────────────────┐
│            FastAPI 文件服务层                  │
│                                              │
│  1. 路径规范化：os.path.realpath()            │
│  2. 前缀校验：必须在已注册的根目录下            │
│  3. 扩展名白名单：.md .txt .json .yaml .yml   │
│  4. 编码：统一 UTF-8                          │
│  5. 文件大小上限：5MB（传输限制）               │
│  6. 读取加锁：同一文件写入时阻塞读取            │
└─────────────────────────────────────────────┘
```

路径穿越防护实现：

```python
# services/knowledge_reader.py 核心逻辑（伪码）

ALLOWED_EXTENSIONS = {'.md', '.txt', '.json'}
MAX_FILE_SIZE = 5 * 1024 * 1024

def safe_read(base_dir: Path, relative_path: str) -> str:
    # 1. 解析目标路径
    target = (base_dir / relative_path).resolve()
    # 2. 验证目标路径在 base_dir 下
    if not str(target).startswith(str(base_dir.resolve())):
        raise PathTraversalError("路径越界")
    # 3. 验证扩展名
    if target.suffix not in ALLOWED_EXTENSIONS:
        raise FileTypeError("不支持的文件类型")
    # 4. 验证文件大小
    if target.stat().st_size > MAX_FILE_SIZE:
        raise FileTooLargeError("文件过大，请使用分段读取模式")
    # 5. 读取
    return target.read_text(encoding='utf-8')
```

### 3.3 章节文件规范

章节文件命名规则：

| 类型 | 格式 | 示例 |
|------|------|------|
| 正文 | `第X章_标题.md` | `第40章_离开之前.md` |
| 锚点 | `第X章_标题.md`（仍在 chapters/ 下） | `第40章_离开之前.md` |
| 合集 | `第X-Y章_合集.md` | `第10-12章_合集.md` |
| 草稿 | `_tmp_` 前缀 | `_tmp_第40章_初稿.md` |

文件结构（正文）：

```markdown
# 第40章_离开之前

（正文内容，Markdown 格式）

---

（日记部分，在 `---` 分隔符之后）
```

### 3.4 运行脚本的安全执行

```python
# services/script_runner.py 核心逻辑（伪码）

import subprocess, os
from pathlib import Path

class ScriptRunner:
    # 白名单：可运行的脚本路径
    ALLOWED_SCRIPTS = {
        "_review.py",
        "guard.py",
        "chapter_review.py",
    }
    
    # 白名单：可传递的参数模式
    ALLOWED_ARGS_PATTERNS = [
        r"^第\d+[-_~]\d+章_.+\.md$",   # 第X章_标题.md
        r"^第\d+章_.+\.md$",             # 单章
        r"^_tmp_.+\.md$",                # 草稿
        r"^(filter|scan|clean)$",        # guard.py 子命令
    ]
    
    def run(self, script_path: str, args: list[str], cwd: str) -> dict:
        # 1. 验证脚本路径在白名单中
        # 2. 验证所有参数符合 ALLOWED_ARGS_PATTERNS
        # 3. 设置超时 30s
        # 4. 执行 subprocess.run(...)
        # 5. 解析 stdout/stderr
        # 6. 返回 {"stdout": ..., "stderr": ..., "returncode": ...}
```

---

## 4. API Key 管理方案

### 4.1 存储

```
data/keys.json
├── 加密方式: Fernet (对称加密，密钥派生自机器指纹+盐值)
├── 存储结构:
│   {
│     "deepseek": {"key": "<加密值>", "endpoint": "https://api.deepseek.com", "model": "deepseek-chat"},
│     "openai":   {"key": "<加密值>", "endpoint": "https://api.openai.com",    "model": "gpt-4o"},
│     "claude":   {"key": "<加密值>", "endpoint": "https://api.anthropic.com",  "model": "claude-sonnet-4-20250514"},
│   }
├── 初始化: 首次启动时如果 keys.json 不存在，从 .env 文件读取
│           如果 .env 也不存在，key 为空，前端显示"未配置"
│
└── 安全性: 本机运行 + 加密存储，密钥不离开本机
```

### 4.2 加解密

```python
# services/key_manager.py 核心逻辑（伪码）

from cryptography.fernet import Fernet
import hashlib, platform, uuid

class KeyManager:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self._fernet = Fernet(self._derive_key())
    
    def _derive_key(self) -> bytes:
        """基于机器特征生成密钥（非可移植，绑定本机）"""
        machine_id = [
            platform.node(),                    # 主机名
            str(uuid.getnode()),                # MAC 地址
            platform.machine(),                 # 架构
        ]
        seed = "|".join(machine_id).encode()
        return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    
    def save_key(self, provider: str, api_key: str, endpoint: str, model: str):
        data = self._load()
        data[provider] = {
            "key": self._fernet.encrypt(api_key.encode()).decode(),
            "endpoint": endpoint,
            "model": model,
        }
        self._save(data)
    
    def get_key(self, provider: str) -> str | None:
        data = self._load()
        if provider not in data:
            return None
        return self._fernet.decrypt(data[provider]["key"].encode()).decode()
    
    def get_config(self, provider: str) -> dict | None:
        """返回配置但不包含密钥原文"""
        data = self._load()
        if provider not in data:
            return None
        return {
            "configured": True,
            "endpoint": data[provider]["endpoint"],
            "model": data[provider]["model"],
            "key_preview": data[provider]["key"][:8] + "...",
        }
```

### 4.3 备选方案（不加密）

如果用户觉得加密增加了不必要的复杂度（本机应用），支持明文存储：

```yaml
# config.yaml 中的选项
key_storage:
  method: "plaintext"  # 可选: "encrypted" (默认) / "plaintext"
  # plaintext 模式下存储在 .env 文件或 config.yaml 自身
```

---

## 5. 聊天接口消息格式

### 5.1 请求格式

```
POST /api/v1/chat/completions
```

```json
{
  "model": "deepseek",
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 4096,
  "system_prompt": "你是《泰拉拾遗录》的专属写手。放下日常的对话风格，切换到作家模式。",
  "messages": [
    {
      "role": "user",
      "content": "帮我分析第40章写前需要确认的事项"
    }
  ],
  "context": {
    "active_chapter": "第40章_离开之前.md",
    "attached_knowledge": [
      "地理地图.md",
      "人物档案与关系网.md"
    ]
  }
}
```

### 5.2 流式响应格式 (stream: true)

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

```
data: {"type": "text", "content": "好的，先看"}
data: {"type": "text", "content": "写前分析需要确认的"}
data: {"type": "text", "content": "七项内容..."}
data: {"type": "thinking", "content": "正在检索地理地图.md..."}  // 当检索知识库时
data: {"type": "text", "content": "...\n\n"}
data: {"type": "done", "content": "", "usage": {"prompt_tokens": 1200, "completion_tokens": 350}}
```

### 5.3 非流式响应格式 (stream: false)

```json
{
  "role": "assistant",
  "content": "写前分析确认如下：\n\n1. **沈默的不适**——...",
  "usage": {
    "prompt_tokens": 1200,
    "completion_tokens": 350,
    "total_tokens": 1550
  },
  "model": "deepseek-chat"
}
```

### 5.4 会话历史格式

存储在 `data/chat_history.json` 中的格式：

```json
[
  {
    "id": "msg_001",
    "role": "user",
    "content": "帮我分析第40章写前需要确认的事项",
    "timestamp": "2026-05-20T20:00:00+08:00",
    "context": {
      "active_chapter": "第40章_离开之前.md",
      "attached_files": ["地理地图.md"]
    }
  },
  {
    "id": "msg_002",
    "role": "assistant",
    "content": "写前分析确认如下：...",
    "timestamp": "2026-05-20T20:00:10+08:00",
    "model": "deepseek-chat",
    "usage": {"prompt_tokens": 1200, "completion_tokens": 350}
  }
]
```

### 5.5 多模型统一调用层

```python
# services/llm_client.py 核心结构（伪码）

class LLMClient:
    
    PROVIDERS = {
        "deepseek": {
            "base_url": "https://api.deepseek.com",
            "models": ["deepseek-chat", "deepseek-reasoner"],
            "headers": lambda key: {"Authorization": f"Bearer {key}"},
            "chat_endpoint": "/v1/chat/completions",
        },
        "openai": {
            "base_url": "https://api.openai.com",
            "models": ["gpt-4o", "gpt-4o-mini"],
            "headers": lambda key: {"Authorization": f"Bearer {key}"},
            "chat_endpoint": "/v1/chat/completions",
        },
        "claude": {
            "base_url": "https://api.anthropic.com",
            "models": ["claude-sonnet-4-20250514", "claude-haiku-3-5"],
            "headers": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"},
            "chat_endpoint": "/v1/messages",
        },
    }
    
    def chat_stream(self, provider: str, messages: list, **params):
        """统一流式调用，将不同 provider 的响应格式归一化为 SSE"""
        config = self.PROVIDERS[provider]
        key = self.key_manager.get_key(provider)
        # ...
        # 对于 Claude，将 messages 转换为 Anthropic 格式
        # 对于 OpenAI/DeepSeek，保持 OpenAI 格式
        # 统一产出 SSE 流
    
    def chat(self, provider: str, messages: list, **params):
        """非流式调用"""
```

**Anthropic <-> OpenAI 格式转换：**

| OpenAI | Anthropic | 转换方式 |
|--------|-----------|----------|
| `system` 放在 messages 数组 | `system` 参数单独传 | 提取第一个 system message |
| `user` `assistant` | `user` `assistant` | 映射 content 和 role |
| 无 `thinking` 块 | 有 `thinking` 块 | 合并到 content 中或作为额外字段 |

---

## 6. 工作流状态追踪

### 6.1 状态模型

```python
# models/workflow_schemas.py

class WorkflowState(BaseModel):
    project: str = "tales-of-tera"
    current_stage: int = 0  # 0-8 对应 9 阶段
    current_stage_name: str = "未开始"
    
    # 当前正在处理的章节
    active_chapter: str | None = None
    
    # 各阶段完成状态
    stages: dict[int, StageStatus] = {
        1: {"name": "写前分析",       "completed": False, "completed_at": None},
        2: {"name": "写作",           "completed": False, "completed_at": None},
        3: {"name": "自检清单",       "completed": False, "completed_at": None,
            "checklist": {
                "时间线": False, "空间一致性": False, "情绪衔接": False,
                "字数检查": False, "句号密度": False, ...}},
        3.3: {"name": "自动审查",     "completed": False, "completed_at": None,
              "auto_checks": {}},
        3.5: {"name": "文笔润色",     "completed": False, "completed_at": None},
        4:  {"name": "修订",          "completed": False, "completed_at": None},
        5:  {"name": "章末元数据",    "completed": False, "completed_at": None},
        6:  {"name": "知识库同步",    "completed": False, "completed_at": None,
             "sync_items": {
                 "伏笔与线索追踪表": False,
                 "时间线表": False,
                 "人物档案与关系网": False,
                 "物品列表": False,
                 "情节脉络": False,
                 "全卷章节细纲": False,
             }},
    }
    
    created_at: str
    updated_at: str
```

### 6.2 阶段枚举

| 阶段序号 | 名称 | 说明 |
|----------|------|------|
| 0 | 未开始 | 初始状态 |
| 1 | 写前分析 | 7项确认 + 写作策略输出 |
| 2 | 写作 | 正文写作 |
| 3 | 自检清单 | 逐项确认，阻塞（未通过不可进入下一阶段） |
| 3.3 | 自动审查 | 运行 _review.py + 字数/密度/句式检查 |
| 3.4 | 外部评审 | 可选，派给 hanako/小黄/小黑 |
| 3.5 | 文笔润色 | 语言/韵律/氛围优化 |
| 4 | 修订 | 修复自检问题 |
| 5 | 章末元数据 | 输出结构化摘要 |
| 6 | 知识库同步 | 6个文件同步确认 |
| 7 | 交付 | 发出 docx |

### 6.3 状态持久化

```yaml
# data/workflow_state.json
{
  "project": "tales-of-tera",
  "active_chapter": "第40章_离开之前.md",
  "current_stage": 5,
  "current_stage_name": "章末元数据",
  "stages": { ... },
  "history": [
    {"stage": 2, "entered_at": "...", "exited_at": "...", "chapter": "第40章_离开之前.md"},
    {"stage": 3, "entered_at": "...", "exited_at": "...", "chapter": "第40章_离开之前.md"},
  ],
  "created_at": "2026-05-20T20:00:00+08:00",
  "updated_at": "2026-05-20T20:30:00+08:00"
}
```

---

## 7. 工具脚本执行接口

### 7.1 审查执行流程

```
POST /api/v1/tools/review
  │
  ├→ 1. 定位项目目录（从 config.yaml 读取 root）
  ├→ 2. 解析文件名，拼接完整路径
  ├→ 3. 路径安全校验（path traversal 防护）
  ├→ 4. 检查文件是否存在
  ├→ 5. subprocess.run(["python", "_review.py", "<file>"], cwd="<project_root>", capture_output=True, timeout=30)
  ├→ 6. 解析标准输出
  │   ├→ "OK" → {"status": "ok", "output": "..."}
  │   └→ "问题描述" → {"status": "issues_found", "output": "...", "issues": [...]}
  ├→ 7. 可选：同时运行其他自动化检查（字数统计、句号密度、句式分析）
  └→ 8. 返回结构化结果
```

### 7.2 guard.py 集成

```
POST /api/v1/tools/guard-scan
  body: {"chapter": "第40章_离开之前.md", "project": "tales-of-tera"}
  → 运行 guard.py scan <文件>
  → 返回命中列表或"通过"

POST /api/v1/tools/guard-filter
  body: {"directory": "chapters", "pattern": "第*章_*.md", "project": "tales-of-tera"}
  → 运行 guard.py filter <目录> <pattern>
  → 返回过滤后的文件列表
```

### 7.3 脚本执行安全约束

```python
class ScriptRunner:
    TIMEOUT = 30          # 单次运行上限 30 秒
    MAX_OUTPUT = 65536    # 输出截断 64KB
    
    BLOCKED_MODULES = [   # 禁止脚本导入的模块（防范恶意脚本）
        "os", "subprocess", "shutil", "socket",
        "ctypes", "winreg", "requests",
    ]
```

考虑使用 `runpy` 或 `exec` + 沙箱而非 subprocess（可选方案）：

| 方案 | 优点 | 缺点 |
|------|------|------|
| `subprocess.run` | 隔离性好，不污染主进程 | 额外进程开销，输出解析成本 |
| `runpy.run_path` + 沙箱 | 同一进程，速度快 | 沙箱不完美，恶意脚本可影响主进程 |

**推荐**：对于 `_review.py` 这种纯检查脚本，使用 `subprocess`。未来如果性能瓶颈，再迁移到 `runpy` + `RestrictedPython`。

---

## 8. 错误处理规范

### 8.1 统一错误响应格式

```json
{
  "error": {
    "code": "FILE_NOT_FOUND",
    "message": "章节文件不存在",
    "detail": "第999章_不存在的章节.md 在 chapters/ 目录下未找到",
    "suggestion": "请确认文件名正确，或者先通过 GET /api/v1/chapters 查看可用文件列表"
  }
}
```

### 8.2 错误码表

| HTTP 状态码 | error.code | 场景 |
|-------------|------------|------|
| 400 | `INVALID_PARAMETER` | 请求参数格式错误 |
| 400 | `FILE_TYPE_ERROR` | 不支持的文件扩展名 |
| 404 | `FILE_NOT_FOUND` | 请求的文件不存在 |
| 404 | `ROUTE_NOT_FOUND` | API 路径不存在 |
| 413 | `FILE_TOO_LARGE` | 文件超过大小限制 |
| 422 | `VALIDATION_ERROR` | Pydantic 校验失败 |
| 423 | `PATH_TRAVERSAL` | 路径穿越检测拦截 |
| 424 | `SCRIPT_TIMEOUT` | 脚本执行超时 |
| 424 | `SCRIPT_ERROR` | 脚本执行报错 |
| 502 | `PROVIDER_ERROR` | AI 服务商 API 返回错误 |
| 502 | `PROVIDER_TIMEOUT` | AI 服务商请求超时 |
| 503 | `KEY_NOT_CONFIGURED` | API Key 未配置 |

### 8.3 日志规范

```
writing-app/logs/
├── app.log         # 应用日志（INFO 级别）
├── access.log      # HTTP 请求日志
├── error.log       # 错误日志（ERROR 级别）
└── chat.log        # 聊天对话记录（可选，用户控制）
```

日志输出使用 Python 标准 `logging`，按天轮转。不记录 API Key 原文。

---

## 附录 A：依赖清单

```
# requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
cryptography>=42.0.0
pyyaml>=6.0
python-multipart>=0.0.9
pydantic>=2.0.0
sse-starlette>=2.0.0
```

## 附录 B：启动脚本

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务（开发模式）
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# 启动服务（生产模式）
uvicorn main:app --host 127.0.0.1 --port 8000 --log-config logging.conf
```

前端页面访问：`http://127.0.0.1:8000`

---

## 附录 C：后续可扩展

| 功能 | 说明 |
|------|------|
| Git 集成 | 章节文件自动版本控制，diff 查看，回滚 |
| 多项目支持 | 通过 config.yaml 切换不同的写作项目 |
| 自定义审查规则 | 用户可通过界面添加新的审查规则 |
| 写作统计 | 字数趋势、写作速度、阶段耗时分析 |
| 多会话 | 每个章节可关联独立的聊天会话 |
| 知识库全文搜索 | 在 18 个知识库文件中全文检索 |
| 一键交付流水线 | 合并 → guard scan → pdf/docx → 发送邮箱 |
