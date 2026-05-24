"""
AI 聊天路由 — 流式 SSE / 非流式响应、会话历史管理

POST   /chat/completions        — 发送消息，获取流式或完整响应
GET    /chat/history            — 获取当前会话历史
DELETE /chat/history            — 清空当前会话历史
POST   /chat/history/export     — 导出聊天记录为 Markdown

路径前缀 /api/v1/chat

POST   /chat/stuck             — 卡住时获取续写建议

SSE 流式格式：
  data: {"type": "text", "content": "..."}
  data: {"type": "thinking", "content": "..."}
  data: {"type": "done", "content": "", "usage": {"prompt_tokens": N, "completion_tokens": N}}

v2 新增：
- 代理支持：读取 HTTPS_PROXY 等环境变量，自动传给 httpx client
- 预设支持：ChatRequest.preset 字段，优先于 scene 但低于显式参数
"""

import json
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import AsyncGenerator
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
import httpx

from core.vector_store import get_vector_store


# ─── 代理配置读取 ───


def get_proxy_settings() -> dict:
    """
    读取代理配置。
    优先级：HTTPS_PROXY > https_proxy > HTTP_PROXY > http_proxy
    返回 httpx 兼容的 proxies 字典，无代理时返回空 dict。
    """
    import os
    for var in ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"]:
        val = os.environ.get(var)
        if val:
            return {"http://": val, "https://": val}
    return {}


router = APIRouter(prefix="/chat", tags=["chat"])
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "chat_history.json"

# ─── 服务层导入（延迟加载，services 不存在时优雅降级） ───

_key_manager_instance = None


def _get_key_manager():
    global _key_manager_instance
    if _key_manager_instance is not None:
        return _key_manager_instance
    try:
        from services.key_manager import KeyManager
        _key_manager_instance = KeyManager(storage_path=DATA_DIR / "keys.json")
        return _key_manager_instance
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SERVICE_UNAVAILABLE",
                "message": "key_manager 服务未实现",
                "suggestion": "请先实现 services/key_manager.py",
            },
        )

# ─── 知识库读取辅助（用于 attach 知识库文件到上下文） ───

KNOWLEDGE_BASE = None  # 延迟初始化


def _ensure_knowledge_base():
    """获取知识库根目录"""
    global KNOWLEDGE_BASE
    if KNOWLEDGE_BASE is not None:
        return KNOWLEDGE_BASE
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            for info in cfg.get("knowledge_base", {}).values():
                root = info.get("root")
                if root:
                    p = Path(root).expanduser().resolve()
                    if p.is_dir():
                        KNOWLEDGE_BASE = p
                        return KNOWLEDGE_BASE
        except Exception:
            pass  # knowledge dir not found
    candidates = [
        BASE / "knowledge",
        Path("knowledge"),
    ]
    for d in candidates:
        if d.is_dir():
            KNOWLEDGE_BASE = d
            return KNOWLEDGE_BASE
    KNOWLEDGE_BASE = BASE / "knowledge"
    return KNOWLEDGE_BASE


def _read_knowledge_file(filename: str) -> str | None:
    """读取知识库文件内容，供注入上下文"""
    kb = _ensure_knowledge_base()
    if not kb.is_dir():
        return None
    target = (kb / filename).resolve()
    if not str(target).startswith(str(kb.resolve())):
        return None
    if not target.exists() or not target.is_file():
        return None
    if target.suffix.lower() not in {".md", ".txt"}:
        return None
    if target.stat().st_size > 1024 * 1024:
        return None
    return target.read_text(encoding="utf-8", errors="replace")


# ─── Pydantic 模型 ───


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class ChatContext(BaseModel):
    active_chapter: str | None = None
    attached_knowledge: list[str] | None = None
    project_id: str | None = None


