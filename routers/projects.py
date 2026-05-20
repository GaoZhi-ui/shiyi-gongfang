"""
项目路由 — 多项目支持

GET    /projects              — 列出所有项目
POST   /projects              — 创建新项目（name, template="empty"）
DELETE /projects/{id}         — 删除项目
POST   /projects/{id}/duplicate  — 复制项目

路径前缀 /api/v1/projects

每个项目在 projects/ 下独立存储：
  projects/{id}/
    ├── config.json         # 项目配置
    ├── chapters/           # 章节文件
    ├── knowledge/          # 知识库文件
    └── scenes/             # 场景文件
"""

import json, shutil, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from routers.sanitize import sanitize_text

router = APIRouter(prefix="/projects", tags=["projects"])
BASE = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE / "projects"
TEMPLATES_DIR = BASE / "templates"

PROJECTS_DIR.mkdir(exist_ok=True)


# ─── 异常 ───

class ProjectNotFound(Exception):
    pass
class ProjectAlreadyExists(Exception):
    pass
class TemplateNotFound(Exception):
    pass
class ProjectOperationError(Exception):
    pass


# ─── 工具函数 ───

def _generate_id() -> str:
    """生成短 UUID 作为项目 ID"""
    return uuid.uuid4().hex[:12]


def _list_projects() -> list[dict]:
    """扫描 projects/ 目录，返回所有项目摘要"""
    results = []
    if not PROJECTS_DIR.is_dir():
        return results
    for entry in sorted(PROJECTS_DIR.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        config_path = entry / "config.json"
        if not config_path.exists():
            continue
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        results.append({
            "id": entry.name,
            "name": cfg.get("name", entry.name),
            "template": cfg.get("template", "default"),
            "description": cfg.get("description", ""),
            "created_at": cfg.get("created_at", ""),
            "updated_at": cfg.get("updated_at", ""),
            "stats": {
                "chapters": len(list((entry / "chapters").glob("*.md"))) if (entry / "chapters").is_dir() else 0,
                "knowledge_files": len(list((entry / "knowledge").rglob("*.md"))) if (entry / "knowledge").is_dir() else 0,
                "scenes": len(list((entry / "scenes").glob("*.md"))) if (entry / "scenes").is_dir() else 0,
            },
        })
    return results


def _find_project(project_id: str) -> Path:
    """查找项目目录，不存在则抛 ProjectNotFound"""
    proj_dir = (PROJECTS_DIR / project_id).resolve()
    if not str(proj_dir).startswith(str(PROJECTS_DIR.resolve())):
        raise ProjectOperationError("路径越界")
    if not proj_dir.is_dir():
        raise ProjectNotFound(f"项目 '{project_id}' 不存在")
    return proj_dir


def _load_config(proj_dir: Path) -> dict:
    """加载项目配置"""
    cfg_path = proj_dir / "config.json"
    if not cfg_path.exists():
        raise ProjectNotFound("项目配置缺失")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _save_config(proj_dir: Path, cfg: dict):
    """保存项目配置"""
    cfg_path = proj_dir / "config.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _init_project_dir(proj_dir: Path, cfg: dict):
    """创建初始项目目录结构"""
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "chapters").mkdir(exist_ok=True)
    (proj_dir / "knowledge").mkdir(exist_ok=True)
    (proj_dir / "scenes").mkdir(exist_ok=True)
    _save_config(proj_dir, cfg)


# ─── Pydantic 模型 ───

class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="项目名称")
    template: str = Field("default", description="模板名称: default / arknights")

class CreateProjectResponse(BaseModel):
    id: str
    name: str
    template: str
    created_at: str
    message: str

class ProjectInfo(BaseModel):
    id: str
    name: str
    template: str
    description: str
    created_at: str
    updated_at: str
    stats: dict

class ProjectListResponse(BaseModel):
    projects: list[ProjectInfo]
    count: int

class DeleteProjectResponse(BaseModel):
    status: str
    message: str

