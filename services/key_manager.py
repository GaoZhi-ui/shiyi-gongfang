"""
Key Manager — API Key 存储升级版

存储层级（按优先级）：
1. 系统密钥链（keyring）—— Windows Credential Manager / macOS Keychain / Linux Secret Service
2. 自加密 JSON 文件（Fernet）—— keyring 不可用时的降级路径

元数据（endpoint/model）始终保存在 config.json，密钥本身走 keyring（或加密备选）。

预设管理（v2）：
- 内置预设：写作助手 / 润色审稿 / 头脑风暴 / 严谨分析
- 自定义预设：通过 save_preset() / delete_preset() 管理
- 优先级：自定义预设与内置预设不重名，可覆盖
"""

import os
import json
import base64
import platform
import re
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ─── 尝试导入 keyring ───

_USE_KEYRING = False
try:
    import keyring
    _USE_KEYRING = True
except ImportError:
    pass

SERVICE_NAME = "shiyi-gongfang"

# ─── 路径 ───

BASE = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE / "data" / "config.json"
SALT_FIELD = "_key_salt"
_KEYS_SECTION = "api_keys"

# ─── 日志过滤 ───

class APIKeyFilter(logging.Filter):
    """屏蔽日志中可能出现的 API Key 原文"""

    _PATTERN = re.compile(
        r'(api_key["\']?\s*[:=]\s*["\']?)[^"\',;}\s]+',
        re.IGNORECASE,
    )

    def filter(self, record) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = self._PATTERN.sub(r"\1****", record.msg)
        return True


# 注册全局日志过滤器
logging.getLogger().addFilter(APIKeyFilter())

# ─── 内部辅助：config.json 读写 ───


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _get_salt() -> bytes:
    cfg = _load_config()
    salt = cfg.get(SALT_FIELD)
    if not salt:
        salt = base64.b64encode(os.urandom(16)).decode()
        cfg[SALT_FIELD] = salt
        _save_config(cfg)
    return salt.encode()


def _derive_key() -> bytes:
    raw = (
        f"{platform.node()}-{platform.machine()}-"
        f"{os.environ.get('USERNAME', 'unknown')}"
    )
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=_get_salt(), iterations=100000
    )
    return base64.urlsafe_b64encode(kdf.derive(raw.encode()))


def _fernet_encrypt(plaintext: str) -> str:
    return Fernet(_derive_key()).encrypt(plaintext.encode()).decode()


def _fernet_decrypt(ciphertext: str) -> Optional[str]:
    try:
        return Fernet(_derive_key()).decrypt(ciphertext.encode()).decode()
    except Exception:
        return None


# ─── 迁移：旧 Fernet 加密格式 → 系统密钥链 ───


def _migrate_old_keys():
    """检测 config.json 中的旧 api_keys，解密后存入 keyring，然后清理旧数据。"""
    if not _USE_KEYRING:
        return
    cfg = _load_config()
    old_keys = cfg.get(_KEYS_SECTION)
    if not old_keys:
        return
    migrated = False
    for provider, entry in list(old_keys.items()):
        # 旧格式可能是加密字符串，也可能是 { "key": "<encrypted>" }
        if isinstance(entry, str) and entry:
            plain = _fernet_decrypt(entry)
        elif isinstance(entry, dict):
            plain = _fernet_decrypt(entry.get("key", ""))
        else:
            plain = None

        if plain:
            try:
                keyring.set_password(SERVICE_NAME, f"api_key_{provider}", plain)
                migrated = True
            except Exception:
                logging.getLogger(__name__).warning(
                    "keyring 存储失败（provider=%s），保留旧加密数据", provider
                )
                continue

        # 清理：只移除 key 字段，保留 endpoint/model 元数据
        if isinstance(entry, dict):
            entry.pop("key", None)
            if not entry:
                old_keys.pop(provider)
        else:
            old_keys.pop(provider)

    if migrated:
        # 如果所有 key 都被迁移且清空，移除整个 api_keys 段
        if not old_keys:
            cfg.pop(_KEYS_SECTION, None)
        _save_config(cfg)
        logging.getLogger(__name__).info("旧 API Key 已迁移至系统密钥链")


# 模块加载时自动迁移一次
_migrate_old_keys()

# ─── 模块级函数（writing_agent.py 等直接调用） ───


def save_key(provider: str, api_key: str):
    """保存 API Key。走 keyring（可用时），否则走 Fernet 加密。"""
    if _USE_KEYRING:
        try:
            keyring.set_password(SERVICE_NAME, f"api_key_{provider}", api_key)
            return
        except Exception:
            logging.getLogger(__name__).warning(
                "keyring 写入失败（provider=%s），降级到加密文件", provider
            )

    # 降级：Fernet 加密写入 config.json
    cfg = _load_config()
    keys = cfg.setdefault(_KEYS_SECTION, {})
    entry = keys.get(provider)
    if isinstance(entry, dict):
        entry["key"] = _fernet_encrypt(api_key)
    else:
        keys[provider] = _fernet_encrypt(api_key)
    _save_config(cfg)