class ChatRequest(BaseModel):
    model: str = Field("deepseek", description="模型标识: deepseek / openai / claude / google / moonshot / zhipu / yi")
    mode: str = Field("chat", description="对话模式: chat / continue / expand / rewrite", pattern="^(chat|continue|expand|rewrite)$")
    scene: str = Field("draft", description="场景标签: draft / polish / continue", pattern="^(draft|polish|continue)$")
    stream: bool = Field(True, description="是否流式响应")
    temperature: float | None = Field(None, ge=0.0, le=2.0, description="温度参数，如不传则根据 scene 自动选择")
    max_tokens: int = Field(4096, ge=1, le=32768)
    system_prompt: str | None = Field(
        None,
        description="系统提示词，如不传则根据 scene 自动选择",
    )
    preset: str | None = Field(None, description="预设名称（优先级高于 scene，低于显式传入的 temperature/system_prompt）")
    messages: list[ChatMessage] = Field(..., min_length=1)
    context: ChatContext | None = None


class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    role: str = "assistant"
    content: str
    usage: UsageInfo | None = None
    model: str | None = None


class HistoryMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    context: dict | None = None
    model: str | None = None
    usage: UsageInfo | None = None


class ExportResponse(BaseModel):
    status: str
    content: str
    filename: str


# ─── 历史管理 ───


def _load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_history(history: list):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_to_history(entry: dict):
    history = _load_history()
    history.append(entry)
    # 保留最近 200 条消息
    if len(history) > 200:
        history = history[-200:]
    _save_history(history)


# ─── Provider 配置（协议族分组） ───

