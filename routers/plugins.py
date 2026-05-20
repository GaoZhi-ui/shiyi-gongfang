"""
插件管理路由

GET    /plugins              — 列出已加载插件
POST   /plugins/load         — 从文件加载插件

路径前缀 /api/v1/plugins
"""

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from core.plugin_manager import plugin_manager

router = APIRouter(prefix="/plugins", tags=["plugins"])

BASE = Path(__file__).resolve().parent.parent
PLUGINS_DIR = BASE / "plugins"


class LoadPluginBody(BaseModel):
    path: str = Field(..., description="插件文件路径（绝对路径或相对项目根目录的路径）")


@router.get("")
def list_plugins():
    """列出所有已注册（含已加载和尚未调用 on_load）的插件"""
    return {
        "plugins": plugin_manager.list_plugins(),
        "count": len(plugin_manager.list_plugins()),
    }


@router.post("/load", status_code=201)
def load_plugin(body: LoadPluginBody):
    """从文件加载插件，自动注册并调用 on_load（如果 app 已传入则触发 on_load）"""
    plugin_path = Path(body.path)

    # 相对路径 → 相对于项目根目录
    if not plugin_path.is_absolute():
        plugin_path = BASE / plugin_path

    if not plugin_path.exists():
        raise HTTPException(404, detail={
            "code": "PLUGIN_FILE_NOT_FOUND",
            "message": f"插件文件不存在: {body.path}",
        })

    if not plugin_path.suffix == ".py":
        raise HTTPException(400, detail={
            "code": "INVALID_FILE_TYPE",
            "message": "仅支持 .py 文件",
        })

    # 加载但暂时不触发 on_load（因为 app 引用在 main 中处理）
    result = plugin_manager.load_plugin(str(plugin_path))
    if result is None:
        raise HTTPException(422, detail={
            "code": "PLUGIN_LOAD_FAILED",
            "message": f"无法从 {body.path} 加载任何插件",
        })

    return {
        "status": "loaded",
        "plugin": result,
        "note": "插件已注册。需要在 main.py 中调用 plugin_manager.load_all(app) 触发 on_load。",
    }