class DuplicateProjectResponse(BaseModel):
    id: str
    name: str
    message: str


# ─── 写作规范管理 ───

DEFAULT_WRITING_GUIDE = {
    "style": "冷峻克制",
    "tone": "严肃",
    "forbidden_words": [],
    "character_names": [],
    "place_names": [],
    "max_sentence_length": 40,
    "dialogue_density_target": 0.25,
    "description": "项目的写作风格描述",
}


class WritingGuideResponse(BaseModel):
    style: str = Field(default="冷峻克制", description="写作风格")
    tone: str = Field(default="严肃", description="语调")
    forbidden_words: list[str] = Field(default_factory=list, description="禁用词")
    character_names: list[str] = Field(default_factory=list, description="角色名")
    place_names: list[str] = Field(default_factory=list, description="地名")
    max_sentence_length: int = Field(default=40, ge=10, le=100, description="最大句子长度")
    dialogue_density_target: float = Field(default=0.25, ge=0.0, le=1.0, description="对话密度目标")
    description: str = Field(default="项目的写作风格描述", description="写作风格描述")


class WritingGuideUpdate(BaseModel):
    style: str = Field(default="冷峻克制", description="写作风格")
    tone: str = Field(default="严肃", description="语调")
    forbidden_words: list[str] = Field(default_factory=list, description="禁用词")
    character_names: list[str] = Field(default_factory=list, description="角色名")
    place_names: list[str] = Field(default_factory=list, description="地名")
    max_sentence_length: int = Field(default=40, ge=10, le=100, description="最大句子长度")
    dialogue_density_target: float = Field(default=0.25, ge=0.0, le=1.0, description="对话密度目标")
    description: str = Field(default="项目的写作风格描述", description="写作风格描述")


@router.get("/{project_id}/guide", response_model=WritingGuideResponse)
def get_writing_guide(project_id: str):
    """获取项目的写作规范"""
    try:
        proj_dir = _find_project(project_id)
    except ProjectNotFound as e:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": str(e)})
    except ProjectOperationError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})

    guide_path = proj_dir / "writing-guide.json"
    if not guide_path.exists():
        return WritingGuideResponse(**DEFAULT_WRITING_GUIDE)

    try:
        data = json.loads(guide_path.read_text(encoding="utf-8"))
        return WritingGuideResponse(**data)
    except (json.JSONDecodeError, OSError):
        return WritingGuideResponse(**DEFAULT_WRITING_GUIDE)


