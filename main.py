"""
写作助手工坊 — FastAPI 后端
运行: uvicorn main:app --reload --port 8000
"""

import logging, os, json, re
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from routers.health import router as health_router
from routers.keys import router as keys_router
from routers.knowledge import router as knowledge_router
from routers.chapters import router as chapters_router
from routers.chat import router as chat_router
from routers.tools import router as tools_router
from routers.workflow import router as workflow_router
from routers.scenes import router as scenes_router
from routers.projects import router as projects_router
from routers.tools_router import router as mcp_tools_router
from routers.goals import router as goals_router
from routers.characters import router as characters_router
from routers.foreshadowing import router as foreshadowing_router
from routers.snapshots import router as snapshots_router
from routers.export import router as export_router
from routers.stats import router as stats_router
from routers.backup import router as backup_router
from routers.style_check import router as style_router
from routers.plugins import router as plugins_router
from routers.harness_report import router as harness_router
from core.plugin_manager import plugin_manager, logger as plugin_logger
from core.writing_rules import discover_and_register

# 插件日志设置
plugin_logger.setLevel(logging.INFO)
sh = logging.StreamHandler()
sh.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
plugin_logger.addHandler(sh)

BASE = Path(__file__).parent
STATIC = BASE / "static"

def _startup():
    plugin_manager.load_all(app, BASE / "plugins")
    count = discover_and_register("core.rules")
    logging.info(f"WritingRule 插件加载完成: {count} 条规则")


app = FastAPI(title="写作助手工坊", on_startup=[_startup])
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health_router, prefix="/api/v1")
app.include_router(keys_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(chapters_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(tools_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(scenes_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(mcp_tools_router, prefix="/api/v1")
app.include_router(goals_router, prefix="/api/v1")
app.include_router(characters_router, prefix="/api/v1")
app.include_router(foreshadowing_router, prefix="/api/v1")
app.include_router(snapshots_router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")
app.include_router(stats_router, prefix="/api/v1")
app.include_router(backup_router, prefix="/api/v1")
app.include_router(style_router, prefix="/api/v1")
app.include_router(plugins_router, prefix="/api/v1")
app.include_router(harness_router, prefix="/api/v1")

STATIC.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# 导出文件下载
EXPORT = BASE / "export"
EXPORT.mkdir(exist_ok=True)
app.mount("/export", StaticFiles(directory=str(EXPORT)), name="export")

@app.get("/")
async def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

if __name__ == "__main__":
    import sys
    import uvicorn
    if "--gui" in sys.argv:
        # GUI 模式：启动服务器并打开原生窗口
        from run_gui import main as gui_main
        gui_main()
    else:
        # 标准模式：仅启动服务器
        uvicorn.run(app, host="127.0.0.1", port=8000)
