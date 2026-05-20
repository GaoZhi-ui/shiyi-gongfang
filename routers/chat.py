"""
AI 聊天路由 — 流式 SSE / 非流式响应、会话历史管理

POST   /chat/completions        — 发送消息，获取流式或完整响应
GET    /chat/history            — 获取当前会话历史
DELETE /chat/history            — 清空当前会话历史
POST   /chat/history/export     — 导出聊天记录为 Markdown

路径前缀 /api/v1/chat

SSE 流式格式：
  data: {"type": "text", "content": "..."}
  data: {"type": "thinking", "content": "..."}
  data: {"type": "done", "content": "", "usage": {"prompt_tokens": N, "completion_tokens": N}}
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
            pass
    candidates = [
        BASE / "knowledge" / "泰拉拾遗录",
        Path("E:/openhanako-work/knowledge_base/泰拉拾遗录"),
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


class ChatRequest(BaseModel):
    model: str = Field("deepseek", description="模型标识: deepseek / openai / claude / google / moonshot / zhipu / yi")
    stream: bool = Field(True, description="是否流式响应")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(4096, ge=1, le=32768)
    system_prompt: str = Field(
        "你是《泰拉拾遗录》的专属写作助手。回答简洁、直接，不啰嗦。",
        description="系统提示词",
    )
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


# ─── Provider 配置 ───

PROVIDER_CONFIGS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
    },
    "openai": {
        "base_url": "https://api.openai.com",
        "default_model": "gpt-5.4",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
    },
    "claude": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "chat_endpoint": "/v1/messages",
        "auth_header": lambda key: {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        "content_type": "application/json",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-2.5-pro",
        "chat_endpoint": "/v1beta/openai/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn",
        "default_model": "kimi-k2.6",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn",
        "default_model": "glm-5.1",
        "chat_endpoint": "/api/paas/v4/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
    },
    "yi": {
        "base_url": "https://api.lingyiwanwu.com",
        "default_model": "yi-lightning",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "content_type": "application/json",
    },
}

DEFAULT_SYSTEM = "你是《泰拉拾遗录》的专属写手。放下日常的对话风格，切换到作家模式。回答简洁、直接、不啰嗦。"


# ─── 核心逻辑 ───


def _build_payload(provider: str, req: ChatRequest) -> dict:
    """构建请求体（OpenAI 兼容格式）"""
    provider_lower = provider.lower()
    cfg = PROVIDER_CONFIGS.get(provider_lower, PROVIDER_CONFIGS["deepseek"])
    model_name = cfg["default_model"]

    # 构建 messages
    messages = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})

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

    # 添加用户消息
    for msg in req.messages:
        messages.append({"role": msg.role, "content": msg.content})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": req.temperature,
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


async def _non_stream_chat(payload: dict, cfg: dict, headers: dict) -> dict:
    """非流式请求"""
    url = cfg["base_url"].rstrip("/") + cfg["chat_endpoint"]
    async with httpx.AsyncClient(timeout=120) as client:
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
        result = await _non_stream_chat(api_payload, provider_cfg, headers)

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
            async with httpx.AsyncClient(timeout=120) as client:
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

    lines = ["# 拾遗工坊 · 聊天记录导出", "", f"导出时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}", ""]
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