PROVIDER_FAMILIES = {
    "openai_compatible": {
        "label": "OpenAI 兼容",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
        "providers": {
            "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "default_model": "deepseek-v4-flash"},
            "openai": {"name": "OpenAI", "base_url": "https://api.openai.com", "default_model": "gpt-5.4"},
            "moonshot": {"name": "Kimi", "base_url": "https://api.moonshot.cn", "default_model": "kimi-k2.6"},
            "zhipu": {"name": "GLM", "base_url": "https://open.bigmodel.cn", "default_model": "glm-5.1", "chat_endpoint": "/api/paas/v4/chat/completions"},
            "yi": {"name": "Yi", "base_url": "https://api.lingyiwanwu.com", "default_model": "yi-lightning"},
        },
    },
    "anthropic": {
        "label": "Anthropic",
        "chat_endpoint": "/v1/messages",
        "auth_header": lambda key: {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        "content_type": "application/json",
        "providers": {
            "claude": {"name": "Claude", "base_url": "https://api.anthropic.com", "default_model": "claude-sonnet-4-20250514"},
        },
    },
    "google": {
        "label": "Google",
        "chat_endpoint": "/v1beta/openai/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
        "providers": {
            "google": {"name": "Gemini", "base_url": "https://generativelanguage.googleapis.com", "default_model": "gemini-2.5-pro"},
        },
    },
    "ollama": {
        "label": "Ollama (本地)",
        "chat_endpoint": "/api/chat",
        "auth_header": lambda key: {},
        "content_type": "application/json",
        "providers": {
            "ollama": {"name": "Ollama", "base_url": "http://localhost:11434", "default_model": "llama3.2", "local": True},
        },
    },
}

# 从 PROVIDER_FAMILIES 生成 flat PROVIDER_CONFIGS（向后兼容）
PROVIDER_CONFIGS = {}
for family_id, family in PROVIDER_FAMILIES.items():
    for pid, info in family["providers"].items():
        PROVIDER_CONFIGS[pid] = {
            "base_url": info["base_url"],
            "default_model": info["default_model"],
            "chat_endpoint": info.get("chat_endpoint", family.get("chat_endpoint", "/v1/chat/completions")),
            "auth_header": family["auth_header"],
            "content_type": family["content_type"],
            "family": family_id,
            "family_label": family["label"],
            "local": info.get("local", False),
        }




DEFAULT_SYSTEM = "你是专业的写作助手。回答简洁、直接、不啰嗦。"

SCENE_PRESETS = {
    "draft": {
        "temperature": 0.7,
        "system": "你是一个写作助手，专注于头脑风暴、大纲生成和快速创作。回答直接、灵感导向，鼓励发散思维。",
    },
    "polish": {
        "temperature": 0.3,
        "system": "你是一个文字润色专家，专注于文笔优化、句式调整和语言精炼。保持原意，注重修辞和流畅度。",
    },
    "continue": {
        "temperature": 0.8,
        "system": "你是一个小说续写者，擅长故事续写、场景扩展和情节推进。保持文风一致，不破坏叙事节奏。",
    },
}


MODE_SYSTEM_PROMPTS = {
    "chat": DEFAULT_SYSTEM,
    "continue": (
        "你正在续写一段小说。\n\n"
        "规则：\n"
        "1. 保持已有的文风、视角和叙事节奏\n"
        "2. 不重复上一段已经说过的内容\n"
        "3. 不点评、不概括、不以「以下为续写」开头\n"
        "4. 直接从上一段末尾的语境自然延续\n"
        "5. 不添加任何 meta 性质的说明"
    ),
    "expand": (
        "你正在根据一段简短的描述展开成详细生动的段落。\n\n"
        "规则：\n"
        "1. 保持文风一致\n"
        "2. 增加细节描写（场景、动作、心理、感官）\n"
        "3. 不改变原始描述的情节走向和关键信息\n"
        "4. 展开后的内容需要自然流畅，有画面感"
    ),
    "rewrite": (
        "你正在按要求重写一段文本。\n\n"
        "规则：\n"
        "1. 保留原文的关键信息和情节\n"
        "2. 根据用户的具体要求调整风格、视角或表述方式\n"
        "3. 重写结果需完整流畅，不自相矛盾\n"
        "4. 如果用户未指定改写方向，默认优化语言表达"
    ),
}


# ─── 核心逻辑 ───


def _load_writing_guide(project_id: str) -> str | None:
    from pathlib import Path
    proj_dir = (BASE / "projects" / project_id).resolve()
    if not str(proj_dir).startswith(str((BASE / "projects").resolve())):
        return None
    """读取项目的 writing-guide.json，返回格式化的描述文本"""
    guide_dir = BASE / "projects" / project_id
    guide_file = guide_dir / "writing-guide.json"
    if not guide_file.exists():
        return None
    try:
        data = json.loads(guide_file.read_text(encoding="utf-8"))
        parts = []
        if data.get("description"):
            parts.append(f"写作规范：{data['description']}")
        forbidden = data.get("forbidden_words", [])
        if forbidden:
            parts.append(f"禁用词：{', '.join(forbidden)}")
        names = data.get("character_names", [])
        if names:
            parts.append(f"角色名：{', '.join(names)}")
        places = data.get("place_names", [])
        if places:
            parts.append(f"地名：{', '.join(places)}")
        style = data.get("style", "")
        tone = data.get("tone", "")
        if style or tone:
            extras = []
            if style:
                extras.append(f"风格：{style}")
            if tone:
                extras.append(f"语调：{tone}")
            parts.insert(0, "；".join(extras))
        return "。".join(parts) if parts else None
    except (json.JSONDecodeError, OSError):
        return None


def _resolve_scene_temperature(req: ChatRequest) -> tuple[float, str]:
    """根据场景标签解析 temperature 和 system prompt，向后兼容"""
    scene_key = req.scene or "draft"
    preset = SCENE_PRESETS.get(scene_key, SCENE_PRESETS["draft"])
    temperature = req.temperature if req.temperature is not None else preset["temperature"]
    system_prompt = req.system_prompt if req.system_prompt is not None else preset["system"]
    return temperature, system_prompt


def _build_payload(provider: str, req: ChatRequest) -> dict:
    """构建请求体（OpenAI 兼容格式）"""
    provider_lower = provider.lower()
    cfg = PROVIDER_CONFIGS.get(provider_lower, PROVIDER_CONFIGS["deepseek"])
    model_name = cfg["default_model"]

    # 根据场景标签解析 temperature 和 system prompt
    temperature, system_prompt = _resolve_scene_temperature(req)

    # 预设覆盖：预设优先级高于 scene，但低于显式传入的 temperature/system_prompt
    if req.preset:
        try:
            from services.key_manager import get_preset_by_name
            preset_cfg = get_preset_by_name(req.preset)
            if preset_cfg:
                if req.temperature is None:
                    temperature = preset_cfg["temperature"]
                if req.system_prompt is None:
                    system_prompt = preset_cfg["system_prompt"]
        except Exception:
            pass

    # 构建 messages
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # 注入附加上下文
    context_notes = []
    if req.context:
        if req.context.active_chapter:
            context_notes.append(f"当前正在进行章节：{req.context.active_chapter}")
        if req.context.attached_knowledge:
            for kf in req.context.attached_knowledge:
                content = _read_knowledge_file(kf)
                if content:
                    # 取前 3000 字作为上下文
                    truncated = content[:3000]
                    context_notes.append(f"\n--- 参考知识库: {kf} ---\n{truncated}\n--- 参考结束 ---")

    if context_notes:
        messages.append({"role": "system", "content": "\n".join(context_notes)})

    # 注入向量检索上下文（RAG）
    if req.context and req.context.project_id and req.messages:
        try:
            last_user_msg = ""
            for m in reversed(req.messages):
                if m.role == "user":
                    last_user_msg = m.content
                    break
            if last_user_msg:
                vs = get_vector_store()
                results = vs.search(query=last_user_msg, project_id=req.context.project_id, top_k=5)
                if results:
                    rag_parts = ["相关章节内容："]
                    for r in results:
                        source = r.get("filename", r.get("title", "未知"))
                        rag_parts.append(f"[{source}] {r['content'][:400]}\n")
                    rag_text = "\n".join(rag_parts)
                    messages.append({"role": "system", "content": rag_text})
        except Exception as e:
            logger = __import__("logging").getLogger("chat")
            logger.warning(f"向量检索失败: {e}")

    # 注入 writing-guide（如果 project_id 存在）
    if req.context and req.context.project_id:
        guide_text = _load_writing_guide(req.context.project_id)
        if guide_text:
            messages.append({"role": "system", "content": guide_text})

    # 添加用户消息
    for msg in req.messages:
        messages.append({"role": msg.role, "content": msg.content})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": req.max_tokens,
        "stream": req.stream,
    }
    return payload, cfg