def get_key(provider: str) -> Optional[str]:
    """获取 API Key 明文。先查 keyring，再查加密文件。"""
    if _USE_KEYRING:
        try:
            val = keyring.get_password(SERVICE_NAME, f"api_key_{provider}")
            if val is not None:
                return val
        except Exception:
            pass

    # 降级：从 config.json 读取加密 key
    cfg = _load_config()
    entry = cfg.get(_KEYS_SECTION, {}).get(provider)
    if not entry:
        return None
    if isinstance(entry, str):
        return _fernet_decrypt(entry)
    if isinstance(entry, dict):
        return _fernet_decrypt(entry.get("key", ""))
    return None


def delete_key(provider: str) -> bool:
    """删除 API Key。返回值表示是否存在。"""
    existed = False
    if _USE_KEYRING:
        try:
            keyring.delete_password(SERVICE_NAME, f"api_key_{provider}")
            existed = True
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception:
            pass

    # 同时清理 config.json 中的残留
    cfg = _load_config()
    keys = cfg.get(_KEYS_SECTION, {})
    if provider in keys:
        existed = True
        entry = keys[provider]
        if isinstance(entry, dict):
            entry.pop("key", None)
            if not entry:
                keys.pop(provider)
        else:
            keys.pop(provider)
        if not keys:
            cfg.pop(_KEYS_SECTION, None)
        _save_config(cfg)

    return existed


def list_providers() -> list[str]:
    """返回所有已配置的 provider 列表。"""
    cfg = _load_config()
    keys = cfg.get(_KEYS_SECTION, {})
    # 也扫描 keyring（API 可能会在 keyring 中但 config 没记录元数据）
    return list(keys.keys())


def get_config(provider: str) -> Optional[dict]:
    """获取指定 provider 的元数据（endpoint/model），不含密钥。"""
    cfg = _load_config()
    entry = cfg.get(_KEYS_SECTION, {}).get(provider)
    if not entry:
        key_present = False
        if _USE_KEYRING:
            try:
                key_present = keyring.get_password(SERVICE_NAME, f"api_key_{provider}") is not None
            except Exception:
                pass
        return {"endpoint": None, "model": None} if key_present else None
    if isinstance(entry, str):
        return {"endpoint": None, "model": None}
    return {
        "endpoint": entry.get("endpoint"),
        "model": entry.get("model"),
    }


async def test_key(provider: str, key: str) -> bool:
    """连通性测试（模块级，向后兼容）"""
    import httpx
    urls = {
        "openai": "https://api.openai.com/v1/models",
        "deepseek": "https://api.deepseek.com/v1/models",
        "claude": "https://api.anthropic.com/v1/messages",
    }
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


# ─── 配置预设 ───

PRESETS = {
    "写作助手": {
        "system_prompt": "你是一个专业的写作助手，擅长小说创作、文字润色、情节设计。回答简洁直接，不啰嗦，不评价自己的输出。根据用户的创作需求给出具体建议和可用的文字。",
        "temperature": 0.7,
        "max_tokens": 4096,
        "builtin": True,
    },
    "润色审稿": {
        "system_prompt": "你是一个文字润色专家，擅长修正语法、优化表达、提升文采。只输出润色后的文本，不添加说明、不解释改动、不评价原文。保持原文风格和语气的一致性。",
        "temperature": 0.3,
        "max_tokens": 2048,
        "builtin": True,
    },
    "头脑风暴": {
        "system_prompt": "你是一个创意策划助手。你的任务是提供多样化的想法和可能性，不做评判，不自我设限。对于每一个问题，给出至少3个不同的方向或方案。",
        "temperature": 0.9,
        "max_tokens": 3072,
        "builtin": True,
    },
    "严谨分析": {
        "system_prompt": "你是一个严谨的分析师。对于每个问题，先拆解前提，再推导结论。指出不确定之处，给有把握的判断就明确表态。避免模糊措辞和中立废话。",
        "temperature": 0.2,
        "max_tokens": 4096,
        "builtin": True,
    },
}

# 预设存储文件
_PRESETS_FILE = BASE / "data" / "custom_presets.json"


