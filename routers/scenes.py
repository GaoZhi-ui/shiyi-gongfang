"""
场景管理路由

场景是章节的下级单元，每个场景包含：
  - 标题、状态、字数、场景摘要

存储方式：scenes/{chapter_id}.json（每个章节一个 JSON 文件，内含场景列表）

GET    /scenes/{chapter_id}                  — 列出某章节下所有场景
POST   /scenes/{chapter_id}                  — 创建新场景
PUT    /scenes/{chapter_id}/{scene_id}       — 更新指定场景
DELETE /scenes/{chapter_id}/{scene_id}       — 删除指定场景
POST   /scenes/{chapter_id}/reorder          — 重新排序场景

路径前缀 /api/v1/scenes
"""

import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from core.enums import SceneType

router = APIRouter(prefix="/scenes", tags=["scenes"])
BASE = Path(__file__).resolve().parent.parent

# ─── 存储目录 ───

SCENES_DIR = BASE / "scenes"
SCENES_DIR.mkdir(exist_ok=True)

ALLOWED_STATUSES = {"draft", "written", "revised", "final"}
ALLOWED_SCENE_TYPES = {t.value for t in SceneType}

# ─── 异常定义 ───


class ScenePathTraversalError(Exception):
    pass


# ─── 安全文件操作 ───


def _scenes_file(chapter_id: str) -> Path:
    """解析场景文件路径（防路径穿越）"""
    safe_name = Path(chapter_id).name  # 去除路径分隔符，只取文件名部分
    if safe_name != chapter_id:
        raise ScenePathTraversalError(f"无效的 chapter_id: {chapter_id}")
    target = (SCENES_DIR / safe_name).with_suffix(".json")
    target = target.resolve()
    if not str(target).startswith(str(SCENES_DIR.resolve())):
        raise ScenePathTraversalError(f"路径越界: {chapter_id}")
    return target


def _load_scenes(chapter_id: str) -> list[dict]:
    """从文件加载某个章节的场景列表"""
    target = _scenes_file(chapter_id)
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, ValueError):
        return []


def _save_scenes(chapter_id: str, scenes: list[dict]):
    """保存某个章节的场景列表到文件"""
    target = _scenes_file(chapter_id)
    target.write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ─── Pydantic 模型 ───


class SceneItem(BaseModel):
    """场景数据结构"""
    id: str
    chapter_id: str
    title: str
    scene_type: SceneType = SceneType.NARRATION
    status: str = "draft"
    word_count: int = 0
    summary: str = ""
    order: int = 0
    created_at: str = ""
    updated_at: str = ""


class SceneCreate(BaseModel):
    title: str = Field(default="新场景", max_length=200, description="场景标题")
    scene_type: SceneType = Field(default=SceneType.NARRATION, description="场景类型")
    status: str = Field(default="draft", description="状态: draft/written/revised/final")
    word_count: int = Field(default=0, ge=0, description="场景字数")
    summary: str = Field(default="", max_length=2000, description="场景摘要")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(f"status 必须是 {ALLOWED_STATUSES} 之一")
        return v

    @field_validator("scene_type")
    @classmethod
    def validate_scene_type(cls, v: SceneType) -> SceneType:
        if v.value not in ALLOWED_SCENE_TYPES:
            raise ValueError(f"scene_type 必须是 {list(SceneType)} 之一")
        return v


class SceneUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    scene_type: SceneType | None = Field(default=None, description="场景类型")
    status: str | None = Field(default=None)
    word_count: int | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"status 必须是 {ALLOWED_STATUSES} 之一")
        return v


class SceneReorder(BaseModel):
    scene_ids: list[str] = Field(..., min_length=1, description="按新顺序排列的场景 ID 列表")


# ─── 帮助函数 ───


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_scene(scenes: list[dict], scene_id: str) -> int:
    """查找场景在列表中的索引，未找到返回 -1"""
    for i, s in enumerate(scenes):
        if s.get("id") == scene_id:
            return i
    return -1


# ─── 路由 ───