def _get_api_info(provider: str) -> tuple[str, dict]:
    """获取 API Key 和 provider 配置"""
    provider_lower = provider.lower()
    config = PROVIDER_CONFIGS.get(provider_lower)
    if not config:
        raise HTTPException(400, detail={
            "code": "INVALID_PARAMETER",
            "message": f"不支持的 provider: {provider}",
            "suggestion": f"可用: {list(PROVIDER_CONFIGS.keys())}",
        })

    # 本地 provider（如 ollama）不需要 API Key
    if config.get("local"):
        api_key = ""
    else:
        km = _get_key_manager()
        api_key = km.get_key(provider_lower)
        if not api_key:
            raise HTTPException(503, detail={
                "code": "KEY_NOT_CONFIGURED",
                "message": f"{provider} 的 API Key 未配置",
                "suggestion": "请先通过 POST /api/v1/keys 配置 API Key",
            })

    stored_cfg = km.get_config(provider_lower)
    base_url = None
    model = None
    if stored_cfg:
        base_url = stored_cfg.get("endpoint") or config["base_url"]
        model = stored_cfg.get("model") or config["default_model"]
    else:
        base_url = config["base_url"]
        model = config["default_model"]

    return api_key, {
        **config,
        "base_url": base_url,
        "default_model": model,
    }


