"""
API Key 管理路由

GET    /keys              — 查看已配置的 key 列表（不含密钥原文）
POST   /keys              — 新增/更新某个 provider 的 API Key
DELETE /keys/{provider}   — 删除指定 provider 的 key
GET    /keys/{provider}/test — 测试 key 连通性
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)

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


# ─── 路由 ───


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
    """测试指定 provider 的 API Key 连通性"""
    provider = provider.strip().lower()
    km = _get_key_manager()
    config = km.get_config(provider)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "KEY_NOT_CONFIGURED",
                "message": f"{provider} 的 API Key 未配置",
                "detail": "请先通过 POST /api/v1/keys 配置 key",
                "suggestion": f"POST /api/v1/keys  {{'provider': '{provider}', 'api_key': '...'}}",
            },
        )

    import httpx
    raw_key = km.get_key(provider)

    # 根据 provider 类型选择测试方式和端点
    provider_lower = provider.lower()

    async def _test_openai_compat(base_url: str) -> tuple[bool, str]:
        """对 OpenAI 兼容接口做轻量测试"""
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
                return False, "API Key 无效（401 Unauthorized）"
            elif resp.status_code == 429:
                return True, "连接成功但触发限流（429），Key 有效"
            else:
                return False, f"返回异常状态码 {resp.status_code}: {resp.text[:200]}"

    async def _test_anthropic() -> tuple[bool, str]:
        """Anthropic Claude 专用测试"""
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
                return False, "API Key 无效（401 Unauthorized）"
            else:
                return False, f"返回异常状态码 {resp.status_code}: {resp.text[:200]}"

    try:
        if "anthropic" in provider_lower or "claude" in provider_lower:
            ok, detail = await _test_anthropic()
        else:
            base_url = config.get("endpoint") or _default_endpoint(provider_lower)
            ok, detail = await _test_openai_compat(base_url)
    except httpx.TimeoutException:
        return KeyTestResponse(status="error", provider=provider, detail="请求超时（15秒），请检查网络或端点地址")
    except httpx.ConnectError:
        return KeyTestResponse(status="error", provider=provider, detail="无法连接，请检查端点地址或网络代理设置")
    except Exception as e:
        return KeyTestResponse(status="error", provider=provider, detail=f"测试异常: {type(e).__name__}: {e}")

    return KeyTestResponse(status="ok" if ok else "error", provider=provider, detail=detail)


def _default_endpoint(provider: str) -> str:
    """返回 provider 的默认 API 端点"""
    defaults = {
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
    }
    return defaults.get(provider, "https://api.deepseek.com/v1")


@router.get("/{provider}/models")
async def list_models(provider: str):
    """获取指定 provider 的可用模型列表"""
    provider = provider.strip().lower()
    km = _get_key_manager()

    # Ollama 使用独立 API
    if provider == "ollama":
        import httpx
        try:
            config = km.get_config(provider)
            base = (config.get("endpoint", "http://localhost:11434") if config else "http://localhost:11434").rstrip("/")
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(base + "/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    return {"provider": provider, "models": models}
        except Exception:
            pass
        return {"provider": provider, "models": []}

    # OpenAI 兼容：GET /v1/models
    config = km.get_config(provider)
    if config is None:
        return {"provider": provider, "models": []}

    raw_key = km.get_key(provider)
    base_url = config.get("endpoint", _default_endpoint(provider)).rstrip("/")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                base_url + "/models",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", [])]
                return {"provider": provider, "models": models}
    except Exception:
        pass

    return {"provider": provider, "models": []}
