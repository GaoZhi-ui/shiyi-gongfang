"""
API Key 管理路由

GET    /keys                       — 查看已配置的 key 列表（不含密钥原文）
POST   /keys                       — 新增/更新某个 provider 的 API Key
DELETE /keys/{provider}            — 删除指定 provider 的 key
GET    /keys/families              — 返回协议族列表（供前端渲染设置页）
GET    /keys/{provider}/test       — 测试 key 连通性（区分多种失败原因）
GET    /keys/{provider}/models     — 获取可用模型列表（含错误描述）
POST   /keys/validate              — 同时验证 endpoint + key + provider 兼容性
"""

import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)


# ─── Ollama 自动探测 ───


def detect_ollama() -> dict:
    """检测本地 Ollama 是否运行，返回状态信息。超时 2s，不阻塞其他功能。"""
    endpoint = "http://localhost:11434"
    try:
        resp = httpx.get(f"{endpoint}/api/tags", timeout=2)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return {
                "running": True,
                "models": models,
                "endpoint": endpoint,
                "model_count": len(models),
            }
        return {
            "running": False,
            "models": [],
            "endpoint": endpoint,
            "detail": f"Ollama 返回状态码 {resp.status_code}",
        }
    except httpx.ConnectError:
        return {
            "running": False,
            "models": [],
            "endpoint": endpoint,
            "detail": "Ollama 未运行（连接拒绝）",
        }
    except httpx.TimeoutException:
        return {
            "running": False,
            "models": [],
            "endpoint": endpoint,
            "detail": "Ollama 连接超时（2s）",
        }
    except Exception as e:
        return {
            "running": False,
            "models": [],
            "endpoint": endpoint,
            "detail": f"探测异常: {type(e).__name__}",
        }

# ─── 异常消息截断 ───

_KEY_SANITIZE_PATTERNS = [
    # api_key=xxx / api_key: xxx / "api_key": "xxx"
    (re.compile(r'(api_key["\']?\s*[:=]\s*["\']?)[^"\',;}\s]+', re.IGNORECASE), r'\1****'),
    # Authorization: Bearer sk-...
    (re.compile(r'(Bearer\s+)[A-Za-z0-9_\-]{8,}'), r'\1****'),
    # x-api-key: sk-...
    (re.compile(r'(x-api-key["\']?\s*[:=]\s*["\']?)[^"\',;}\s]+', re.IGNORECASE), r'\1****'),
]


def _sanitize_error(msg: str) -> str:
    """从错误消息中移除可能泄露的 API Key 片段，防御性深度清理。"""
    for pattern, replacement in _KEY_SANITIZE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg

# 延迟导入 KeyManager（services 层尚未实现时优雅降级）
key_manager = None


def _get_key_manager():
    global key_manager
    if key_manager is not None:
        return key_manager
    try:
        from services.key_manager import KeyManager
        key_manager = KeyManager(storage_path=DATA_DIR / "keys.json")
        return key_manager
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SERVICE_UNAVAILABLE",
                "message": "key_manager 服务未实现",
                "suggestion": "请先实现 services/key_manager.py",
            },
        )


router = APIRouter(prefix="/keys", tags=["keys"])


# ─── Pydantic 模型 ───


class KeyCreate(BaseModel):
    provider: str = Field(..., description="服务商标识，如 deepseek / openai / claude")
    api_key: str = Field(..., min_length=1, description="API Key 原文")
    endpoint: str = Field("", description="自定义 API 端点，为空则使用默认")
    model: str = Field("", description="默认模型名，为空则使用服务商默认")


class KeyListResponse(BaseModel):
    provider: str
    configured: bool
    endpoint: str | None = None
    model: str | None = None
    key_preview: str | None = None


class KeyDeleteResponse(BaseModel):
    status: str
    provider: str


class KeyTestResponse(BaseModel):
    status: str
    provider: str
    detail: str


class ValidateBody(BaseModel):
    provider: str = Field(..., description="服务商标识")
    api_key: str = Field("", description="API Key（本地模型可为空）")
    endpoint: str = Field("", description="API 端点 URL")


class ValidateResponse(BaseModel):
    status: str  # ok / error
    provider: str
    endpoint_valid: bool
    auth_valid: bool | None = None
    models_accessible: bool | None = None
    models_count: int | None = None
    message: str


# ─── 模型列表缓存（可选，减少重复请求） ───

_models_cache: dict[str, tuple[list[str], float]] = {}  # provider -> (models, timestamp)
_MODELS_CACHE_TTL = 60  # 秒