async def _stream_openai_compat(client: httpx.AsyncClient, url: str, payload: dict, headers: dict) -> AsyncGenerator[str, None]:
    """处理 OpenAI 兼容的流式响应（DeepSeek / OpenAI）"""
    async with client.stream("POST", url, json=payload, headers=headers, timeout=120) as resp:
        if resp.status_code != 200:
            error_body = await resp.aread()
            yield json.dumps({
                "type": "error",
                "content": f"API 返回 {resp.status_code}: {error_body.decode('utf-8', errors='replace')[:500]}",
            }, ensure_ascii=False)
            return

        usage_info = None
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            if data_str == "[DONE]":
                continue
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # 提取增量内容
            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield json.dumps({"type": "text", "content": content}, ensure_ascii=False)

            # 提取 usage（仅在最后一个 chunk 中有）
            if "usage" in chunk:
                usage_info = chunk["usage"]
            elif choices[0].get("finish_reason") == "stop":
                pass  # 等待 usage

        # 否则从第一块中取
        if usage_info:
            yield json.dumps({"type": "done", "content": "", "usage": usage_info}, ensure_ascii=False)
        else:
            yield json.dumps({"type": "done", "content": ""}, ensure_ascii=False)


async def _stream_anthropic(client: httpx.AsyncClient, url: str, payload: dict, headers: dict) -> AsyncGenerator[str, None]:
    """处理 Anthropic Claude 的流式响应（格式不同）"""
    async with client.stream("POST", url, json=payload, headers=headers, timeout=120) as resp:
        if resp.status_code != 200:
            error_body = await resp.aread()
            yield json.dumps({
                "type": "error",
                "content": f"Anthropic API 返回 {resp.status_code}: {error_body.decode('utf-8', errors='replace')[:500]}",
            }, ensure_ascii=False)
            return

        usage_info = {}
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield json.dumps({"type": "text", "content": text}, ensure_ascii=False)
            elif event_type == "message_delta":
                usage = event.get("usage", {})
                usage_info = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                }
            elif event_type == "message_stop":
                pass

        if usage_info:
            usage_info["total_tokens"] = usage_info.get("prompt_tokens", 0) + usage_info.get("completion_tokens", 0)
            yield json.dumps({"type": "done", "content": "", "usage": usage_info}, ensure_ascii=False)
        else:
            yield json.dumps({"type": "done", "content": ""}, ensure_ascii=False)


async def _non_stream_chat(payload: dict, cfg: dict, headers: dict, proxies: dict | None = None) -> dict:
    """非流式请求"""
    url = cfg["base_url"].rstrip("/") + cfg["chat_endpoint"]
    client_kwargs = {"timeout": 120}
    if proxies:
        client_kwargs["proxies"] = proxies
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(502, detail={
                "code": "PROVIDER_ERROR",
                "message": f"API 返回 {resp.status_code}",
                "detail": resp.text[:500],
            })
        data = resp.json()

    if cfg["auth_header"]("test").get("x-api-key"):  # Anthropic 格式
        content = data.get("content", [{}])[0].get("text", "")
        usage = data.get("usage", {})
        usage_info = UsageInfo(
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        )
    else:  # OpenAI 格式
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        usage_info = UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )

    return {"content": content, "usage": usage_info.model_dump() if usage_info else None}


# ─── 路由 ───


