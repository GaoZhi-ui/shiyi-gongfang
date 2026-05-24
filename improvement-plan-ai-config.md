# 写作助手工坊 · AI 配置与管理改进计划

> 基于对 Open WebUI、Continue.dev、LM Studio、AnythingLLM、Cursor、Obsidian Copilot 等 9 类产品的调研，
> 以及 Reddit r/LocalLLaMA、GitHub Issues 上的真实用户反馈。

---

## 一、当前问题诊断

| # | 问题 | 严重度 | 来源 |
|:-:|:-----|:------:|:----:|
| 1 | 8 个 provider 各自独立配置，表单重复度高 | 🔴 | Hanako |
| 2 | 模型列表硬编码，用户不知道实际可用模型 | 🔴 | Hanako / 小黑 |
| 3 | 连接测试和配置保存的 UI 反馈不够清晰 | 🔴 | 小黑（用户反馈最高频投诉） |
| 4 | API Key 明文存储在配置文件，无加密 | 🟡 | 小黄 |
| 5 | 前端默认端口 8867，服务器跑在 8000 | 🟡 | 子代理测试发现 |
| 6 | 模型下拉展示原始模型名，非场景化标签 | 🟡 | 小黑（ChatGPT 下拉分析） |
| 7 | 设置页是模态弹窗，不适合展示大量配置项 | 🟢 | 小黑 |
| 8 | 无代理/自定义 endpoint 支持 | 🟢 | 小黄 |

---

## 二、改进方案

### P0 — 必须做（影响核心体验）

#### 1. 按协议族合并 Provider 配置

**现状**：8 个 provider 各自独立，表单几乎一样（endpoint + API Key + model）。

**目标**：按协议类型分组，同一协议共享一套配置模板。

| 协议族 | 包含 Provider |
|:-------|:--------------|
| OpenAI 兼容 | DeepSeek、OpenAI、Kimi、GLM、Yi |
| Anthropic | Claude（请求格式不同） |
| Google | Gemini（API 结构不同） |
| Ollama | Ollama（本地、自动发现、无 Key） |

