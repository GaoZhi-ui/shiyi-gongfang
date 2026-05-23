"""
项目配置共享模块
避免 chapters.py 和 export.py 各写一份 _resolve_active_project_id
"""

import json
from pathlib import Path

# 项目的基目录：writing-app/
BASE = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE / "projects"


def resolve_active_project_id() -> str:
    """从 projects/config.json 读取当前活跃项目 ID"""
    try:
        config_path = PROJECTS_DIR / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            return cfg.get("active_project", "default")
    except Exception:
        pass
    return "default"


def diary_dir(project_id: str | None = None) -> Path:
    """获取指定项目的日记目录"""
    pid = project_id or resolve_active_project_id()
    d = PROJECTS_DIR / pid / "diary"
    d.mkdir(parents=True, exist_ok=True)
    return d
