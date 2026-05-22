"""
日记路由 — 日记与正文分离

日记按项目隔离，存储在 projects/{id}/diary/{day}.md
正文保存时不再包含日记部分，日记通过独立 API 管理。

GET    /diary/{project_id}                    — 列出所有日记
GET    /diary/{project_id}/{day}              — 读取某天日记
PUT    /diary/{project_id}/{day}              — 写入/更新日记
DELETE /diary/{project_id}/{day}              — 删除日记
"""

from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/diary", tags=["diary"])
BASE = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE / "projects"


class DiaryEntry(BaseModel):
    content: str = Field(..., description="日记内容")


class DiaryResponse(BaseModel):
    day: int
    content: str
    updated_at: str


def _diary_dir(project_id: str) -> Path:
    """获取项目的日记目录"""
    proj_dir = (PROJECTS_DIR / project_id).resolve()
    if not str(proj_dir).startswith(str(PROJECTS_DIR.resolve())):
        raise HTTPException(400, detail="路径越界")
    diary_dir = proj_dir / "diary"
    diary_dir.mkdir(parents=True, exist_ok=True)
    return diary_dir


@router.get("/{project_id}")
def list_diary(project_id: str):
    """列出项目所有日记"""
    diary_dir = _diary_dir(project_id)
    entries = []
    for f in sorted(diary_dir.glob("*.md"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        day = int(f.stem) if f.stem.isdigit() else 0
        content = f.read_text(encoding="utf-8", errors="replace").strip()
        entries.append({
            "day": day,
            "content": content[:100] + ("..." if len(content) > 100 else ""),
            "updated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return {"project_id": project_id, "entries": entries, "count": len(entries)}


@router.get("/{project_id}/{day}")
def read_diary(project_id: str, day: int):
    """读取某天日记"""
    diary_dir = _diary_dir(project_id)
    fp = diary_dir / f"{day}.md"
    if not fp.exists():
        raise HTTPException(404, detail=f"第{day}天没有日记")
    return DiaryResponse(
        day=day,
        content=fp.read_text(encoding="utf-8", errors="replace"),
        updated_at=datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc).isoformat(),
    )


@router.put("/{project_id}/{day}")
def write_diary(project_id: str, day: int, body: DiaryEntry):
    """写入/更新日记"""
    diary_dir = _diary_dir(project_id)
    fp = diary_dir / f"{day}.md"
    fp.write_text(body.content.strip(), encoding="utf-8")
    return {
        "status": "saved",
        "day": day,
        "content_length": len(body.content.strip()),
    }


@router.delete("/{project_id}/{day}")
def delete_diary(project_id: str, day: int):
    """删除日记"""
    diary_dir = _diary_dir(project_id)
    fp = diary_dir / f"{day}.md"
    if fp.exists():
        fp.unlink()
    return {"status": "deleted", "day": day}