def _load_custom_presets() -> dict:
    """加载用户自定义预设"""
    if _PRESETS_FILE.exists():
        try:
            return json.loads(_PRESETS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_custom_presets(custom: dict):
    """保存用户自定义预设"""
    _PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PRESETS_FILE.write_text(
        json.dumps(custom, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_presets() -> list[dict]:
    """合并内置预设和自定义预设，返回列表"""
    result = []
    for name, config in PRESETS.items():
        result.append({
            "name": name,
            "system_prompt": config["system_prompt"],
            "temperature": config["temperature"],
            "max_tokens": config["max_tokens"],
            "builtin": True,
        })
    custom = _load_custom_presets()
    for name, config in custom.items():
        result.append({
            "name": name,
            "system_prompt": config.get("system_prompt", ""),
            "temperature": config.get("temperature", 0.7),
            "max_tokens": config.get("max_tokens", 4096),
            "builtin": False,
        })
    return result


def save_preset(name: str, system_prompt: str, temperature: float, max_tokens: int):
    """保存自定义预设（覆盖同名）"""
    custom = _load_custom_presets()
    custom[name] = {
        "system_prompt": system_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    _save_custom_presets(custom)


def delete_preset(name: str) -> bool:
    """删除自定义预设。返回是否成功删除。内置预设不可删除。"""
    if name in PRESETS:
        return False
    custom = _load_custom_presets()
    if name not in custom:
        return False
    del custom[name]
    _save_custom_presets(custom)
    return True


def get_preset_by_name(name: str) -> dict | None:
    """按名称查找预设（先查内置，再查自定义）"""
    if name in PRESETS:
        return {**PRESETS[name], "builtin": True}
    custom = _load_custom_presets()
    custom_entry = custom.get(name)
    if custom_entry:
        return {**custom_entry, "builtin": False}
    return None


# ─── KeyManager 类（延迟加载用，兼容 routers/keys.py、routers/chat.py、routers/generate.py） ───


class KeyManager:
    """
    API Key 管理器

    封装了密钥链（keyring）和自加密 JSON 两种存储路径。
    密钥本身优先存 keyring，元数据（endpoint/model）始终存 config.json。
    初始化时自动做一次旧格式 → keyring 的迁移。

    storage_path 参数仅用于向后兼容（路由层传入 DATA_DIR / "keys.json"），
    实际读写的是 data/config.json。
    """

    def __init__(self, storage_path: str | Path):
        self.storage_path = Path(storage_path)
        # 保持初始化语义一致：所有路由都传 DATA_DIR / "keys.json"
        if str(self.storage_path).endswith("keys.json"):
            self._config_path = Path(self.storage_path).parent / "config.json"
        else:
            self._config_path = Path(self.storage_path)

    def _load(self) -> dict:
        if self._config_path.exists():
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        return {}

    def _save(self, cfg: dict):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _derived_salt(self) -> bytes:
        cfg = self._load()
        salt = cfg.get(SALT_FIELD)
        if not salt:
            salt = base64.b64encode(os.urandom(16)).decode()
            cfg[SALT_FIELD] = salt
            self._save(cfg)
        return salt.encode() if isinstance(salt, str) else salt

    def _derive_key(self) -> bytes:
        salt = self._derived_salt()
        raw = (
            f"{platform.node()}-{platform.machine()}-"
            f"{os.environ.get('USERNAME', 'unknown')}"
        )
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000
        )
        return base64.urlsafe_b64encode(kdf.derive(raw.encode()))

    def _encrypt(self, plaintext: str) -> str:
        return Fernet(self._derive_key()).encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> Optional[str]:
        try:
            return Fernet(self._derive_key()).decrypt(ciphertext.encode()).decode()
        except Exception:
            return None

    def save_key(
        self,
        provider: str,
        api_key: str,
        endpoint: str | None = None,
        model: str | None = None,
    ):
        """
        保存 provider 的 API Key 和配置。

        密钥本身走 keyring（可用时），降级走 Fernet 加密。
        endpoint/model 元数据始终写入 config.json。
        """
        # 1. 保存密钥
        if _USE_KEYRING:
            try:
                keyring.set_password(SERVICE_NAME, f"api_key_{provider}", api_key)
            except Exception:
                logging.getLogger(__name__).warning(
                    "keyring 写入失败（provider=%s），降级到加密文件", provider
                )
                self._save_key_to_config(provider, api_key)
        else:
            self._save_key_to_config(provider, api_key)

        # 2. 保存元数据（endpoint/model）
        self._save_metadata(provider, endpoint, model)

    def _save_key_to_config(self, provider: str, api_key: str):
        """降级路径：Fernet 加密后写入 config.json"""
        cfg = self._load()
        keys = cfg.setdefault(_KEYS_SECTION, {})
        entry = keys.get(provider)
        if isinstance(entry, dict):
            entry["key"] = self._encrypt(api_key)
        else:
            keys[provider] = self._encrypt(api_key)
        self._save(cfg)

    def _save_metadata(
        self,
        provider: str,
        endpoint: str | None = None,
        model: str | None = None,
    ):
        cfg = self._load()
        keys = cfg.setdefault(_KEYS_SECTION, {})
        existing = keys.get(provider)

        if endpoint is None and model is None and existing is None:
            return

        if isinstance(existing, dict):
            if endpoint is not None:
                existing["endpoint"] = endpoint
            if model is not None:
                existing["model"] = model
        elif isinstance(existing, str):
            # 旧格式：升级为 dict
            new_entry = {}
            # 如果 keyring 不可用，旧值就是加密 key，需要保留
            if not _USE_KEYRING:
                new_entry["key"] = existing
            if endpoint is not None:
                new_entry["endpoint"] = endpoint
            if model is not None:
                new_entry["model"] = model
            keys[provider] = new_entry
        else:
            if endpoint is not None or model is not None:
                entry = {}
                if endpoint is not None:
                    entry["endpoint"] = endpoint
                if model is not None:
                    entry["model"] = model
                keys[provider] = entry

        self._save(cfg)

    def get_key(self, provider: str) -> Optional[str]:
        """获取 API Key 明文。先查 keyring，再查加密文件。"""
        if _USE_KEYRING:
            try:
                val = keyring.get_password(SERVICE_NAME, f"api_key_{provider}")
                if val is not None:
                    return val
            except Exception:
                pass

        # 降级：从 config.json 读取
        cfg = self._load()
        entry = cfg.get(_KEYS_SECTION, {}).get(provider)
        if not entry:
            return None
        if isinstance(entry, str):
            return self._decrypt(entry)
        return self._decrypt(entry.get("key", ""))

    def get_config(self, provider: str) -> Optional[dict]:
        """获取 provider 的配置（不含密钥明文）。"""
        cfg = self._load()
        entry = cfg.get(_KEYS_SECTION, {}).get(provider)
        if not entry:
            # 可能在 keyring 中有 key 但无元数据
            has_key = self.get_key(provider) is not None
            return {"endpoint": None, "model": None} if has_key else None
        if isinstance(entry, str):
            return {"endpoint": None, "model": None}
        return {
            "endpoint": entry.get("endpoint"),
            "model": entry.get("model"),
        }

    def delete_key(self, provider: str) -> bool:
        """删除 provider 的 key 和元数据。返回是否存在。"""
        existed = False

        # 从 keyring 删除
        if _USE_KEYRING:
            try:
                keyring.delete_password(SERVICE_NAME, f"api_key_{provider}")
                existed = True
            except keyring.errors.PasswordDeleteError:
                pass
            except Exception:
                pass

        # 从 config.json 删除
        cfg = self._load()
        keys = cfg.get(_KEYS_SECTION, {})
        if provider in keys:
            existed = True
            entry = keys[provider]
            if isinstance(entry, dict):
                entry.pop("key", None)
                # 如果有 endpoint/model 则保留空结构（让前端知道这个 provider 被配置过）
                if not entry.get("endpoint") and not entry.get("model"):
                    keys.pop(provider)
            else:
                keys.pop(provider)
            if not keys:
                cfg.pop(_KEYS_SECTION, None)
            self._save(cfg)

        return existed

    def list_providers(self) -> dict:
        """
        返回所有已配置的 provider 及其摘要信息。
        格式: { provider: { endpoint, model, key_preview } }
        key_preview 仅从 config.json 读取（keyring 中的 key 不暴露预览）。
        """
        cfg = self._load()
        keys = cfg.get(_KEYS_SECTION, {})
        result = {}
        for p, entry in keys.items():
            if isinstance(entry, str):
                result[p] = {
                    "endpoint": None,
                    "model": None,
                    "key_preview": entry[:12] + "..." if entry else None,
                }
            else:
                key_preview = None
                key_val = entry.get("key", "")
                if key_val:
                    key_preview = key_val[:12] + "..."
                result[p] = {
                    "endpoint": entry.get("endpoint"),
                    "model": entry.get("model"),
                    "key_preview": key_preview,
                }
        return result

    # ─── 预设管理 ───

    def get_presets(self) -> list[dict]:
        """获取所有预设（内置 + 自定义）"""
        return get_presets()

    def save_preset(self, name: str, system_prompt: str, temperature: float, max_tokens: int):
        """保存自定义预设"""
        return save_preset(name, system_prompt, temperature, max_tokens)

    def delete_preset(self, name: str) -> bool:
        """删除自定义预设"""
        return delete_preset(name)

    def get_preset_by_name(self, name: str) -> dict | None:
        """按名称查找预设"""
        return get_preset_by_name(name)
