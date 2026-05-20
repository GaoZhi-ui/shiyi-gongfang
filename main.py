"""
泰拉拾遗录·写作工坊 — FastAPI 后端
运行: uvicorn main:app --reload --port 8000
"""

import os, json, re
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

BASE = Path(__file__).parent
STATIC = BASE / "static"

app = FastAPI(title="拾遗工坊")
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

STATIC.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

@app.get("/")
async def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
