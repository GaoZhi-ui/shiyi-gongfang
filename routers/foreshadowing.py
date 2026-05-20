"""
伏笔追踪 API

管理故事中的伏笔/铺垫元素，追踪设置章节和预期回收章节。

GET    /foreshadowing               — 列出伏笔（?project_id=xxx）
POST   /foreshadowing               — 创建伏笔
PUT    /foreshadowing/{id}          — 更新伏笔状态（?project_id=xxx）
DELETE /foreshadowing/{id}          — 删除伏笔（?project_id=xxx）

数据存储：foreshadowing/{project_id}.json
"""

import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/foreshadowing", tags=["foreshadowing"])
BASE = Path(__file__).resolve().parent.parent
FORESHADOWING_DIR = BASE / "foreshadowing"
FORESHADOWING_DIR.mkdir(exist_ok=True)

ALLOWED_TYPES = {"plot", "character", "object", "lore"}
ALLOWED_STATUSES = {"pending", "revealed", "resolved", "abandoned"}


# ─── 路径安全 ───


class ForeshadowingPathError(Exception):
    pass


def _fs_file(project_id: str) -> Path:
    safe = Path(project_id).name
    if safe != project_id:
        raise ForeshadowingPathError(f"无效的 project_id: {project_id}")
    target = (FORESHADOWING_DIR / safe).with_suffix(".json")
    target = target.resolve()
    if not str(target).startswith(str(FORESHADOWING_DIR.resolve())):
        raise ForeshadowingPathError("路径越界")
    return target


def _load_all(project_id: str) -> list[dict]:
    target = _fs_file(project_id)
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _save_all(project_id: str, items: list[dict]):
    target = _fs_file(project_id)
    target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Pydantic 模型 ───


class ForeshadowingCreate(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目 ID")
    title: str = Field(..., min_length=1, max_length=200, description="伏笔标题")
    description: str = Field(default="", max_length=2000, description="伏笔描述")
    type: str = Field(default="plot", description=f"伏笔类型: {ALLOWED_TYPES}")
    chapter_planted: int = Field(default=1, ge=1, description="设置章节")
    chapter_expected: int = Field(default=1, ge=1, description="预期回收章节")
    status: str = Field(default="pending", description=f"状态: {ALLOWED_STATUSES}")
    strength: int = Field(default=3, ge=1, le=5, description="伏笔力度 1-5")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ALLOWED_TYPES:
            raise ValueError(f"type 必须是 {ALLOWED_TYPES} 之一")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(f"status 必须是 {ALLOWED_STATUSES} 之一")
        return v

    @field_validator("chapter_expected")
    @classmethod
    def expected_ge_planted(cls, v: int, info) -> int:
        # 只在 chapter_planted 也传了的情况下检查
        if "chapter_planted" in info.data and v < info.data["chapter_planted"]:
            raise ValueError("预期回收章节不能早于设置章节")
        return v


class ForeshadowingUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    type: str | None = Field(default=None)
    chapter_planted: int | None = Field(default=None, ge=1)
    chapter_expected: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None)
    strength: int | None = Field(default=None, ge=1, le=5)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_TYPES:
            raise ValueError(f"type 必须是 {ALLOWED_TYPES} 之一")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"status 必须是 {ALLOWED_STATUSES} 之一")
        return v


class ForeshadowingResponse(BaseModel):
    id: str
    title: str
    description: str = ""
    type: str
    chapter_planted: int
    chapter_expected: int
    status: str
    strength: int
    gap: int = 0  # chapter_expected - chapter_planted
    created_at: str = ""
    updated_at: str = ""


# ─── 帮助函数 ───


def _build_response(item: dict) -> dict:
    planted = item.get("chapter_planted", 1)
    expected = item.get("chapter_expected", 1)
    return {
        "id": item["id"],
        "title": item["title"],
        "description": item.get("description", ""),
        "type": item.get("type", "plot"),
        "chapter_planted": planted,
        "chapter_expected": expected,
        "status": item.get("status", "pending"),
        "strength": item.get("strength", 3),
        "gap": max(expected - planted, 0),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }


# ─── API 端点 ───


@router.get("", response_model=list[ForeshadowingResponse])
async def list_foreshadowing(project_id: str = Query(..., description="项目 ID")):
    """列出项目中所有伏笔"""
    items = _load_all(project_id)
    items.sort(key=lambda x: (x.get("status", "pending"), x.get("chapter_planted", 1)))
    return [_build_response(item) for item in items]


@router.post("", response_model=ForeshadowingResponse, status_code=201)
async def create_foreshadowing(body: ForeshadowingCreate):
    """创建新伏笔"""
    items = _load_all(body.project_id)
    new_item = {
        "id": uuid.uuid4().hex[:12],
        "title": body.title,
        "description": body.description,
        "type": body.type,
        "chapter_planted": body.chapter_planted,
        "chapter_expected": body.chapter_expected,
        "status": body.status,
        "strength": body.strength,
        "created_at": _now(),
        "updated_at": _now(),
    }
    # chapter_expected 不小于 chapter_planted 的校验已在 Pydantic 中完成
    items.append(new_item)
    _save_all(body.project_id, items)
    return _build_response(new_item)


@router.put("/{fs_id}", response_model=ForeshadowingResponse)
async def update_foreshadowing(fs_id: str, body: ForeshadowingUpdate,
                                project_id: str = Query(..., description="项目 ID")):
    """更新伏笔信息（常用于推进状态）"""
    items = _load_all(project_id)
    idx = next((i for i, item in enumerate(items) if item["id"] == fs_id), -1)
    if idx == -1:
        raise HTTPException(404, f"伏笔 '{fs_id}' 不存在")

    item = items[idx]
    if body.title is not None:
        item["title"] = body.title
    if body.description is not None:
        item["description"] = body.description
    if body.type is not None:
        item["type"] = body.type
    if body.chapter_planted is not None:
        item["chapter_planted"] = body.chapter_planted
    if body.chapter_expected is not None:
        item["chapter_expected"] = body.chapter_expected
    if body.status is not None:
        item["status"] = body.status
    if body.strength is not None:
        item["strength"] = body.strength
    item["updated_at"] = _now()

    items[idx] = item
    _save_all(project_id, items)
    return _build_response(item)


@router.delete("/{fs_id}", status_code=204)
async def delete_foreshadowing(fs_id: str,
                                project_id: str = Query(..., description="项目 ID")):
    """删除伏笔"""
    items = _load_all(project_id)
    idx = next((i for i, item in enumerate(items) if item["id"] == fs_id), -1)
    if idx == -1:
        raise HTTPException(404, f"伏笔 '{fs_id}' 不存在")

    items.pop(idx)
    _save_all(project_id, items)
    return None
