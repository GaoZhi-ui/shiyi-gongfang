"""
角色关系图 API

管理项目中的角色及其关系，支持可视化图谱所需的 nodes+edges 格式。

GET    /characters               — 列出角色（?project_id=xxx）
POST   /characters               — 创建角色
PUT    /characters/{id}          — 更新角色（?project_id=xxx）
DELETE /characters/{id}          — 删除角色（?project_id=xxx）
GET    /characters/relations     — 获取所有关系（nodes+edges 格式，?project_id=xxx）
POST   /characters/relations     — 创建/更新关系

数据存储：characters/{project_id}.json

JSON 结构：
{
  "characters": [ ... ],
  "relations": [ { "source": "id1", "target": "id2", "type": "...", "label": "..." }, ... ]
}
"""

import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/characters", tags=["characters"])
BASE = Path(__file__).resolve().parent.parent
CHARS_DIR = BASE / "characters"
CHARS_DIR.mkdir(exist_ok=True)


# ─── 路径安全 ───


class CharPathError(Exception):
    pass


def _chars_file(project_id: str) -> Path:
    safe = Path(project_id).name
    if safe != project_id:
        raise CharPathError(f"无效的 project_id: {project_id}")
    target = (CHARS_DIR / safe).with_suffix(".json")
    target = target.resolve()
    if not str(target).startswith(str(CHARS_DIR.resolve())):
        raise CharPathError("路径越界")
    return target


def _load_data(project_id: str) -> dict:
    """返回 { "characters": [...], "relations": [...] }"""
    target = _chars_file(project_id)
    if not target.exists():
        return {"characters": [], "relations": []}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return {
            "characters": data.get("characters", []),
            "relations": data.get("relations", []),
        }
    except (json.JSONDecodeError, ValueError):
        return {"characters": [], "relations": []}


def _save_data(project_id: str, data: dict):
    target = _chars_file(project_id)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Pydantic 模型 ───