def _get_cached_models(provider: str) -> list[str] | None:
    import time
    entry = _models_cache.get(provider)
    if entry and time.time() - entry[1] < _MODELS_CACHE_TTL:
        return entry[0]
    return None


def _set_cached_models(provider: str, models: list[str]):
    import time
    _models_cache[provider] = (models, time.time())


# ─── 默认端点映射 ───


DEFAULT_ENDPOINTS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "claude": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "yi": "https://api.lingyiwanwu.com/v1",
    "ollama": "http://localhost:11434",
}


def _resolve_endpoint(provider: str, endpoint: str | None = None) -> str:
    if endpoint:
        return endpoint.rstrip("/")
    return DEFAULT_ENDPOINTS.get(provider, "https://api.deepseek.com/v1")


def _raise_key_config_error(provider: str):
    raise HTTPException(
        status_code=404,
        detail={
            "code": "KEY_NOT_CONFIGURED",
            "message": f"{provider} 的 API Key 未配置",
            "detail": "请先通过 POST /api/v1/keys 配置 key",
            "suggestion": f"POST /api/v1/keys  {{'provider': '{provider}', 'api_key': '...'}}",
        },
    )


# ─── 路由 ───


@router.get("/families")
def list_families():
    """
    返回协议族列表和各族的 provider 信息，供前端渲染设置页。

    返回结构：
    {
        "families": [
            {
                "id": "remote",
                "label": "远程 API",
                "local": false,
                "providers": [
                    {"id": "deepseek", "name": "DeepSeek", "default_model": "...",
                     "configured": true, "status": "connected"}
                ]
            }
        ]
    }
    """
    from routers.chat import PROVIDER_FAMILIES
    km = _get_key_manager()
    result = []
    for family_id, config in PROVIDER_FAMILIES.items():
        providers = []
        for pid, info in config["providers"].items():
            has_key = km.get_key(pid) is not None
            providers.append({
                "id": pid,
                "name": info["name"],
                "default_model": info.get("default_model"),
                "configured": has_key,
                "status": "connected" if has_key else "disconnected",
            })
        result.append({
            "id": family_id,
            "label": config["label"],
            "local": any(p.get("local") for p in config["providers"].values()),
            "providers": providers,
        })
    return {"families": result}


@router.get("", response_model=list[KeyListResponse])
def list_keys():
    """返回所有已配置的服务商列表（密钥原文不出现在响应中）"""
    km = _get_key_manager()
    providers = km.list_providers()
    return [
        KeyListResponse(
            provider=p,
            configured=True,
            endpoint=info.get("endpoint"),
            model=info.get("model"),
            key_preview=info.get("key_preview"),
        )
        for p, info in providers.items()
    ] if providers else []


@router.post("", status_code=201)
def create_key(body: KeyCreate):
    """新增或更新某个 provider 的 API Key"""
    if not body.api_key.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PARAMETER",
                "message": "API Key 不能为空",
                "detail": "api_key 字段必须包含非空字符串",
                "suggestion": "请传入有效的 API Key",
            },
        )
    provider = body.provider.strip().lower()
    km = _get_key_manager()
    km.save_key(
        provider=provider,
        api_key=body.api_key.strip(),
        endpoint=body.endpoint.strip() or None,
        model=body.model.strip() or None,
    )
    return {"status": "ok", "provider": provider, "message": f"{provider} API Key 已保存"}


@router.delete("/{provider}", response_model=KeyDeleteResponse)
def delete_key(provider: str):
    """删除指定 provider 的 API Key"""
    provider = provider.strip().lower()
    km = _get_key_manager()
    existed = km.delete_key(provider)
    if not existed:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "KEY_NOT_FOUND",
                "message": f"{provider} 的 API Key 未配置",
                "detail": f"provider={provider} 在 keys.json 中不存在",
                "suggestion": "请先通过 GET /api/v1/keys 查看已配置的 provider",
            },
        )
    return {"status": "ok", "provider": provider}


