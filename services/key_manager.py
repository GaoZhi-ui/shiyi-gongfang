"""
Key Manager — API Key 加密存储
Fernet 对称加密，密钥从主机特征派生
"""

import os, json, base64, hashlib, platform
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

BASE = Path(__file__).parent.parent
CONFIG_FILE = BASE / "config.json"


def _derive_key() -> bytes:
    """从机器特征派生加密密钥"""
    raw = f"{platform.node()}-{platform.machine()}-{os.environ.get('USERNAME', 'unknown')}"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"shiyigongfang", iterations=100000)
    return base64.urlsafe_b64encode(kdf.derive(raw.encode()))


def _load_or_create_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"api_keys": {}, "endpoint": "https://api.deepseek.com/v1", "model": "deepseek-chat"}


def _save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def save_key(provider: str, key: str):
    cfg = _load_or_create_config()
    cipher = Fernet(_derive_key())
    cfg.setdefault("api_keys", {})[provider] = cipher.encrypt(key.encode()).decode()
    _save_config(cfg)


def get_key(provider: str) -> str | None:
    cfg = _load_or_create_config()
    encrypted = cfg.get("api_keys", {}).get(provider)
    if not encrypted:
        return None
    try:
        cipher = Fernet(_derive_key())
        return cipher.decrypt(encrypted.encode()).decode()
    except Exception:
        return None


def delete_key(provider: str):
    cfg = _load_or_create_config()
    cfg.get("api_keys", {}).pop(provider, None)
    _save_config(cfg)


def get_config() -> dict:
    cfg = _load_or_create_config()
    providers = {}
    for p in cfg.get("api_keys", {}):
        providers[p] = bool(get_key(p))
    return {
        "endpoint": cfg.get("endpoint", "https://api.deepseek.com/v1"),
        "model": cfg.get("model", "deepseek-chat"),
        "providers": providers,
    }


def list_providers() -> list[str]:
    cfg = _load_or_create_config()
    return list(cfg.get("api_keys", {}).keys())


async def test_key(provider: str, key: str) -> bool:
    """测试API Key连通性"""
    import httpx
    endpoints = {
        "openai": "https://api.openai.com/v1/models",
        "deepseek": "https://api.deepseek.com/v1/models",
        "claude": "https://api.anthropic.com/v1/messages",
    }
    url = endpoints.get(provider)
    if not url:
        return False
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "claude":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            return resp.status_code == 200
    except Exception:
        return False