@router.post("/completions")
async def chat_completions(req: ChatRequest):
    """发送消息，获取流式 SSE 或完整 JSON 响应"""
    provider = req.model.lower()

    # 根据 mode 切换 system prompt
    if req.mode != "chat":
        mode_prompt = MODE_SYSTEM_PROMPTS.get(req.mode, DEFAULT_SYSTEM)
        current_system = req.system_prompt or ""
        if current_system and current_system != SCENE_PRESETS.get(req.scene or "draft", {}).get("system", ""):
            req.system_prompt = f"{mode_prompt}\n\n{current_system}"
        else:
            req.system_prompt = mode_prompt

    proxies = get_proxy_settings()
    api_key, provider_cfg = _get_api_info(provider)
    payload, cfg = _build_payload(provider, req)

    # 记录用户消息到历史
    user_msg = {
        "id": f"msg_{uuid.uuid4().hex[:8]}",
        "role": "user",
        "content": req.messages[-1].content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": req.context.model_dump() if req.context else None,
    }
    _append_to_history(user_msg)

    # 构建请求头
    headers = provider_cfg["auth_header"](api_key)
    headers["Content-Type"] = provider_cfg["content_type"]

    # 对于 Claude，转换 payload 格式
    is_anthropic = "x-api-key" in headers
    if is_anthropic:
        # 从 messages 中提取 system prompt
        system_text = None
        claude_messages = []
        for m in payload["messages"]:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                claude_messages.append({"role": m["role"], "content": m["content"]})
        claude_payload = {
            "model": payload["model"],
            "max_tokens": payload["max_tokens"],
            "messages": claude_messages,
            "stream": payload["stream"],
        }
        if system_text:
            claude_payload["system"] = system_text
        if "temperature" in payload:
            claude_payload["temperature"] = payload["temperature"]
        api_payload = claude_payload
    else:
        api_payload = payload

    url = provider_cfg["base_url"].rstrip("/") + provider_cfg["chat_endpoint"]

    if not req.stream:
        # 非流式
        result = await _non_stream_chat(api_payload, provider_cfg, headers, proxies=proxies)

        # 记录响应到历史
        assistant_msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "content": result["content"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": provider_cfg["default_model"],
            "usage": result["usage"],
        }
        _append_to_history(assistant_msg)

        return ChatResponse(
            role="assistant",
            content=result["content"],
            usage=UsageInfo(**result["usage"]) if result["usage"] else None,
            model=provider_cfg["default_model"],
        )

    # 流式
    async def event_generator():
        assistant_content = ""
        usage_info = None

        try:
            client_kwargs = {"timeout": 120}
            if proxies:
                client_kwargs["proxies"] = proxies
            async with httpx.AsyncClient(**client_kwargs) as client:
                if is_anthropic:
                    stream_gen = _stream_anthropic(client, url, api_payload, headers)
                else:
                    stream_gen = _stream_openai_compat(client, url, api_payload, headers)

                async for event_data in stream_gen:
                    event_obj = json.loads(event_data)
                    if event_obj["type"] == "text":
                        assistant_content += event_obj["content"]
                    elif event_obj["type"] == "done":
                        usage_info = event_obj.get("usage")
                    yield {"event": "message", "data": event_data}

        except httpx.TimeoutException:
            yield {"event": "message", "data": json.dumps({"type": "error", "content": "请求超时（120秒）"})}
            return
        except httpx.ConnectError:
            yield {"event": "message", "data": json.dumps({"type": "error", "content": "无法连接到 API 服务"})}
            return
        except Exception as e:
            yield {"event": "message", "data": json.dumps({"type": "error", "content": f"流式异常: {type(e).__name__}: {e}"})}
            return

        # 流结束后，保存助手消息到历史
        if assistant_content:
            assistant_msg = {
                "id": f"msg_{uuid.uuid4().hex[:8]}",
                "role": "assistant",
                "content": assistant_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": provider_cfg["default_model"],
                "usage": usage_info,
            }
            _append_to_history(assistant_msg)

    return EventSourceResponse(event_generator())


@router.get("/history")
def get_history():
    """获取当前会话历史"""
    history = _load_history()
    return {"history": history, "count": len(history)}


@router.delete("/history")
def clear_history():
    """清空当前会话历史"""
    _save_history([])
    return {"status": "ok", "message": "会话历史已清空"}