@router.get("/{chapter_id}")
def list_scenes(chapter_id: str):
    """列出某章节下所有场景，按 order 排序"""
    try:
        scenes = _load_scenes(chapter_id)
    except ScenePathTraversalError:
        raise HTTPException(400, detail={"code": "INVALID_CHAPTER_ID", "message": "无效的章节 ID"})

    scenes.sort(key=lambda s: s.get("order", 0))
    return {"chapter_id": chapter_id, "scenes": scenes}


@router.post("/{chapter_id}", status_code=201)
def create_scene(chapter_id: str, body: SceneCreate):
    """在指定章节下创建新场景"""
    try:
        scenes = _load_scenes(chapter_id)
    except ScenePathTraversalError:
        raise HTTPException(400, detail={"code": "INVALID_CHAPTER_ID", "message": "无效的章节 ID"})

    now = _now()
    scene = {
        "id": uuid.uuid4().hex[:12],
        "chapter_id": chapter_id,
        "title": body.title,
        "scene_type": body.scene_type.value,
        "status": body.status,
        "word_count": body.word_count,
        "summary": body.summary,
        "order": len(scenes),  # 追加到末尾
        "created_at": now,
        "updated_at": now,
    }

    scenes.append(scene)
    _save_scenes(chapter_id, scenes)

    return {"status": "created", "scene": scene}


@router.put("/{chapter_id}/{scene_id}")
def update_scene(chapter_id: str, scene_id: str, body: SceneUpdate):
    """更新指定场景的字段"""
    try:
        scenes = _load_scenes(chapter_id)
    except ScenePathTraversalError:
        raise HTTPException(400, detail={"code": "INVALID_CHAPTER_ID", "message": "无效的章节 ID"})

    idx = _find_scene(scenes, scene_id)
    if idx == -1:
        raise HTTPException(404, detail={
            "code": "SCENE_NOT_FOUND",
            "message": f"场景不存在: {scene_id}",
        })

    scene = scenes[idx]
    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if value is not None:
            scene[key] = value
    scene["updated_at"] = _now()

    scenes[idx] = scene
    _save_scenes(chapter_id, scenes)

    return {"status": "updated", "scene": scene}


@router.delete("/{chapter_id}/{scene_id}")
def delete_scene(chapter_id: str, scene_id: str):
    """删除指定场景"""
    try:
        scenes = _load_scenes(chapter_id)
    except ScenePathTraversalError:
        raise HTTPException(400, detail={"code": "INVALID_CHAPTER_ID", "message": "无效的章节 ID"})

    idx = _find_scene(scenes, scene_id)
    if idx == -1:
        raise HTTPException(404, detail={
            "code": "SCENE_NOT_FOUND",
            "message": f"场景不存在: {scene_id}",
        })

    deleted = scenes.pop(idx)
    # 重新整理 order 顺序
    for i, s in enumerate(scenes):
        s["order"] = i
    _save_scenes(chapter_id, scenes)

    return {"status": "deleted", "scene_id": scene_id, "title": deleted.get("title")}


@router.post("/{chapter_id}/reorder")
def reorder_scenes(chapter_id: str, body: SceneReorder):
    """按 scene_ids 顺序重新排列场景"""
    try:
        scenes = _load_scenes(chapter_id)
    except ScenePathTraversalError:
        raise HTTPException(400, detail={"code": "INVALID_CHAPTER_ID", "message": "无效的章节 ID"})

    scene_map = {s["id"]: s for s in scenes}
    for sid in body.scene_ids:
        if sid not in scene_map:
            raise HTTPException(400, detail={
                "code": "SCENE_NOT_FOUND",
                "message": f"场景 ID 不存在于当前章节: {sid}",
            })

    if len(body.scene_ids) != len(scenes):
        raise HTTPException(400, detail={
            "code": "SCENE_COUNT_MISMATCH",
            "message": f"提供的场景 ID 数量 ({len(body.scene_ids)}) 与实际场景数量 ({len(scenes)}) 不匹配",
        })

    reordered = []
    for order, sid in enumerate(body.scene_ids):
        s = scene_map[sid]
        s["order"] = order
        reordered.append(s)

    _save_scenes(chapter_id, reordered)

    return {"status": "reordered", "chapter_id": chapter_id, "scenes": reordered}
