"""
健康检查路由
GET /api/v1/health — 返回服务状态、版本号、配置概览
"""

import sys
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter

router = APIRouter(tags=["health"])

BASE = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE / "config.yaml"
CONFIG_JSON = BASE / "config.json"
DATA_DIR = BASE / "data"


def _load_config_preview() -> dict:
    """读取配置概览（不含敏感信息）"""
    # 优先 yaml，回退 json
    if CONFIG_FILE.exists():
        try:
            import yaml
            cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
            return {
                "active_project": cfg.get("active_project", ""),
                "projects_count": len(cfg.get("projects", {})),
                "knowledge_bases": list(cfg.get("knowledge_base", {}).keys()),
                "key_storage_method": cfg.get("key_storage", {}).get("method", "encrypted"),
            }
        except Exception:
            return {"active_project": "", "note": "config.yaml parse error"}
    if CONFIG_JSON.exists():
        try:
            import json
            cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
            return {
                "has_api_key": bool(cfg.get("api_key")),
                "endpoint": cfg.get("api_endpoint", ""),
                "model": cfg.get("model", ""),
            }
        except Exception:
            return {"note": "config.json parse error"}
    return {"note": "no config file found"}


def _check_paths() -> dict:
    """检查关键目录是否存在"""
    return {
        "chapters": (BASE / "chapters").is_dir(),
        "knowledge": (BASE / "knowledge").is_dir(),
        "data": DATA_DIR.is_dir(),
        "routers": (BASE / "routers").is_dir(),
        "static": (BASE / "static").is_dir(),
    }


@router.get("/health")
def health_check():
    config_preview = _load_config_preview()
    paths = _check_paths()

    return {
        "status": "ok",
        "app": "写作助手工坊",
        "version": "2.0.0",
        "python_version": sys.version.split()[0],
        "timestamp": datetime.now().astimezone().isoformat(),
        "config": config_preview,
        "paths": paths,
    }