@router.get("/{provider}/test", response_model=KeyTestResponse)
async def test_key(provider: str):
    """
    测试指定 provider 的 API Key 连通性。

    错误消息细化：
    | 情况 | 消息 |
    |------|------|
    | 401 | API Key 无效，请检查是否正确 |
    | 429 | 请求过频，请稍后重试 |
    | 超时 (15s) | 连接超时，请检查 endpoint 地址 |
    | DNS 失败 | 无法解析地址，请检查 URL |
    | 连接拒绝 | 端口无响应，请确认服务是否运行 |
    | Ollama 连接拒绝 | Ollama 未运行，请执行 ollama serve |
    """
    provider = provider.strip().lower()
    km = _get_key_manager()
    config = km.get_config(provider)
    if config is None:
        _raise_key_config_error(provider)

    import httpx
    raw_key = km.get_key(provider)

    # 检查是否为 Ollama
    is_ollama = provider == "ollama"

    async def _test_openai_compat(base_url: str) -> tuple[bool, str]:
        url = base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": config.get("model", "deepseek-chat"),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        headers = {"Authorization": f"Bearer {raw_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return True, "连接成功，API Key 有效"
            elif resp.status_code == 401:
                return False, "API Key 无效，请检查是否正确"
            elif resp.status_code == 429:
                return False, "请求过频，请稍后重试"
            else:
                return False, f"返回异常状态码 {resp.status_code}: {resp.text[:200]}"

    async def _test_anthropic() -> tuple[bool, str]:
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": config.get("model", "claude-sonnet-4-20250514"),
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        headers = {
            "x-api-key": raw_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return True, "连接成功，API Key 有效"
            elif resp.status_code == 401:
                return False, "API Key 无效，请检查是否正确"
            elif resp.status_code == 429:
                return False, "请求过频，请稍后重试"
            else:
                return False, f"返回异常状态码 {resp.status_code}: {resp.text[:200]}"

    try:
        if "anthropic" in provider or "claude" in provider:
            ok, detail = await _test_anthropic()
        else:
            base_url = config.get("endpoint") or _resolve_endpoint(provider)
            ok, detail = await _test_openai_compat(base_url)
    except httpx.TimeoutException:
        return KeyTestResponse(
            status="error", provider=provider,
            detail="连接超时，请检查 endpoint 地址",
        )
    except httpx.ConnectError as e:
        err_msg = str(e).lower()
        if is_ollama and ("connection refused" in err_msg or "111" in err_msg):
            return KeyTestResponse(
                status="error", provider=provider,
                detail="Ollama 未运行，请执行 ollama serve",
            )
        if "connection refused" in err_msg:
            return KeyTestResponse(
                status="error", provider=provider,
                detail="端口无响应，请确认服务是否运行",
            )
        if "name or service not known" in err_msg or "nodename nor servname" in err_msg:
            return KeyTestResponse(
                status="error", provider=provider,
                detail="无法解析地址，请检查 URL",
            )
        return KeyTestResponse(
            status="error", provider=provider,
            detail=_sanitize_error(f"无法连接：{err_msg[:120]}"),
        )
    except Exception as e:
        return KeyTestResponse(
            status="error", provider=provider,
            detail=_sanitize_error(f"测试异常: {type(e).__name__}: {e}"),
        )

    return KeyTestResponse(
        status="ok" if ok else "error",
        provider=provider,
        detail=detail,
    )


@router.get("/{provider}/models")
async def list_models(provider: str):
    """
    获取指定 provider 的可用模型列表。

    错误处理改进：
    - 未配置 → 返回明确错误信息
    - 认证失败 → 返回 401 提示
    - 网络错误 → 返回具体的连接错误描述
    - Ollama → 3s 超时
    - 缓存 → 60s TTL 缓存模型列表，减少重复请求
    """
    provider = provider.strip().lower()
    km = _get_key_manager()

    # 尝试缓存
    cached = _get_cached_models(provider)
    if cached is not None:
        return {"provider": provider, "models": cached, "cached": True}

    import httpx

    config = km.get_config(provider)
    base_url = _resolve_endpoint(provider, config.get("endpoint") if config else None)

    # Ollama 使用独立 /api/tags 接口
    if provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(base_url + "/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    _set_cached_models(provider, models)
                    return {"provider": provider, "models": models, "cached": False}
                return {
                    "provider": provider, "models": [],
                    "error": f"Ollama 返回状态码 {resp.status_code}",
                }
        except httpx.TimeoutException:
            return {
                "provider": provider, "models": [],
                "error": "Ollama 连接超时（3s），请确认服务是否运行",
            }
        except httpx.ConnectError as e:
            err_msg = str(e).lower()
            if "connection refused" in err_msg:
                return {
                    "provider": provider, "models": [],
                    "error": "Ollama 未运行，请执行 ollama serve",
                }
            return {
                "provider": provider, "models": [],
                "error": _sanitize_error(f"Ollama 连接失败：{str(e)[:120]}"),
            }

    # OpenAI 兼容：GET /v1/models
    if config is None:
        return {
            "provider": provider, "models": [],
            "error": "未配置，请先通过 POST /keys 配置 API Key",
        }

    raw_key = km.get_key(provider)
    if not raw_key:
        return {
            "provider": provider, "models": [],
            "error": "API Key 未配置或已失效",
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                base_url + "/models",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", [])]
                _set_cached_models(provider, models)
                return {"provider": provider, "models": models, "cached": False}
            elif resp.status_code == 401:
                return {
                    "provider": provider, "models": [],
                    "error": "API Key 无效，请检查是否正确",
                }
            elif resp.status_code == 404:
                return {
                    "provider": provider, "models": [],
                    "error": "模型列表接口不存在，请检查 endpoint 地址",
                }
            else:
                return {
                    "provider": provider, "models": [],
                    "error": f"返回异常状态码 {resp.status_code}",
                }
    except httpx.TimeoutException:
        return {
            "provider": provider, "models": [],
            "error": "请求超时（10s），请检查 endpoint 地址",
        }
    except httpx.ConnectError as e:
        err_msg = str(e).lower()
        if "connection refused" in err_msg:
            return {
                "provider": provider, "models": [],
                "error": "端口无响应，请确认服务是否运行",
            }
        if "name or service not known" in err_msg or "nodename nor servname" in err_msg:
            return {
                "provider": provider, "models": [],
                "error": "无法解析地址，请检查 URL",
            }
        return {
            "provider": provider, "models": [],
            "error": _sanitize_error(f"连接失败：{str(e)[:120]}"),
        }
    except Exception as e:
        return {
            "provider": provider, "models": [],
            "error": _sanitize_error(f"获取模型列表异常: {type(e).__name__}: {e}"),
        }


@router.post("/validate", response_model=ValidateResponse)
async def validate_config(body: ValidateBody):
    """
    验证 provider 配置的完整性：
    1. 验证 endpoint URL 格式
    2. 测试连接
    3. 验证认证
    4. 获取模型列表
    5. 返回完整的验证结果
    """
    import httpx
    from urllib.parse import urlparse

    provider = body.provider.strip().lower()
    endpoint = body.endpoint.strip() or _resolve_endpoint(provider)
    api_key = body.api_key.strip()

    # 1. 验证 endpoint URL 格式
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return ValidateResponse(
            status="error",
            provider=provider,
            endpoint_valid=False,
            message=f"端点 URL 格式无效：{endpoint}",
        )
    endpoint_valid = True

    # Ollama 不需要 key，直接测试连接
    is_ollama = provider == "ollama"
    if is_ollama:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(endpoint.rstrip("/") + "/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    return ValidateResponse(
                        status="ok",
                        provider=provider,
                        endpoint_valid=True,
                        auth_valid=True,
                        models_accessible=True,
                        models_count=len(models),
                        message=f"Ollama 连接成功，共 {len(models)} 个模型可用",
                    )
                else:
                    return ValidateResponse(
                        status="error",
                        provider=provider,
                        endpoint_valid=True,
                        message=f"Ollama 返回异常状态码 {resp.status_code}",
                    )
        except httpx.TimeoutException:
            return ValidateResponse(
                status="error",
                provider=provider,
                endpoint_valid=True,
                message="连接超时（3s），请确认 Ollama 服务是否运行",
            )
        except httpx.ConnectError:
            return ValidateResponse(
                status="error",
                provider=provider,
                endpoint_valid=True,
                auth_valid=False,
                message="Ollama 未运行，请执行 ollama serve",
            )

    # 远程 provider：需要 key
    if not api_key:
        return ValidateResponse(
            status="error",
            provider=provider,
            endpoint_valid=endpoint_valid,
            auth_valid=False,
            message="API Key 不能为空",
        )

    # 2. 测试连接 + 3. 验证认证（一步完成）
    headers: dict[str, str] = {"Content-Type": "application/json"}
    is_anthropic = "anthropic" in provider or "claude" in provider

    try:
        if is_anthropic:
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            url = endpoint.rstrip("/") + "/messages"
            payload = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
        else:
            headers["Authorization"] = f"Bearer {api_key}"
            url = endpoint.rstrip("/") + "/chat/completions"
            payload = {
                "model": body.provider if body.provider else "deepseek-chat",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            auth_valid = True
            message = "连接成功，API Key 有效"
        elif resp.status_code == 401:
            return ValidateResponse(
                status="error",
                provider=provider,
                endpoint_valid=endpoint_valid,
                auth_valid=False,
                models_accessible=False,
                message="API Key 无效，请检查是否正确",
            )
        elif resp.status_code == 429:
            return ValidateResponse(
                status="ok",
                provider=provider,
                endpoint_valid=endpoint_valid,
                auth_valid=True,
                models_accessible=True,
                message="连接成功但触发限流（429），Key 有效",
            )
        else:
            return ValidateResponse(
                status="error",
                provider=provider,
                endpoint_valid=endpoint_valid,
                auth_valid=False,
                message=_sanitize_error(f"返回异常状态码 {resp.status_code}: {resp.text[:200]}"),
            )
    except httpx.TimeoutException:
        return ValidateResponse(
            status="error",
            provider=provider,
            endpoint_valid=endpoint_valid,
            message="连接超时（15s），请检查 endpoint 地址",
        )
    except httpx.ConnectError as e:
        err_msg = str(e).lower()
        if "connection refused" in err_msg:
            return ValidateResponse(
                status="error",
                provider=provider,
                endpoint_valid=endpoint_valid,
                message="端口无响应，请确认服务是否运行",
            )
        if "name or service not known" in err_msg or "nodename nor servname" in err_msg:
            return ValidateResponse(
                status="error",
                provider=provider,
                endpoint_valid=endpoint_valid,
                message="无法解析地址，请检查 URL",
            )
        return ValidateResponse(
            status="error",
            provider=provider,
            endpoint_valid=endpoint_valid,
            message=_sanitize_error(f"连接失败：{err_msg[:120]}"),
        )

    # 4. 获取模型列表
    try:
        if is_anthropic:
            # Anthropic 没有 /models 端点，跳过
            models_count = None
            models_accessible = None
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                models_resp = await client.get(
                    endpoint.rstrip("/") + "/models",
                    headers=headers,
                )
                if models_resp.status_code == 200:
                    models = [m["id"] for m in models_resp.json().get("data", [])]
                    models_count = len(models)
                    models_accessible = True
                    message = f"连接成功，API Key 有效，共 {models_count} 个模型可用"
                else:
                    models_accessible = False
                    models_count = 0
                    message = "连接成功，但无法获取模型列表"
    except Exception:
        models_accessible = False
        models_count = 0
        message = "连接成功，但获取模型列表失败"

    return ValidateResponse(
        status="ok",
        provider=provider,
        endpoint_valid=endpoint_valid,
        auth_valid=auth_valid,
        models_accessible=models_accessible,
        models_count=models_count,
        message=message,
    )


# ─── Auto-detect ───


class AutoDetectResponse(BaseModel):
    ollama: dict
    detected_services: list[dict]


@router.get("/auto-detect")
def auto_detect():
    """
    自动探测本地可用的 AI 服务。

    当前探测范围：
    - Ollama（http://localhost:11434）

    返回每个服务的运行状态、可用模型列表和端点地址。
    超时短（2s），不阻塞前端渲染。
    """
    ollama_info = detect_ollama()
    detected = []
    if ollama_info["running"]:
        detected.append({
            "service": "ollama",
            "name": "Ollama (本地)",
            "running": True,
            "endpoint": ollama_info["endpoint"],
            "models": ollama_info["models"],
            "model_count": ollama_info["model_count"],
        })
    return AutoDetectResponse(ollama=ollama_info, detected_services=detected)


# ─── 配置预设 ───


class PresetInfo(BaseModel):
    name: str
    system_prompt: str
    temperature: float
    max_tokens: int
    builtin: bool = False


class PresetBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="预设名称")
    system_prompt: str = Field(..., description="系统提示词")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(4096, ge=1, le=32768)


@router.get("/presets")
def list_presets():
    """返回所有预设（内置 + 自定义）"""
    km = _get_key_manager()
    return {"presets": km.get_presets()}


@router.post("/presets", status_code=201)
def save_preset(body: PresetBody):
    """保存自定义预设（覆盖同名）"""
    km = _get_key_manager()
    km.save_preset(
        name=body.name.strip(),
        system_prompt=body.system_prompt.strip(),
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )
    return {"status": "ok", "name": body.name.strip(), "message": f"预设「{body.name.strip()}」已保存"}


@router.delete("/presets/{name}")
def delete_preset(name: str):
    """删除自定义预设（不可删除内置预设）"""
    km = _get_key_manager()
    ok = km.delete_preset(name.strip())
    if not ok:
        raise HTTPException(status_code=404, detail={
            "code": "PRESET_NOT_FOUND",
            "message": f"预设「{name}」不存在或为内置预设不可删除",
        })
    return {"status": "ok", "name": name.strip(), "message": f"预设「{name.strip()}」已删除"}