@router.post("/history/export")
def export_history():
    """导出聊天记录为 Markdown 文件"""
    history = _load_history()
    if not history:
        raise HTTPException(404, detail={
            "code": "NO_HISTORY",
            "message": "没有聊天记录可导出",
        })

    lines = ["# 写作助手工坊 · 聊天记录导出", "", f"导出时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for msg in history:
        role_label = "🧑 你" if msg["role"] == "user" else "🤖 助手"
        timestamp = msg.get("timestamp", "")
        lines.append(f"### {role_label} ({timestamp})")
        lines.append("")
        lines.append(msg["content"])
        lines.append("")
        if msg.get("model"):
            lines.append(f"> 模型：{msg['model']}")
        if msg.get("usage"):
            u = msg["usage"]
            lines.append(f"> Tokens: {u.get('prompt_tokens', 0)} in / {u.get('completion_tokens', 0)} out")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"chat_export_{ts}.md"

    export_path = DATA_DIR / filename
    export_path.write_text(content, encoding="utf-8")

    return ExportResponse(status="ok", content=content, filename=filename)


# ─── 卡住了路由 ───


class StuckRequest(BaseModel):
    project_id: str | None = None
    chapter_content: str = Field(..., description="当前章节文本")
    characters: list[str] = Field(default_factory=list, description="活跃角色列表")
    foreshadowing: list[str] = Field(default_factory=list, description="待回收伏笔列表")


class StuckSuggestion(BaseModel):
    title: str
    summary: str


class StuckResponse(BaseModel):
    suggestions: list[StuckSuggestion]


@router.post("/stuck")
async def stuck_suggestions(req: StuckRequest):
    """用户卡住时，根据当前章节内容、活跃角色和伏笔，给出续写建议"""
    provider = "deepseek"  # 默认模型
    api_key, provider_cfg = _get_api_info(provider)

    # 构建提示词
    prompt_parts = ["你是写作助手。用户卡住了。"]
    prompt_parts.append(f"当前章节内容：{req.chapter_content[:2000]}")
    if req.characters:
        prompt_parts.append(f"活跃角色：{'、'.join(req.characters)}")
    if req.foreshadowing:
        prompt_parts.append(f"待回收伏笔：{'、'.join(req.foreshadowing)}")
    prompt_parts.append("请给出3个不同的续写方向，每个方向用一句话概括。每行格式：标题：内容")
    prompt = "\n".join(prompt_parts)

    payload = {
        "model": provider_cfg["default_model"],
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 1024,
        "stream": False,
    }

    url = provider_cfg["base_url"].rstrip("/") + provider_cfg["chat_endpoint"]
    headers = provider_cfg["auth_header"](api_key)
    headers["Content-Type"] = provider_cfg["content_type"]

    try:
        result = await _non_stream_chat(payload, provider_cfg, headers)
        content = result.get("content", "")
    except Exception as e:
        # 降级：返回格式化建议
        content = _fallback_stuck_suggestions(req)

    # 解析响应，提取3个建议
    suggestions = _parse_stuck_suggestions(content)
    return StuckResponse(suggestions=suggestions)


def _parse_stuck_suggestions(text: str) -> list[StuckSuggestion]:
    """解析 AI 返回的文本，提取结构化的续写建议"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    suggestions = []
    for line in lines:
        if ":" in line:
            title, summary = line.split(":", 1)
            suggestions.append(StuckSuggestion(
                title=title.strip(),
                summary=summary.strip(),
            ))
        elif "：" in line:
            title, summary = line.split("：", 1)
            suggestions.append(StuckSuggestion(
                title=title.strip(),
                summary=summary.strip(),
            ))
    if len(suggestions) >= 3:
        return suggestions[:3]
    # 如果解析出的不够，补默认
    while len(suggestions) < 3:
        idx = len(suggestions) + 1
        suggestions.append(StuckSuggestion(
            title=f"方向{idx}",
            summary=f"从当前章节的自然走向出发，继续推进故事情节。",
        ))
    return suggestions[:3]


def _fallback_stuck_suggestions(req: StuckRequest) -> str:
    """API 不可用时，返回格式化的默认建议"""
    chars = "、".join(req.characters) if req.characters else "当前角色"
    fores = "、".join(req.foreshadowing) if req.foreshadowing else "已有的伏笔"
    return f"""方向一：回到冲突核心：让{chars}在当前场景中最紧张的关系上再推一步。
方向二：伏笔回收：找一个机会自然地带出{fores}，不必明说，让读者隐约感知。
方向三：留一扇窗：在章节结尾留出一个未回答的问题，为下一章制造悬念。"""