class CharacterCreate(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目 ID")
    name: str = Field(..., min_length=1, max_length=64, description="角色名")
    description: str = Field(default="", max_length=2000, description="角色描述")
    traits: list[str] = Field(default_factory=list, description="性格/特征标签")
    avatar_color: str = Field(default="#4A90D9", description="头像/标识颜色")


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    traits: list[str] | None = Field(default=None)
    avatar_color: str | None = Field(default=None)


class CharacterResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    traits: list[str] = []
    avatar_color: str = "#4A90D9"
    relation_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class RelationCreate(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目 ID")
    source: str = Field(..., min_length=1, description="源角色 ID")
    target: str = Field(..., min_length=1, description="目标角色 ID")
    type: str = Field(default="neutral", description="关系类型: ally/enemy/love/family/neutral")
    label: str = Field(default="", max_length=100, description="关系标签，如'战友'")


class RelationResponse(BaseModel):
    source: str
    target: str
    type: str
    label: str = ""


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


# ─── 帮助函数 ───


def _build_character(char: dict, relation_count: int = 0) -> dict:
    return {
        "id": char["id"],
        "name": char["name"],
        "description": char.get("description", ""),
        "traits": char.get("traits", []),
        "avatar_color": char.get("avatar_color", "#4A90D9"),
        "relation_count": relation_count,
        "created_at": char.get("created_at", ""),
        "updated_at": char.get("updated_at", ""),
    }


def _count_relations(char_id: str, relations: list[dict]) -> int:
    return sum(1 for r in relations if r["source"] == char_id or r["target"] == char_id)


# ─── API: 角色 CRUD ───

# 注意：/relations 路径必须定义在 /{id} 之前，否则 FastAPI 会将 "relations" 匹配为 id


@router.get("/relations", response_model=GraphResponse)
async def list_relations(project_id: str = Query(..., description="项目 ID")):
    """获取图谱数据，以 nodes+edges 格式返回"""
    data = _load_data(project_id)
    characters = data["characters"]
    relations = data["relations"]

    char_map = {c["id"]: c for c in characters}

    nodes = [
        {
            "id": c["id"],
            "name": c["name"],
            "traits": c.get("traits", []),
            "avatar_color": c.get("avatar_color", "#4A90D9"),
        }
        for c in characters
    ]

    edges = []
    for r in relations:
        if r["source"] in char_map and r["target"] in char_map:
            edges.append({
                "source": r["source"],
                "target": r["target"],
                "type": r.get("type", "neutral"),
                "label": r.get("label", ""),
            })

    return GraphResponse(nodes=nodes, edges=edges)


@router.post("/relations", response_model=RelationResponse, status_code=201)
async def create_relation(body: RelationCreate):
    """创建或更新角色关系（同 source+target 的已有关系会被覆盖）"""
    data = _load_data(body.project_id)
    characters = data["characters"]
    relations = data["relations"]

    char_ids = {c["id"] for c in characters}
    if body.source not in char_ids:
        raise HTTPException(400, f"源角色 '{body.source}' 不存在")
    if body.target not in char_ids:
        raise HTTPException(400, f"目标角色 '{body.target}' 不存在")
    if body.source == body.target:
        raise HTTPException(400, "不能建立与自己的关系")

    # 覆盖已有同向关系
    existing = [
        i for i, r in enumerate(relations)
        if r["source"] == body.source and r["target"] == body.target
    ]
    new_rel = {
        "source": body.source,
        "target": body.target,
        "type": body.type,
        "label": body.label,
    }
    if existing:
        relations[existing[0]] = new_rel
    else:
        relations.append(new_rel)

    _save_data(body.project_id, {"characters": characters, "relations": relations})
    return RelationResponse(**new_rel)


@router.get("", response_model=list[CharacterResponse])
async def list_characters(project_id: str = Query(..., description="项目 ID")):
    """列出项目中所有角色"""
    data = _load_data(project_id)
    return [
        _build_character(c, _count_relations(c["id"], data["relations"]))
        for c in data["characters"]
    ]


@router.post("", response_model=CharacterResponse, status_code=201)
async def create_character(body: CharacterCreate):
    """创建新角色"""
    data = _load_data(body.project_id)
    new_char = {
        "id": uuid.uuid4().hex[:12],
        "name": body.name,
        "description": body.description,
        "traits": body.traits,
        "avatar_color": body.avatar_color,
        "created_at": _now(),
        "updated_at": _now(),
    }
    data["characters"].append(new_char)
    _save_data(body.project_id, data)
    return _build_character(new_char)


@router.put("/{char_id}", response_model=CharacterResponse)
async def update_character(char_id: str, body: CharacterUpdate,
                            project_id: str = Query(..., description="项目 ID")):
    """更新角色信息"""
    data = _load_data(project_id)
    idx = next((i for i, c in enumerate(data["characters"]) if c["id"] == char_id), -1)
    if idx == -1:
        raise HTTPException(404, f"角色 '{char_id}' 不存在")

    char = data["characters"][idx]
    if body.name is not None:
        char["name"] = body.name
    if body.description is not None:
        char["description"] = body.description
    if body.traits is not None:
        char["traits"] = body.traits
    if body.avatar_color is not None:
        char["avatar_color"] = body.avatar_color
    char["updated_at"] = _now()

    data["characters"][idx] = char
    _save_data(project_id, data)
    return _build_character(char, _count_relations(char_id, data["relations"]))


@router.delete("/{char_id}", status_code=204)
async def delete_character(char_id: str,
                            project_id: str = Query(..., description="项目 ID")):
    """删除角色（同时清理所有相关关系）"""
    data = _load_data(project_id)
    idx = next((i for i, c in enumerate(data["characters"]) if c["id"] == char_id), -1)
    if idx == -1:
        raise HTTPException(404, f"角色 '{char_id}' 不存在")

    data["characters"].pop(idx)
    # 清理涉及该角色的所有关系
    data["relations"] = [
        r for r in data["relations"]
        if r["source"] != char_id and r["target"] != char_id
    ]
    _save_data(project_id, data)

    return None
