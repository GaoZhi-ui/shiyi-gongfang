"""
Key Manager — API Key 加密存储
Fernet 对称加密，密钥从主机特征+随机盐派生
"""

import os, json, base64, platform
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

BASE = Path(__file__).parent.parent
CONFIG_FILE = BASE / "config.json"
SALT_FIELD = "_key_salt"


def _get_salt() -> bytes:
    cfg = _load_config()
    salt = cfg.get(SALT_FIELD)
    if not salt:
        salt = base64.b64encode(os.urandom(16)).decode()
        cfg[SALT_FIELD] = salt
        _save_config(cfg)
    return salt.encode()


def _derive_key() -> bytes:
    raw = f"{platform.node()}-{platform.machine()}-{os.environ.get('USERNAME', 'unknown')}"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_get_salt(), iterations=100000)
    return base64.urlsafe_b64encode(kdf.derive(raw.encode()))


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def save_key(provider: str, key: str):
    cfg = _load_config()
    cipher = Fernet(_derive_key())
    cfg.setdefault("api_keys", {})[provider] = cipher.encrypt(key.encode()).decode()
    _save_config(cfg)


def get_key(provider: str) -> str | None:
    encrypted = _load_config().get("api_keys", {}).get(provider)
    if not encrypted:
        return None
    try:
        return Fernet(_derive_key()).decrypt(encrypted.encode()).decode()
    except Exception:
        return None


def delete_key(provider: str):
    cfg = _load_config()
    cfg.get("api_keys", {}).pop(provider, None)
    _save_config(cfg)


def get_config() -> dict:
    cfg = _load_config()
    providers = {p: bool(get_key(p)) for p in cfg.get("api_keys", {})}
    return {
        "endpoint": cfg.get("endpoint", "https://api.deepseek.com/v1"),
        "model": cfg.get("model", "deepseek-chat"),
        "providers": providers,
    }


def list_providers() -> list[str]:
    return list(_load_config().get("api_keys", {}).keys())


async def test_key(provider: str, key: str) -> bool:
    import httpx
    urls = {
        "openai": "https://api.openai.com/v1/models",
        "deepseek": "https://api.deepseek.com/v1/models",
        "claude": "https://api.anthropic.com/v1/messages",
    }
    # 本地 provider 不需要测试
    if provider == "ollama":
        return True
    url = urls.get(provider)
    if not url:
        return False
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "claude":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            return (await client.get(url, headers=headers)).status_code == 200
    except Exception:
        return False