**UI 设计**（参考 Open WebUI / AnythingLLM）：
```
┌─ 配置 AI 模型 ──────────────────────────┐
│                                          │
│  ┌─────────────────────────────────────┐ │
│  │ ● OpenAI 兼容   ▼ deepseek         │ │ ← 协议族 + Provider 下拉
│  │   Endpoint:  https://api.deepseek... │ │
│  │   API Key:   ●●●●●●●●●●  [👁]     │ │
│  │   可用模型:  ┌─ deepseek-v4-flash ─┐│ │ ← 动态获取，非硬编码
│  │              │ deepseek-v4-pro    ││ │
│  │              │ deepseek-chat      ││ │
│  │              └─────────────────────┘│ │
│  │   [测试连接]  ✅ 连接成功           │ │ ← 三态：未测/成功/失败
│  └─────────────────────────────────────┘ │
│                                          │
│  ┌─────────────────────────────────────┐ │
│  │ ○ Ollama  [本地]                    │ │ ← 本地标签 + 自动探测
│  │   Endpoint:  http://localhost:11434  │ │
│  │   可用模型:  ┌─ llama3.2:latest ───┐│ │
│  │              │ qwen2.5:7b         ││ │
│  │              └─────────────────────┘│ │
│  │   [测试连接]  ✅ Ollama 运行中      │ │
│  └─────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

**改动量**：中小。前端重构设置弹窗，后端已有 `/keys/{provider}/models` 接口可用。

---

#### 2. 连接测试三态 UI + 精准错误消息

**现状**：测试连接只显示"OK"或"无法连接"，不区分错误类型。

**目标**：按钮状态机：`idle` → `testing`（spinner+禁用） → `success`（绿色）/ `error`（红色具体消息）。

**错误消息分级**（参考小黄调研）：
| 状态码 | 用户可见消息 |
|:------:|:------------|
| 401 | API Key 无效，请检查是否正确 |
| 429 | 请求过频，请稍后重试 |
| 超时 | 连接超时，请检查 endpoint 地址 |
| DNS 失败 | 无法解析地址，请检查 URL |
| 连接拒绝 | 端口无响应，请确认服务是否运行 |
| Ollama 连接拒绝 | Ollama 未运行，请执行 `ollama serve` |

**改动量**：小。修改后端 `/keys/{provider}/test` 的错误消息，前端显示状态机。

---

#### 3. 动态模型列表获取 + 失败提示

**现状**：模型纯硬编码，用户不知道真实可用模型。

**目标**：连接测试成功后自动调用 `/keys/{provider}/models` 获取模型列表并填充下拉。

**三态处理**：
- **loading**：显示 spinner + "正在获取可用模型…"
- **success**：替换下拉选项
- **error**：保留硬编码列表作为 fallback，显示黄色提示"无法获取模型列表，已使用默认列表"

**改动量**：中。后端接口已实现，前端需要整合到连接测试流程中。

---

### P1 — 建议做（体验优化）

#### 4. API Key 安全存储升级

**现状**：Key 加密存在 `data/keys.json`，但密钥在内存中可能泄露。

**改进**：
- 使用 `keyring` 库对接系统密钥链（Windows Credential Manager / macOS Keychain）
- 日志中过滤 `api_key` / `Authorization` 字段
- 异常消息截断，不向用户透传 SDK 原始错误

**改动量**：中。`services/key_manager.py` 替换存储后端。

**升级路径**：当前自加密 JSON 方案没问题，按优先级排到后面。

---

#### 5. 设置页面从模态框升级为独立页面

**现状**：设置塞在模态弹窗里，内容一旦增多就放不下。

**目标**：将设置改为独立页面（侧边栏或新标签页），支持分组、搜索、键盘导航。

**参考**：Cursor 的设置页设计——左侧导航列表，右侧详情面板。

**改动量**：大。涉及前端路由和页面布局重构。可以考虑逐步推进：
1. 先在模态框内加 tab 分组
2. 再升级为独立页面

---

#### 6. 模型选择器场景化标签

**现状**：下拉显示原始模型名（如 `deepseek-v4-flash`）。

**目标**：提供场景预设标签切换：
| 标签 | 模型 | 温度 |
|:-----|:-----|:----:|
| 🚀 快速草稿 | deepseek-v4-flash | 0.7 |
| ✍️ 精细润色 | deepseek-v4-pro | 0.3 |
| 📖 续写生成 | deepseek-chat | 0.8 |

用户可在设置中自定义每个标签对应的模型和参数。

**改动量**：中。前端下拉改为分组标签，后端需返回默认配置。

---

### P2 — 考虑做（锦上添花）

#### 7. Provider 自动探测

- Ollama 自动检测 `localhost:11434` 是否可达
- 首次启动时如果有 Ollama，自动配置并提示用户选择模型
- LM Studio / text-gen-webui 等兼容端点的自动发现

**参考**：Open WebUI 的自动发现机制。

#### 8. 场景预设（Presets）

用户可保存多组 AI 配置预设：
- "写作助手"：system prompt + temperature=0.7 + 长上下文
- "润色审稿"：system prompt + temperature=0.3 + 短上下文

切换预设同时切换 provider + model + 参数。

#### 9. 请求代理支持

- 支持 HTTP/HTTPS/SOCKS5 代理
- 读取系统代理环境变量 `HTTP_PROXY` / `HTTPS_PROXY`
- 设置页可选"使用系统代理"或"自定义代理"

---

## 三、实施优先级

| 阶段 | 内容 | 预估工时 |
|:----:|:-----|:--------:|
| 1 | 协议族合并 + 动态模型获取（P0 #1+#3） | 4-6h |
| 2 | 连接测试三态 UI + 精准错误（P0 #2） | 2-3h |
| 3 | API Key 安全存储升级（P1 #4） | 2-3h |
| 4 | 设置页升级为独立页面（P1 #5） | 6-8h |
| 5 | 场景化模型标签（P1 #6） | 3-4h |
| 6 | Provider 自动探测 + 预设 + 代理（P2） | 8-12h |

---

## 四、参考来源

- [Open WebUI provider 配置设计](https://github.com/open-webui/open-webui)
- [Continue.dev Provider 抽象层](https://docs.continue.dev/customize/providers)
- [AnythingLLM 多 Provider 管理](https://github.com/Mintplex-Labs/anything-llm)
- [LM Studio 模型管理](https://lmstudio.ai/docs)
- [Cursor 设置页设计](https://cursor.sh)
- [Obsidian Copilot 插件](https://github.com/logancyang/obsidian-copilot)
- [Reddit r/LocalLLaMA 用户反馈](https://reddit.com/r/LocalLLaMA)
- [FastAPI 官方 Background Tasks 文档](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Python keyring 库](https://github.com/jaraco/keyring)