@router.put("/{project_id}/guide", response_model=WritingGuideResponse)
def update_writing_guide(project_id: str, body: WritingGuideUpdate):
    """更新项目的写作规范"""
    try:
        proj_dir = _find_project(project_id)
    except ProjectNotFound as e:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": str(e)})
    except ProjectOperationError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})

    guide_path = proj_dir / "writing-guide.json"
    try:
        guide_path.write_text(
            json.dumps(body.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        raise HTTPException(500, detail={
            "code": "GUIDE_SAVE_FAILED",
            "message": f"保存写作规范失败: {e}",
        })

    return WritingGuideResponse(**body.model_dump())


# ─── 路由 ───

@router.get("", response_model=ProjectListResponse)
def list_projects():
    """列出所有项目"""
    projects = _list_projects()
    return ProjectListResponse(projects=[ProjectInfo(**p) for p in projects], count=len(projects))


@router.post("", response_model=CreateProjectResponse, status_code=201)
def create_project(body: CreateProjectRequest):
    """创建新项目，可选择模板"""
    # 解析模板
    template_name = body.template or "default"
    tmpl_dir = (TEMPLATES_DIR / template_name).resolve()
    if not tmpl_dir.is_dir():
        raise HTTPException(400, detail={
            "code": "TEMPLATE_NOT_FOUND",
            "message": f"模板 '{template_name}' 不存在",
            "available": [d.name for d in TEMPLATES_DIR.iterdir() if d.is_dir()],
        })

    # 生成项目 ID
    project_id = _generate_id()
    proj_dir = (PROJECTS_DIR / project_id).resolve()

    # 复制模板
    try:
        shutil.copytree(tmpl_dir, proj_dir, dirs_exist_ok=True)
    except OSError as e:
        raise HTTPException(500, detail={
            "code": "PROJECT_CREATE_FAILED",
            "message": f"创建项目失败: {e}",
        })

    # 更新 config.json
    now = datetime.now(timezone.utc).isoformat()
    cfg_path = proj_dir / "config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        clean_name = sanitize_text(body.name)
        cfg["name"] = clean_name
        cfg["created_at"] = now
        cfg["updated_at"] = now
        cfg["description"] = cfg.get("description", "")
        _save_config(proj_dir, cfg)
    else:
        # 模板没有 config.json，创建默认
        clean_name = sanitize_text(body.name)
        cfg = {
            "name": clean_name,
            "template": template_name,
            "description": "",
            "created_at": now,
            "updated_at": now,
            "review_rules": {
                "word_count_baseline": 2500,
                "word_count_tolerance": 300,
                "sentence_density_target": 5.0,
                "sentence_density_tolerance": 1.0,
            },
        }
        _init_project_dir(proj_dir, cfg)

    return CreateProjectResponse(
        id=project_id,
        name=body.name,
        template=template_name,
        created_at=now,
        message=f"项目 '{body.name}' 创建成功",
    )


@router.delete("/{project_id}", response_model=DeleteProjectResponse)
def delete_project(project_id: str):
    """删除指定项目"""
    try:
        proj_dir = _find_project(project_id)
    except ProjectNotFound as e:
        raise HTTPException(404, detail={
            "code": "PROJECT_NOT_FOUND",
            "message": str(e),
        })
    except ProjectOperationError:
        raise HTTPException(423, detail={
            "code": "PATH_TRAVERSAL",
            "message": "路径越界",
        })

    # 确认是 projects/ 下的有效子目录，而非 projects/ 自身
    if proj_dir == PROJECTS_DIR.resolve():
        raise HTTPException(400, detail={
            "code": "INVALID_OPERATION",
            "message": "不能删除根目录",
        })

    try:
        shutil.rmtree(proj_dir)
    except OSError as e:
        raise HTTPException(500, detail={
            "code": "PROJECT_DELETE_FAILED",
            "message": f"删除项目失败: {e}",
        })

    return DeleteProjectResponse(status="ok", message=f"项目 '{project_id}' 已删除")


@router.post("/{project_id}/duplicate", response_model=DuplicateProjectResponse)
def duplicate_project(project_id: str):
    """复制项目（包括所有章节、知识库、场景文件）"""
    try:
        proj_dir = _find_project(project_id)
        cfg = _load_config(proj_dir)
    except ProjectNotFound as e:
        raise HTTPException(404, detail={
            "code": "PROJECT_NOT_FOUND",
            "message": str(e),
        })
    except ProjectOperationError:
        raise HTTPException(423, detail={
            "code": "PATH_TRAVERSAL",
            "message": "路径越界",
        })

    new_id = _generate_id()
    new_dir = (PROJECTS_DIR / new_id).resolve()

    try:
        shutil.copytree(proj_dir, new_dir, dirs_exist_ok=True)
    except OSError as e:
        raise HTTPException(500, detail={
            "code": "PROJECT_DUPLICATE_FAILED",
            "message": f"复制项目失败: {e}",
        })

    # 更新新项目的配置
    now = datetime.now(timezone.utc).isoformat()
    new_cfg = dict(cfg)
    new_cfg["name"] = cfg.get("name", "未命名项目") + " (副本)"
    new_cfg["created_at"] = now
    new_cfg["updated_at"] = now
    _save_config(new_dir, new_cfg)

    return DuplicateProjectResponse(
        id=new_id,
        name=new_cfg["name"],
        message=f"项目已复制为 '{new_cfg['name']}' (ID: {new_id})",
    )
